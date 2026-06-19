# tracking/views/university_supervisor_views.py
from io import BytesIO

from .common import is_university_supervisor, is_industry_supervisor, is_coordinator
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Case, IntegerField, Prefetch, Value, When
from django.http import HttpResponseForbidden, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from placements.models import Placement
from tracking.forms import AcademicEvaluationForm, SiteVisitScheduleForm, SiteVisitReportForm
from tracking.models import (
    WeeklyLog, WeeklyLogEntry, SiteVisit, SiteVisitReport,
    IndustryEvaluation, AcademicEvaluation, SupervisorResultsReport, IndustrySupervisorResultsReport,
    StudentEvaluation, StudentInternshipReport, Notification
)

from .common import (
    is_university_supervisor,
    _get_staff_profile,
    _get_latest_report,
    build_results_rows,
    ensure_dashboard_notification,
    get_notification_context,
    notify,
    notify_coordinators,
    resolve_dashboard_notification,
)


# -------------------------------------------------------------------
# SUPERVISORS: ASSIGNED STUDENTS (UNIVERSITY)
# -------------------------------------------------------------------
@login_required
def supervisor_students(request):
    u = request.user

    # -------------------------
    # ✅ UNIVERSITY SUPERVISOR
    # -------------------------
    if is_university_supervisor(u):
        staff = getattr(u, "staff_profile", None)
        if not staff:
            return HttpResponseForbidden("Staff profile not set. Admin must create StaffProfile for this user.")

        placements = (
            Placement.objects
            .filter(university_supervisor=staff)
            .exclude(status__in=["completed", "terminated"])
            .select_related("company", "request", "request__student", "request__student__user")
            .order_by("-created_at")
        )

        ind_map = {
            e.placement_id: e
            for e in IndustryEvaluation.objects.filter(placement__in=placements, status="submitted")
        }

        ac_map = {
            e.placement_id: e
            for e in AcademicEvaluation.objects.filter(placement__in=placements, supervisor_user=u)
        }
        report_map = {
            r.placement_id: r
            for r in StudentInternshipReport.objects.filter(placement__in=placements, status="submitted")
        }

        for p in placements:
            ind = ind_map.get(p.id)
            ac = ac_map.get(p.id)
            p.internship_report = report_map.get(p.id)

            # Industry score
            if ind:
                p.eval_status = ind.status
                p.eval_total = ind.total_marks
                p.eval_max = ind.max_marks
                p.eval_score10 = ind.score_out_of_10
                p.eval_score100 = ind.score_out_of_100
            else:
                p.eval_status = None
                p.eval_total = None
                p.eval_max = 65
                p.eval_score10 = None
                p.eval_score100 = None

            # Academic score
            if ac:
                p.ac_eval_status = ac.status
                p.ac_eval_total = ac.total_marks
                p.ac_eval_max = ac.max_marks
                p.ac_eval_score10 = ac.score_out_of_10
                p.ac_eval_score100 = ac.score_out_of_100
            else:
                p.ac_eval_status = None
                p.ac_eval_total = None
                p.ac_eval_max = 25
                p.ac_eval_score10 = None
                p.ac_eval_score100 = None

            # Average only when both submitted
            if p.eval_status == "submitted" and p.ac_eval_status == "submitted":
                avg100 = (float(p.eval_score100) + float(p.ac_eval_score100)) / 2.0
                p.avg_score100 = avg100
                p.avg_score10 = avg100 / 10.0
            else:
                p.avg_score100 = None
                p.avg_score10 = None

        latest_report = _get_supervisor_working_report(u)
        report_rows = latest_report.rows if latest_report else build_results_rows(u, staff)
        report_summary = _results_report_summary(report_rows)

        return render(request, "tracking/supervisor_students.html", {
            "placements": placements,
            "view_mode": "university",
            "latest_report": latest_report,
            "report_summary": report_summary,
        })

    # -------------------------
    # ✅ INDUSTRY SUPERVISOR
    # -------------------------
    if is_industry_supervisor(u):
        # prefer company from industry_profile (same pattern you used elsewhere)
        if not hasattr(u, "industry_profile") or not u.industry_profile.company:
            return HttpResponseForbidden("Industry profile/company not set. Admin must link this user to a company.")

        company = u.industry_profile.company

        placements = (
            Placement.objects
            .filter(company=company)
            .exclude(status__in=["completed", "terminated"])
            .select_related("company", "request", "request__student", "request__student__user", "university_supervisor")
            .order_by("-created_at")
        )

        eval_map = {
            e.placement_id: e
            for e in IndustryEvaluation.objects.filter(company=company, placement__in=placements)
        }

        for p in placements:
            ev = eval_map.get(p.id)
            if ev:
                p.eval_status = ev.status
                p.eval_total = ev.total_marks
                p.eval_max = ev.max_marks
                p.eval_score10 = ev.score_out_of_10
                p.eval_score100 = ev.score_out_of_100
            else:
                p.eval_status = None
                p.eval_total = None
                p.eval_max = 65
                p.eval_score10 = None
                p.eval_score100 = None

        return render(request, "tracking/supervisor_students.html", {
            "placements": placements,
            "company": company,
            "view_mode": "industry",
        })

    return HttpResponseForbidden("Supervisors only.")


# -------------------------------------------------------------------
# UNIVERSITY SUPERVISOR: APPROVED LOGS
# -------------------------------------------------------------------
@login_required
def supervisor_approved_logs(request):
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = getattr(request.user, "staff_profile", None)
    if not staff:
        return HttpResponseForbidden("No staff profile found for this account.")

    logs = (
        WeeklyLog.objects
        .filter(
            status="approved_by_company",
            placement__university_supervisor=staff,
            placement__status="active",
        )
        .select_related(
            "placement",
            "placement__company",
            "placement__request__student",
            "placement__request__student__user",
        )
        .prefetch_related("attachments", Prefetch("entries", queryset=WeeklyLogEntry.objects.order_by("day")))
        .order_by("placement__request__student__reg_no", "-week_no")
    )

    return render(request, "tracking/supervisor_approved_logs.html", {"logs": logs})


# -------------------------------------------------------------------
# UNIVERSITY SUPERVISOR: VIEW SUBMITTED INDUSTRY EVALUATIONS (list)
# -------------------------------------------------------------------
@login_required
def supervisor_submitted_evaluations(request):
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = getattr(request.user, "staff_profile", None)
    if not staff:
        return HttpResponseForbidden("Staff profile not set.")

    evaluations = (
        IndustryEvaluation.objects
        .filter(status="submitted", placement__university_supervisor=staff)
        .select_related(
            "company",
            "placement",
            "placement__company",
            "placement__request",
            "placement__request__student",
            "placement__request__student__user",
        )
        .order_by("placement__request__student__reg_no", "-submitted_at")
    )

    return render(request, "tracking/supervisor_submitted_evaluations.html", {
        "evaluations": evaluations,
        "staff": staff,
    })


@login_required
def supervisor_industry_reports(request):
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = getattr(request.user, "staff_profile", None)
    if not staff:
        return HttpResponseForbidden("Staff profile not set.")

    reports = []
    for report in (
        IndustrySupervisorResultsReport.objects
        .filter(status="submitted")
        .select_related("company", "supervisor_user")
        .order_by("-submitted_at", "-updated_at")
    ):
        rows = [
            row for row in (report.rows or [])
            if row.get("university_supervisor_id") == request.user.id
        ]
        if rows:
            reports.append({
                "report": report,
                "rows": rows,
                "student_count": len(rows),
            })

    return render(request, "tracking/supervisor_industry_reports.html", {
        "reports": reports,
    })


@login_required
def supervisor_industry_report_detail(request, report_id):
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    report = get_object_or_404(
        IndustrySupervisorResultsReport.objects.select_related("company", "supervisor_user"),
        id=report_id,
        status="submitted",
    )
    rows = [
        row for row in (report.rows or [])
        if row.get("university_supervisor_id") == request.user.id
    ]
    if not rows:
        return HttpResponseForbidden("This report was not submitted to you.")

    return render(request, "tracking/supervisor_industry_report_detail.html", {
        "report": report,
        "rows": rows,
    })


# -------------------------------------------------------------------
# UNIVERSITY SUPERVISOR: ACADEMIC EVALUATION
# -------------------------------------------------------------------
ACADEMIC_EVAL_WINDOW_DAYS = 232

@login_required
def supervisor_evaluate_student(request, placement_id):
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = getattr(request.user, "staff_profile", None)
    if not staff:
        return HttpResponseForbidden("Staff profile not set.")

    placement = get_object_or_404(Placement, id=placement_id, university_supervisor=staff)

    today = timezone.localdate()
    if placement.end_date:
        days_to_end = (placement.end_date - today).days
        if days_to_end > ACADEMIC_EVAL_WINDOW_DAYS:
            return render(request, "tracking/academic_evaluation_not_allowed.html", {
                "placement": placement,
                "days_to_end": days_to_end,
                "window_days": ACADEMIC_EVAL_WINDOW_DAYS,
            })

    evaluation, _ = AcademicEvaluation.objects.get_or_create(
        placement=placement,
        defaults={
            "supervisor_user": request.user,
            "supervisor_name": getattr(request.user, "display_name", "") or request.user.get_username(),
            "status": "draft",
        }
    )

    if evaluation.status == "submitted":
        return render(request, "tracking/academic_evaluation_submitted_view.html", {
            "placement": placement,
            "evaluation": evaluation,
        })

    if request.method == "POST":
        form = AcademicEvaluationForm(request.POST, instance=evaluation)
        if form.is_valid():
            evaluation = form.save(commit=False)
            evaluation.supervisor_user = request.user

            action = request.POST.get("action", "save")
            if action == "submit":
                evaluation.submit(user=request.user)
                return redirect("supervisor_submitted_academic_evaluations")

            evaluation.status = "draft"
            evaluation.save()
            return redirect("supervisor_evaluate_student", placement_id=placement.id)
    else:
        form = AcademicEvaluationForm(instance=evaluation)

    return render(request, "tracking/academic_evaluation_form.html", {
        "placement": placement,
        "form": form,
        "evaluation": evaluation,
    })


@login_required
def supervisor_submitted_academic_evaluations(request):
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = getattr(request.user, "staff_profile", None)
    if not staff:
        return HttpResponseForbidden("Staff profile not set.")

    evaluations = (
        AcademicEvaluation.objects
        .filter(status="submitted", placement__university_supervisor=staff, supervisor_user=request.user)
        .select_related(
            "placement",
            "placement__company",
            "placement__request__student",
            "placement__request__student__user",
        )
        .order_by("placement__request__student__reg_no", "-submitted_at")
    )

    return render(request, "tracking/supervisor_submitted_academic_evaluations.html", {
        "evaluations": evaluations,
    })


# -------------------------------------------------------------------
# UNIVERSITY SUPERVISOR: RESULTS REPORT
# -------------------------------------------------------------------
def _results_report_summary(rows):
    rows = rows or []
    total = len(rows)
    industry_complete = sum(1 for r in rows if r.get("industry_100") is not None)
    academic_complete = sum(1 for r in rows if r.get("academic_100") is not None)
    complete = sum(1 for r in rows if r.get("average_100") is not None)
    incomplete = max(total - complete, 0)
    logs_ready = sum(
        1 for r in rows
        if int(r.get("required_weeks") or 0) > 0
        and int(r.get("approved_logs") or 0) >= int(r.get("required_weeks") or 0)
    )
    site_visits_done = sum(1 for r in rows if int(r.get("completed_visits") or 0) > 0)
    student_feedback_done = sum(1 for r in rows if r.get("student_feedback_submitted"))
    average_progress = round(
        sum(float(r.get("log_progress") or 0) for r in rows) / total,
        0,
    ) if total else 0
    return {
        "total": total,
        "industry_complete": industry_complete,
        "academic_complete": academic_complete,
        "complete": complete,
        "incomplete": incomplete,
        "logs_ready": logs_ready,
        "site_visits_done": site_visits_done,
        "student_feedback_done": student_feedback_done,
        "average_log_progress": average_progress,
        "ready": total > 0 and incomplete == 0,
    }


def _get_supervisor_working_report(supervisor_user, for_update=False):
    """
    Return the report the supervisor should work with now.
    Returned reports must appear before locked approved/submitted reports.
    """
    qs = SupervisorResultsReport.objects.filter(supervisor_user=supervisor_user)
    if for_update:
        qs = qs.select_for_update()
    return (
        qs.annotate(
            action_rank=Case(
                When(status="needs_changes", then=Value(5)),
                When(status="draft", then=Value(4)),
                When(status="submitted", then=Value(3)),
                When(status="resubmitted", then=Value(3)),
                When(status="approved", then=Value(2)),
                When(status="rejected", then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        .order_by("-action_rank", "-updated_at", "-submitted_at", "-created_at")
        .first()
    )


@login_required
def supervisor_results_report(request):
    if is_industry_supervisor(request.user):
        return redirect("industry_results_report")
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = getattr(request.user, "staff_profile", None)
    if not staff:
        return HttpResponseForbidden("Staff profile not set.")

    latest_report = _get_supervisor_working_report(request.user)
    live_rows = build_results_rows(request.user, staff)

    if latest_report:
        rows = latest_report.rows or []
    else:
        rows = live_rows

    report_summary = _results_report_summary(rows)
    live_report_summary = _results_report_summary(live_rows)
    report_has_live_updates = bool(
        latest_report
        and latest_report.status in ["draft", "needs_changes"]
        and (latest_report.rows or []) != live_rows
    )

    return render(request, "tracking/supervisor_results_report.html", {
        "rows": rows,
        "count": len(rows),
        "latest_report": latest_report,
        "report_summary": report_summary,
        "live_report_summary": live_report_summary,
        "report_has_live_updates": report_has_live_updates,
        "can_submit_report": report_summary["ready"] and (
            not latest_report or latest_report.status in ["draft", "needs_changes"]
        ),
        "report_is_editable": not latest_report or latest_report.status in ["draft", "needs_changes"],
    })


@login_required
@transaction.atomic
def supervisor_refresh_results_report(request):
    if request.method != "POST":
        return HttpResponseForbidden("POST only.")
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = getattr(request.user, "staff_profile", None)
    if not staff:
        return HttpResponseForbidden("Staff profile not set.")

    latest_report = _get_supervisor_working_report(request.user)
    if latest_report and latest_report.status not in ["draft", "needs_changes"]:
        messages.error(request, "This report is locked. The coordinator must request changes before it can be refreshed.")
        return redirect("supervisor_results_report")

    rows = build_results_rows(request.user, staff)

    report = _get_supervisor_working_report(request.user, for_update=True)

    if report and report.status not in ["draft", "needs_changes"]:
        messages.error(request, "This report is locked. The coordinator must request changes before it can be refreshed.")
        return redirect("supervisor_results_report")

    if not report:
        report = SupervisorResultsReport.objects.create(
            supervisor_user=request.user,
            status="draft",
            rows=rows
        )
    else:
        report.rows = rows
        report.save(update_fields=["rows", "updated_at"])

    messages.success(request, "Results report refreshed with the latest submitted marks.")

    return redirect("supervisor_results_report")


@login_required
def supervisor_results_report_pdf(request):
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = getattr(request.user, "staff_profile", None)
    if not staff:
        return HttpResponseForbidden("Staff profile not set.")

    latest_report = _get_supervisor_working_report(request.user)
    rows = latest_report.rows if latest_report else build_results_rows(request.user, staff)
    report_summary = _results_report_summary(rows)

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 50
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "Internship Results Report (University Supervisor)")
    y -= 18

    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Supervisor: {getattr(request.user, 'display_name', '') or request.user.get_username()}")
    y -= 14
    c.drawString(50, y, f"Generated: {timezone.now().strftime('%Y-%m-%d %H:%M')}")
    if latest_report:
        y -= 14
        c.drawString(50, y, f"Report Ref: #{latest_report.id}   Revision: {latest_report.revision}   Status: {latest_report.status.upper()}")
    y -= 14
    c.drawString(50, y, f"Students: {report_summary['total']}   Complete: {report_summary['complete']}   Missing marks: {report_summary['incomplete']}")
    y -= 25

    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Reg No")
    c.drawString(140, y, "Student")
    c.drawString(320, y, "Ind/100")
    c.drawString(390, y, "Acad/100")
    c.drawString(470, y, "Avg/100")
    y -= 14

    c.setFont("Helvetica", 9)

    for r in rows:
        if y < 60:
            c.showPage()
            y = height - 50

        ind100 = r.get("industry_100")
        ac100 = r.get("academic_100")
        avg100 = r.get("average_100")
        c.drawString(50, y, str(r.get("reg_no", ""))[:14])
        c.drawString(140, y, str(r.get("name", ""))[:28])
        c.drawString(330, y, "-" if ind100 is None else str(int(round(float(ind100), 0))))
        c.drawString(405, y, "-" if ac100 is None else str(int(round(float(ac100), 0))))
        c.drawString(485, y, "-" if avg100 is None else str(int(round(float(avg100), 0))))
        y -= 13

    c.showPage()
    c.save()
    buffer.seek(0)

    filename = f"results_report_{timezone.now().strftime('%Y%m%d_%H%M')}.pdf"
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@transaction.atomic
def supervisor_submit_results_report(request):
    if request.method != "POST":
        return HttpResponseForbidden("POST only.")
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = getattr(request.user, "staff_profile", None)
    if not staff:
        return HttpResponseForbidden("Staff profile not set.")

    latest_locked_report = _get_supervisor_working_report(request.user)
    if latest_locked_report and latest_locked_report.status not in ["draft", "needs_changes"]:
        messages.error(request, "This report is locked. The coordinator must request changes before it can be submitted again.")
        return redirect("supervisor_results_report")

    report = _get_supervisor_working_report(request.user, for_update=True)

    if report and report.status not in ["draft", "needs_changes"]:
        messages.error(request, "This report is locked. The coordinator must request changes before it can be submitted again.")
        return redirect("supervisor_results_report")

    if not report:
        rows = build_results_rows(request.user, staff)
        report = SupervisorResultsReport.objects.create(
            supervisor_user=request.user,
            status="draft",
            rows=rows
        )

    summary = _results_report_summary(report.rows or [])
    if summary["total"] == 0:
        messages.error(request, "You cannot submit an empty results report.")
        return redirect("supervisor_results_report")
    if summary["incomplete"] > 0:
        messages.error(request, "Complete all industry and academic marks before submitting the results report.")
        return redirect("supervisor_results_report")

    report.submit()
    notify_coordinators(
        title="Results report submitted",
        message=(
            f"{getattr(request.user, 'display_name', '') or request.user.get_username()} submitted "
            f"a results report with {summary['total']} student(s) for coordinator review."
        ),
        level="info",
        action_url=reverse("coordinator_results_reports"),
        action_text="Review Reports",
    )
    messages.success(request, "Results report submitted to the coordinator.")
    return redirect("supervisor_results_report")


# -------------------------------------------------------------------
# UNIVERSITY SUPERVISOR: SITE VISITS
# -------------------------------------------------------------------
@login_required
def supervisor_add_site_visit(request, placement_id):
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = _get_staff_profile(request.user)
    if not staff:
        return HttpResponseForbidden("Staff profile not set. Admin must create StaffProfile for this user.")

    placement = get_object_or_404(
        Placement.objects.select_related("company", "request__student__user", "university_supervisor"),
        pk=placement_id,
    )

    if placement.university_supervisor_id != staff.id:
        return HttpResponseForbidden("You are not assigned to this student.")

    form = SiteVisitScheduleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        visit = form.save(commit=False)
        visit.placement = placement
        visit.supervisor = staff
        visit.status = "scheduled"
        visit.save()

        messages.success(request, "Site visit scheduled. Student can now confirm it.")
        return redirect("supervisor_site_visits")

    return render(request, "tracking/site_visit_form.html", {
        "form": form,
        "placement": placement,
        "title": "Schedule Site Visit",
    })


@login_required
def supervisor_site_visits(request):
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = _get_staff_profile(request.user)
    if not staff:
        return HttpResponseForbidden("Staff profile not set.")

    visits = (
        SiteVisit.objects
        .filter(supervisor=staff)
        .select_related(
            "placement",
            "placement__company",
            "placement__request__student__user",
            "supervisor__user",
        )
        .order_by("-scheduled_at")
    )

    return render(request, "tracking/supervisor_site_visits.html", {"visits": visits})


@login_required
def submit_site_visit_report(request, visit_id):
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = _get_staff_profile(request.user)
    if not staff:
        return HttpResponseForbidden("Staff profile not set.")

    visit = get_object_or_404(
        SiteVisit.objects.select_related(
            "placement",
            "placement__company",
            "placement__request__student__user",
            "supervisor__user",
        ),
        id=visit_id,
        supervisor=staff,
    )

    report, _ = SiteVisitReport.objects.get_or_create(site_visit=visit)
    form = SiteVisitReportForm(request.POST or None, request.FILES or None, instance=report)

    if request.method == "POST":
        if visit.status not in ["confirmed", "scheduled"]:
            messages.error(request, "You can only submit/edit reports for scheduled/confirmed visits.")
            return redirect("supervisor_site_visits")

        if form.is_valid():
            form.save()
            if not visit.actual_at:
                visit.actual_at = timezone.now()
            visit.status = "completed"
            visit.save(update_fields=["status", "actual_at"])

            messages.success(request, "Site visit report submitted. Visit marked as completed.")
            return redirect("supervisor_site_visits")

    return render(request, "tracking/site_visit_report_form.html", {
        "visit": visit,
        "form": form,
        "report": report,
    })


# -------------------------------------------------------------------
# UNIVERSITY SUPERVISOR: STUDENT EVALUATIONS
# -------------------------------------------------------------------
@login_required
def supervisor_student_evaluations(request):
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = getattr(request.user, "staff_profile", None)
    if not staff:
        return HttpResponseForbidden("Staff profile not set.")

    evaluations = (
        StudentEvaluation.objects
        .filter(status="submitted", placement__university_supervisor=staff)
        .select_related(
            "placement",
            "placement__company",
            "placement__request__student",
            "placement__request__student__user",
            "student_user",
        )
        .order_by("placement__request__student__reg_no", "-submitted_at")
    )

    return render(request, "tracking/supervisor_student_evaluations.html", {
        "evaluations": evaluations,
    })


@login_required
def supervisor_student_evaluation_detail(request, evaluation_id):
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = getattr(request.user, "staff_profile", None)
    if not staff:
        return HttpResponseForbidden("Staff profile not set.")

    evaluation = get_object_or_404(
        StudentEvaluation,
        id=evaluation_id,
        status="submitted",
        placement__university_supervisor=staff,
    )

    return render(request, "tracking/supervisor_student_evaluation_detail.html", {
        "evaluation": evaluation,
        "placement": evaluation.placement,
    })


# -------------------------------------------------------------------
# UNIVERSITY SUPERVISOR: DASHBOARD
# -------------------------------------------------------------------
@login_required
def supervisor_dashboard(request):
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = getattr(request.user, "staff_profile", None)
    if not staff:
        return HttpResponseForbidden("Staff profile not set. Admin must create StaffProfile for this user.")

    now = timezone.now()

    latest_report = _get_latest_report(request.user)

    assigned_count = (
        Placement.objects
        .filter(university_supervisor=staff)
        .exclude(status__in=["completed", "terminated"])
        .count()
    )

    industry_submitted_count = IndustryEvaluation.objects.filter(
        placement__university_supervisor=staff,
        status="submitted"
    ).count()

    academic_submitted_count = AcademicEvaluation.objects.filter(
        placement__university_supervisor=staff,
        supervisor_user=request.user,
        status="submitted"
    ).count()

    ready_for_average_count = (
        Placement.objects
        .filter(university_supervisor=staff)
        .exclude(status__in=["completed", "terminated"])
        .filter(
            industry_evaluation__status="submitted",
            academic_evaluation__status="submitted",
            academic_evaluation__supervisor_user=request.user,
        )
        .distinct()
        .count()
    )

    site_visits_qs = (
        SiteVisit.objects
        .filter(placement__university_supervisor=staff)
        .select_related(
            "placement",
            "placement__company",
            "placement__request__student",
            "placement__request__student__user",
        )
        .order_by("scheduled_at")
    )

    site_visits_scheduled = site_visits_qs.filter(status="scheduled").count()
    site_visits_confirmed = site_visits_qs.filter(status="confirmed").count()
    site_visits_completed = site_visits_qs.filter(status="completed").count()

    site_visits_pending_count = (
        site_visits_qs
        .filter(status__in=["scheduled", "confirmed"], scheduled_at__gte=now)
        .count()
    )

    latest_site_visits = list(site_visits_qs.order_by("-scheduled_at")[:5])

    next_visit = (
        site_visits_qs
        .filter(status__in=["scheduled", "confirmed"], scheduled_at__gte=now)
        .order_by("scheduled_at")
        .first()
    )

    student_eval_qs = (
        StudentEvaluation.objects
        .filter(status="submitted", placement__university_supervisor=staff)
        .select_related(
            "placement",
            "placement__company",
            "placement__request__student",
            "placement__request__student__user",
            "student_user",
        )
        .order_by("-submitted_at")
    )
    student_eval_count = student_eval_qs.count()
    latest_student_evals = list(student_eval_qs[:5])

    dashboard_keys = [
        "supervisor:site_visits_pending",
        "supervisor:student_feedback",
        "supervisor:results_report_due",
    ]
    active_keys = set()

    def notify_hint(key, **kwargs):
        active_keys.add(key)
        ensure_dashboard_notification(request.user, key=key, **kwargs)

    if site_visits_pending_count:
        notify_hint(
            "supervisor:site_visits_pending",
            title="Site visits pending",
            message=f"You have {site_visits_pending_count} scheduled or confirmed site visit(s) awaiting action.",
            level="warning",
            action_url=reverse("supervisor_site_visits"),
            action_text="View Site Visits",
        )

    if student_eval_count:
        notify_hint(
            "supervisor:student_feedback",
            title="Student feedback submitted",
            message=f"{student_eval_count} student evaluation form(s) are available for review.",
            level="info",
            action_url=reverse("supervisor_student_evaluations"),
            action_text="Open Feedback",
        )

    if ready_for_average_count and (not latest_report or latest_report.status in ["draft", "needs_changes"]):
        notify_hint(
            "supervisor:results_report_due",
            title="Results report ready",
            message=f"{ready_for_average_count} assigned student(s) have complete marks. Refresh and submit your results report to the coordinator.",
            level="success",
            action_url=reverse("supervisor_results_report"),
            action_text="Open Results Report",
        )

    for key in dashboard_keys:
        if key not in active_keys:
            resolve_dashboard_notification(request.user, key)
    notification_context = get_notification_context(request.user)

    return render(request, "dashboards/supervisor_dashboard.html", {
        "latest_report": latest_report,
        "assigned_count": assigned_count,
        "industry_submitted_count": industry_submitted_count,
        "academic_submitted_count": academic_submitted_count,
        "ready_for_average_count": ready_for_average_count,

        "student_eval_count": student_eval_count,
        "latest_student_evals": latest_student_evals,

        "latest_site_visits": latest_site_visits,
        "site_visits_scheduled": site_visits_scheduled,
        "site_visits_confirmed": site_visits_confirmed,
        "site_visits_completed": site_visits_completed,
        "site_visits_pending_count": site_visits_pending_count,

        **notification_context,
    })

@login_required
def schedule_site_visit(request, placement_id):
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = getattr(request.user, "staff_profile", None)  # ✅ correct related_name
    if not staff:
        return HttpResponseForbidden("Staff profile not set.")

    placement = get_object_or_404(
        Placement.objects.select_related(
            "request",
            "request__student",
            "request__student__user",
            "company",
            "university_supervisor",
        ),
        pk=placement_id
    )

    # ✅ strict StaffProfile match
    if placement.university_supervisor_id != staff.id:
        return HttpResponseForbidden("You are not assigned to this student.")

    form = SiteVisitScheduleForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        visit = form.save(commit=False)
        visit.placement = placement
        visit.supervisor = staff
        visit.status = "scheduled"
        visit.save()

        messages.success(request, "Site visit scheduled. The student will see it for confirmation.")
        return redirect("supervisor_site_visits")

    return render(request, "tracking/site_visit_form.html", {
        "form": form,
        "placement": placement,
        "title": "Schedule Site Visit",
    })

