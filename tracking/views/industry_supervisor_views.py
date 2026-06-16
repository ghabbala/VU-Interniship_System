# tracking/views/industry_supervisor_views.py
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Prefetch, Case, When, Value, IntegerField
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from companies.models import CompanyContact
from placements.models import Placement
from tracking.forms import IndustryEvaluationForm
from tracking.models import WeeklyLog, WeeklyLogEntry, IndustryEvaluation, IndustrySupervisorResultsReport, Notification

from .common import (
    ensure_dashboard_notification,
    get_notification_context,
    is_industry_supervisor,
    resolve_dashboard_notification,
)


# -------------------------------------------------------------------
# INDUSTRY SUPERVISOR: LOG REVIEW
# -------------------------------------------------------------------
@login_required
def company_pending_logs(request):
    if not is_industry_supervisor(request.user):
        return HttpResponseForbidden("Industry Supervisors only.")

    if not hasattr(request.user, "industry_profile") or not request.user.industry_profile.company:
        return HttpResponseForbidden("Industry profile/company not set. Admin must link this user to a company.")

    company = request.user.industry_profile.company

    entry_qs = (
        WeeklyLogEntry.objects
        .annotate(
            day_order=Case(
                When(day="mon", then=Value(1)),
                When(day="tue", then=Value(2)),
                When(day="wed", then=Value(3)),
                When(day="thu", then=Value(4)),
                When(day="fri", then=Value(5)),
                default=Value(99),
                output_field=IntegerField(),
            )
        )
        .order_by("day_order")
    )

    logs = (
        WeeklyLog.objects
        .filter(placement__company=company, status="submitted")
        .select_related(
            "placement", "placement__company",
            "placement__request__student", "placement__request__student__user"
        )
        .prefetch_related("attachments", Prefetch("entries", queryset=entry_qs))
        .order_by("placement__request__student__reg_no", "-week_no")
    )

    return render(request, "tracking/company_pending_logs.html", {"company": company, "logs": logs})


@login_required
def company_action_log(request, log_id):
    if request.method != "POST":
        return HttpResponseForbidden("POST only.")

    if not is_industry_supervisor(request.user):
        return HttpResponseForbidden("Industry Supervisors only.")

    if not hasattr(request.user, "industry_profile") or not request.user.industry_profile.company:
        return HttpResponseForbidden("Industry profile/company not set for this user.")

    company = request.user.industry_profile.company
    log = get_object_or_404(WeeklyLog, id=log_id, placement__company=company)

    action = request.POST.get("action")

    if action == "approve":
        log.approve(request.user)
        return redirect("company_approved_logs")

    if action == "return":
        reason = request.POST.get("reason", "")
        log.return_for_edit(request.user, reason)
        return redirect("company_pending_logs")

    return HttpResponseForbidden("Invalid action.")


@login_required
def company_approved_logs(request):
    if not is_industry_supervisor(request.user):
        return HttpResponseForbidden("Industry Supervisors only.")

    if not hasattr(request.user, "industry_profile") or not request.user.industry_profile.company:
        return HttpResponseForbidden("Industry profile/company not set for this user.")

    company = request.user.industry_profile.company

    logs = (
        WeeklyLog.objects
        .filter(placement__company=company, status="approved_by_company")
        .select_related(
            "placement", "placement__company",
            "placement__request", "placement__request__student", "placement__request__student__user"
        )
        .prefetch_related("attachments", Prefetch("entries", queryset=WeeklyLogEntry.objects.order_by("day")))
        .order_by("placement__request__student__reg_no", "-week_no")
    )

    return render(request, "tracking/company_approved_logs.html", {"company": company, "logs": logs})


# -------------------------------------------------------------------
# INDUSTRY SUPERVISOR: EVALUATIONS
# -------------------------------------------------------------------
EVALUATION_WINDOW_DAYS = 234


def _get_industry_company(user):
    if hasattr(user, "industry_profile") and user.industry_profile and user.industry_profile.company:
        return user.industry_profile.company
    contact = CompanyContact.objects.filter(email__iexact=(user.email or "").strip()).select_related("company").first()
    return contact.company if contact else None


def _build_industry_report_rows(company, supervisor_user):
    placements = (
        Placement.objects
        .filter(company=company, status="active")
        .select_related(
            "company",
            "university_supervisor",
            "university_supervisor__user",
            "request",
            "request__student",
            "request__student__user",
        )
        .order_by("request__student__reg_no")
    )
    eval_map = {
        e.placement_id: e
        for e in IndustryEvaluation.objects.filter(
            placement__in=placements,
            company=company,
            status="submitted",
            supervisor_user=supervisor_user,
        )
    }

    rows = []
    for p in placements:
        ev = eval_map.get(p.id)
        uni_user = getattr(getattr(p, "university_supervisor", None), "user", None)
        rows.append({
            "placement_id": p.id,
            "reg_no": p.request.student.reg_no,
            "name": p.request.student.user.display_name,
            "company": p.company.name,
            "university_supervisor_id": uni_user.id if uni_user else None,
            "university_supervisor_name": (uni_user.display_name if uni_user else "") or (uni_user.get_username() if uni_user else "Unassigned"),
            "university_supervisor_email": getattr(uni_user, "email", "") if uni_user else "",
            "industry_total": ev.total_marks if ev else None,
            "industry_max": ev.max_marks if ev else 65,
            "industry_100": float(ev.score_out_of_100) if ev else None,
            "industry_10": float(ev.score_out_of_10) if ev else None,
            "evaluation_submitted_at": ev.submitted_at.isoformat() if ev and ev.submitted_at else "",
        })
    return rows


def _industry_report_summary(rows):
    rows = rows or []
    total = len(rows)
    complete = sum(1 for r in rows if r.get("industry_100") is not None)
    incomplete = max(total - complete, 0)
    assigned_university_supervisors = len({
        r.get("university_supervisor_id")
        for r in rows
        if r.get("university_supervisor_id")
    })
    return {
        "total": total,
        "complete": complete,
        "incomplete": incomplete,
        "assigned_university_supervisors": assigned_university_supervisors,
        "ready": total > 0 and incomplete == 0,
    }


def _get_industry_working_report(user, company, for_update=False):
    qs = IndustrySupervisorResultsReport.objects.filter(supervisor_user=user, company=company)
    if for_update:
        qs = qs.select_for_update()
    return qs.order_by("status", "-updated_at", "-created_at").first()

@login_required
def company_evaluate_student(request, placement_id):
    if not is_industry_supervisor(request.user):
        return HttpResponseForbidden("Industry Supervisors only.")

    if not hasattr(request.user, "industry_profile") or not request.user.industry_profile.company:
        return HttpResponseForbidden("Industry profile/company not set for this user.")

    company = request.user.industry_profile.company
    placement = get_object_or_404(Placement, id=placement_id, company=company)

    if placement.status != "active":
        return render(request, "tracking/evaluation_not_allowed.html", {
            "placement": placement,
            "lock_title": "Evaluation Not Available",
            "lock_message": "Industry supervisors can only assess students whose internship placement is active.",
            "lock_detail": f"This placement is currently marked as {placement.get_status_display()}.",
        }, status=403)

    today = timezone.localdate()
    if placement.end_date:
        days_to_end = (placement.end_date - today).days
        if days_to_end > EVALUATION_WINDOW_DAYS:
            return render(request, "tracking/evaluation_not_allowed.html", {
                "placement": placement,
                "lock_title": "Evaluation Not Available Yet",
                "lock_message": "You can only evaluate an intern near the end of the internship period.",
                "lock_detail": f"This evaluation becomes available only within the last {EVALUATION_WINDOW_DAYS} days of the internship.",
                "days_to_end": days_to_end,
                "window_days": EVALUATION_WINDOW_DAYS,
            })

    evaluation, _ = IndustryEvaluation.objects.get_or_create(
        placement=placement,
        defaults={
            "company": company,
            "supervisor_user": request.user,
            "supervisor_name": getattr(request.user, "display_name", "") or request.user.get_username(),
            "status": "draft",
        }
    )

    if evaluation.status == "submitted":
        return render(request, "tracking/evaluation_submitted_view.html", {
            "placement": placement,
            "company": company,
            "evaluation": evaluation,
        })

    if request.method == "POST":
        form = IndustryEvaluationForm(request.POST, instance=evaluation)
        if form.is_valid():
            evaluation = form.save(commit=False)
            evaluation.company = company
            evaluation.supervisor_user = request.user

            action = request.POST.get("action", "save")
            if action == "submit":
                evaluation.submit(user=request.user)
                return redirect("company_approved_evaluations")

            evaluation.status = "draft"
            evaluation.save()
            return redirect("company_evaluate_student", placement_id=placement.id)
    else:
        form = IndustryEvaluationForm(instance=evaluation)

    criteria = [
        (form["basic_work_expectations"], "Basic work expectations", form["basic_work_expectations_comment"]),
        (form["knowledge_and_learning"], "Knowledge and ability to learn", form["knowledge_and_learning_comment"]),
        (form["ethical_awareness"], "Ethical awareness and conduct", form["ethical_awareness_comment"]),
        (form["interpersonal_relations"], "Interpersonal relations", form["interpersonal_relations_comment"]),
        (form["communication_skills"], "Communication skills", form["communication_skills_comment"]),
        (form["attendance"], "Attendance", form["attendance_comment"]),
        (form["punctuality"], "Punctuality", form["punctuality_comment"]),
        (form["flexibility"], "Flexibility", form["flexibility_comment"]),
        (form["dependability"], "Dependability", form["dependability_comment"]),
        (form["culture_fit"], "Culture fit", form["culture_fit_comment"]),
        (form["dress_code"], "Dress code", form["dress_code_comment"]),
        (form["behaviour"], "Behaviour", form["behaviour_comment"]),
        (form["work_productivity"], "Work productivity", form["work_productivity_comment"]),
    ]

    return render(request, "tracking/company_evaluation_form.html", {
        "placement": placement,
        "company": company,
        "form": form,
        "evaluation": evaluation,
        "criteria": criteria,
        "today": today,
    })


@login_required
def company_approved_evaluations(request):
    if not is_industry_supervisor(request.user):
        return HttpResponseForbidden("Industry Supervisors only.")

    if not hasattr(request.user, "industry_profile") or not request.user.industry_profile.company:
        return HttpResponseForbidden("Industry profile/company not set for this user.")

    company = request.user.industry_profile.company

    evaluations = (
        IndustryEvaluation.objects
        .filter(company=company, status="submitted")
        .select_related(
            "placement",
            "placement__company",
            "placement__request",
            "placement__request__student",
            "placement__request__student__user",
        )
        .order_by("placement__request__student__reg_no", "-submitted_at")
    )

    return render(request, "tracking/company_approved_evaluations.html", {
        "company": company,
        "evaluations": evaluations,
    })


@login_required
def industry_results_report(request):
    if not is_industry_supervisor(request.user):
        return HttpResponseForbidden("Industry Supervisors only.")

    company = _get_industry_company(request.user)
    if not company:
        return HttpResponseForbidden("Industry profile/company not set for this user.")

    report = _get_industry_working_report(request.user, company)
    rows = report.rows if report else _build_industry_report_rows(company, request.user)
    summary = _industry_report_summary(rows)

    return render(request, "tracking/industry_results_report.html", {
        "company": company,
        "report": report,
        "rows": rows,
        "summary": summary,
        "can_submit_report": summary["ready"] and (not report or report.status == "draft"),
    })


@login_required
@transaction.atomic
def industry_refresh_results_report(request):
    if request.method != "POST":
        return HttpResponseForbidden("POST only.")
    if not is_industry_supervisor(request.user):
        return HttpResponseForbidden("Industry Supervisors only.")

    company = _get_industry_company(request.user)
    if not company:
        return HttpResponseForbidden("Industry profile/company not set for this user.")

    report = _get_industry_working_report(request.user, company, for_update=True)
    if report and report.status != "draft":
        messages.error(request, "This industry report has already been submitted and is locked.")
        return redirect("industry_results_report")

    rows = _build_industry_report_rows(company, request.user)
    if not report:
        IndustrySupervisorResultsReport.objects.create(
            supervisor_user=request.user,
            company=company,
            rows=rows,
            status="draft",
        )
    else:
        report.rows = rows
        report.save(update_fields=["rows", "updated_at"])

    messages.success(request, "Industry report refreshed with the latest submitted evaluations.")
    return redirect("industry_results_report")


@login_required
def industry_results_report_pdf(request):
    if not is_industry_supervisor(request.user):
        return HttpResponseForbidden("Industry Supervisors only.")

    company = _get_industry_company(request.user)
    if not company:
        return HttpResponseForbidden("Industry profile/company not set for this user.")

    report = _get_industry_working_report(request.user, company)
    rows = report.rows if report else _build_industry_report_rows(company, request.user)
    summary = _industry_report_summary(rows)

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 50

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "Industry Supervisor Performance Report")
    y -= 18
    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Company: {company.name}")
    y -= 14
    c.drawString(50, y, f"Supervisor: {getattr(request.user, 'display_name', '') or request.user.get_username()}")
    y -= 14
    if report:
        c.drawString(50, y, f"Report Ref: #{report.id}   Status: {report.status.upper()}")
        y -= 14
    c.drawString(50, y, f"Generated: {timezone.now().strftime('%Y-%m-%d %H:%M')}")
    y -= 14
    c.drawString(50, y, f"Students: {summary['total']}   Evaluated: {summary['complete']}   Missing: {summary['incomplete']}")
    y -= 24

    c.setFont("Helvetica-Bold", 9)
    c.drawString(45, y, "Reg No")
    c.drawString(120, y, "Student")
    c.drawString(265, y, "University Supervisor")
    c.drawString(420, y, "Score /100")
    c.drawString(500, y, "Score /10")
    y -= 14
    c.setFont("Helvetica", 8.5)

    for r in rows:
        if y < 60:
            c.showPage()
            y = height - 50
        score100 = r.get("industry_100")
        score10 = r.get("industry_10")
        c.drawString(45, y, str(r.get("reg_no", ""))[:12])
        c.drawString(120, y, str(r.get("name", ""))[:24])
        c.drawString(265, y, str(r.get("university_supervisor_name", ""))[:24])
        c.drawString(430, y, "-" if score100 is None else str(int(round(float(score100), 0))))
        c.drawString(510, y, "-" if score10 is None else str(round(float(score10), 1)))
        y -= 13

    c.showPage()
    c.save()
    buffer.seek(0)

    filename = f"industry_results_report_{timezone.now().strftime('%Y%m%d_%H%M')}.pdf"
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@transaction.atomic
def industry_submit_results_report(request):
    if request.method != "POST":
        return HttpResponseForbidden("POST only.")
    if not is_industry_supervisor(request.user):
        return HttpResponseForbidden("Industry Supervisors only.")

    company = _get_industry_company(request.user)
    if not company:
        return HttpResponseForbidden("Industry profile/company not set for this user.")

    report = _get_industry_working_report(request.user, company, for_update=True)
    if report and report.status != "draft":
        messages.error(request, "This industry report has already been submitted.")
        return redirect("industry_results_report")

    if not report:
        report = IndustrySupervisorResultsReport.objects.create(
            supervisor_user=request.user,
            company=company,
            rows=_build_industry_report_rows(company, request.user),
            status="draft",
        )

    summary = _industry_report_summary(report.rows or [])
    if summary["total"] == 0:
        messages.error(request, "You cannot submit an empty industry report.")
        return redirect("industry_results_report")
    if summary["incomplete"] > 0:
        messages.error(request, "Complete all student evaluations before submitting the industry report.")
        return redirect("industry_results_report")

    report.submit()

    supervisor_ids = {
        row.get("university_supervisor_id")
        for row in report.rows or []
        if row.get("university_supervisor_id")
    }
    for supervisor_id in supervisor_ids:
        Notification.objects.create(
            user_id=supervisor_id,
            title="Industry results report submitted",
            message=(
                f"{getattr(request.user, 'display_name', '') or request.user.get_username()} submitted "
                f"an industry results report for {company.name} with {summary['total']} student(s)."
            ),
            level="info",
            action_url=reverse("supervisor_industry_reports"),
            action_text="Open Industry Reports",
            is_read=False,
        )

    messages.success(request, "Industry report submitted to the assigned University Supervisor(s).")
    return redirect("industry_results_report")


# -------------------------------------------------------------------
# INDUSTRY DASHBOARD
# -------------------------------------------------------------------
@login_required
def industry_dashboard(request):
    if not is_industry_supervisor(request.user):
        return HttpResponseForbidden("Industry Supervisors only.")

    user_email = (request.user.email or "").strip()
    contact = CompanyContact.objects.filter(email__iexact=user_email).select_related("company").first()

    company = None
    if hasattr(request.user, "industry_profile") and request.user.industry_profile and request.user.industry_profile.company:
        company = request.user.industry_profile.company
    elif contact:
        company = contact.company

    if not company:
        empty_stats = {
            "pending_logs": 0,
            "approved_logs": 0,
            "returned_logs": 0,
            "assigned_students": 0,
            "submitted_evaluations": 0,
            "unread_notifications": 0,
        }
        ensure_dashboard_notification(
            request.user,
            key="industry:profile_not_linked",
            title="Profile not linked",
            message="No company linked to your account. Ask the coordinator to link your Industry Profile or Company Contact.",
            level="warning",
        )
        notification_context = get_notification_context(request.user)
        return render(request, "dashboards/industry_dashboard.html", {
            "pending_logs": 0,
            "approved_logs": 0,
            "returned_logs": 0,
            "assigned_students": 0,
            "submitted_evaluations": 0,
            **notification_context,
            "recent_logs": [],
            "contact": contact,
            "stats": empty_stats,
        })

    resolve_dashboard_notification(request.user, "industry:profile_not_linked")

    log_qs = WeeklyLog.objects.filter(placement__company=company).select_related(
        "placement", "placement__company", "placement__request__student__user"
    )

    pending_logs = log_qs.filter(status="submitted").count()
    approved_logs = log_qs.filter(status="approved_by_company").count()
    returned_logs = log_qs.filter(status="returned_for_edit").count()

    assigned_students = (
        Placement.objects.filter(company=company)
        .values("request__student").distinct().count()
    )

    submitted_evaluations = IndustryEvaluation.objects.filter(company=company, status="submitted").count()

    dashboard_keys = ["industry:pending_logs", "industry:returned_logs", "industry:pending_ack"]
    active_keys = set()

    def notify_hint(key, **kwargs):
        active_keys.add(key)
        ensure_dashboard_notification(request.user, key=key, **kwargs)

    if pending_logs:
        notify_hint(
            "industry:pending_logs",
            title="Pending logs need review",
            message=f"You have {pending_logs} submitted weekly log(s) waiting for approval.",
            level="warning",
            action_url=reverse("company_pending_logs"),
            action_text="Review Logs",
        )
    if returned_logs:
        notify_hint(
            "industry:returned_logs",
            title="Returned logs",
            message=f"{returned_logs} log(s) were returned for edit. Students may resubmit anytime.",
            level="info",
            action_url=reverse("company_pending_logs"),
            action_text="Track Logs",
        )

    pending_ack = Placement.objects.filter(company=company, status="pending_student_ack").count()
    if pending_ack:
        notify_hint(
            "industry:pending_ack",
            title="Placements pending acknowledgement",
            message=f"{pending_ack} placement(s) are pending student acknowledgement.",
            level="info",
            action_url=reverse("supervisor_students"),
            action_text="View Students",
        )

    for key in dashboard_keys:
        if key not in active_keys:
            resolve_dashboard_notification(request.user, key)
    notification_context = get_notification_context(request.user)

    recent_qs = log_qs.order_by("-company_action_at", "-submitted_at", "-created_at")[:8]
    recent_logs = []
    for log in recent_qs:
        stu_user = getattr(log.placement.request.student, "user", None)
        student_name = (stu_user.get_full_name() if stu_user else "") or log.placement.request.student.reg_no

        summary = (log.activities or "").strip()
        if len(summary) > 90:
            summary = summary[:90] + "…"

        recent_logs.append({
            "student_name": student_name,
            "week_no": log.week_no,
            "summary": summary or "Weekly log updated.",
            "status": log.status,
            "updated_at": log.company_action_at or log.submitted_at or log.created_at,
        })

    stats = {
        "pending_logs": pending_logs,
        "approved_logs": approved_logs,
        "returned_logs": returned_logs,
        "submitted_evaluations": submitted_evaluations,
        "assigned_students": assigned_students,
        "unread_notifications": notification_context["unread_notifications"],
    }

    return render(request, "dashboards/industry_dashboard.html", {
        "pending_logs": pending_logs,
        "approved_logs": approved_logs,
        "returned_logs": returned_logs,
        "assigned_students": assigned_students,
        "submitted_evaluations": submitted_evaluations,
        "unread_notifications": notification_context["unread_notifications"],

        "notifications": notification_context["notifications"],
        "recent_logs": recent_logs,
        "contact": contact,
        "stats": stats,
    })
