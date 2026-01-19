# tracking/views.py
import datetime
from io import BytesIO

from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.db.models import Q, Case, When, IntegerField, Prefetch
from django.http import HttpResponseForbidden, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from .models import StudentEvaluation
from .forms import StudentEvaluationForm


from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

from placements.models import Placement
from .models import (
    WeeklyLog,
    WeeklyLogEntry,
    SiteVisit,
    IndustryEvaluation,
    AcademicEvaluation,
    SupervisorResultsReport,
)
from .forms import (
    WeeklyLogForm,
    WeeklyLogEntryFormSet,
    SiteVisitForm,
    IndustryEvaluationForm,
    AcademicEvaluationForm,
    StudentEvaluation,
)

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.utils import timezone

from placements.models import InternshipRequest, Placement
from tracking.models import (
    WeeklyLog,
    IndustryEvaluation,
    AcademicEvaluation,
    StudentEvaluation,
    SupervisorResultsReport,
)

from django.db.models import Count, Q
from accounts.models import StaffProfile

# -------------------------------------------------------------------
# Helpers / role checks (SINGLE SOURCE OF TRUTH)
# -------------------------------------------------------------------
def is_university_supervisor(user):
    return user.is_superuser or user.groups.filter(name__in=["UniversitySupervisor", "Admin"]).exists()


def is_industry_supervisor(user):
    return user.is_superuser or user.groups.filter(name__in=["IndustrySupervisor", "Admin"]).exists()


def is_coordinator(user):
    return user.is_superuser or user.groups.filter(name__in=["Coordinator", "Admin"]).exists()


def _get_student_active_placement(user):
    if not hasattr(user, "student_profile"):
        return None
    student = user.student_profile
    return (
        Placement.objects.filter(request__student=student, status="active")
        .select_related("company", "request", "request__student", "request__student__user")
        .order_by("-created_at")
        .first()
    )


def _get_student_latest_placement(user):
    if not hasattr(user, "student_profile"):
        return None
    student = user.student_profile
    return (
        Placement.objects
        .filter(request__student=student)
        .select_related("company", "request", "request__student", "request__student__user", "university_supervisor")
        .order_by("-created_at")
        .first()
    )


def _get_latest_report(user):
    return (
        SupervisorResultsReport.objects
        .filter(supervisor_user=user)
        .order_by("-submitted_at", "-created_at")
        .first()
    )


DAYS = [("mon", "Monday"), ("tue", "Tuesday"), ("wed", "Wednesday"), ("thu", "Thursday"), ("fri", "Friday")]

DAY_ORDER = Case(
    When(day="mon", then=0),
    When(day="tue", then=1),
    When(day="wed", then=2),
    When(day="thu", then=3),
    When(day="fri", then=4),
    output_field=IntegerField(),
)

# -------------------------------------------------------------------
# STUDENT: LOGS
# -------------------------------------------------------------------
@login_required
def student_logs(request):
    placement = _get_student_active_placement(request.user)
    if not placement:
        return render(request, "tracking/no_active_placement.html")

    logs = WeeklyLog.objects.filter(placement=placement).order_by("-week_no")
    return render(request, "tracking/student_logs.html", {"placement": placement, "logs": logs})


@login_required
def student_log_new(request):
    placement = _get_student_active_placement(request.user)
    if not placement:
        return render(request, "tracking/no_active_placement.html")

    last = WeeklyLog.objects.filter(placement=placement).order_by("-week_no").first()
    next_week = (last.week_no + 1) if last else 1

    today = timezone.localdate()
    end = today + datetime.timedelta(days=4)

    log = WeeklyLog.objects.create(
        placement=placement,
        week_no=next_week,
        from_date=today,
        to_date=end,
        status="draft",
        activities="",  # keep if your model still has this legacy field
    )

    WeeklyLogEntry.objects.bulk_create([WeeklyLogEntry(weekly_log=log, day=d) for d, _ in DAYS])
    return redirect("student_log_edit", log_id=log.id)


@login_required
def student_log_edit(request, log_id):
    placement = _get_student_active_placement(request.user)
    if not placement:
        return render(request, "tracking/no_active_placement.html")

    log = get_object_or_404(WeeklyLog, id=log_id, placement=placement)

    # block editing once approved by company
    if log.status == "approved_by_company":
        return HttpResponseForbidden("This log is already approved.")

    # ensure Mon–Fri exist
    existing = set(log.entries.values_list("day", flat=True))
    missing = [WeeklyLogEntry(weekly_log=log, day=d) for d, _ in DAYS if d not in existing]
    if missing:
        WeeklyLogEntry.objects.bulk_create(missing)

    entries_qs = log.entries.all().order_by(DAY_ORDER)

    if request.method == "POST":
        form = WeeklyLogForm(request.POST, request.FILES, instance=log)
        formset = WeeklyLogEntryFormSet(request.POST, instance=log, queryset=entries_qs)

        if form.is_valid() and formset.is_valid():
            log = form.save(commit=False)

            # optional: rebuild "activities" legacy field from table
            lines = []
            for entry in entries_qs:
                wa = (entry.work_assignment or "").strip()
                st = (entry.activities_steps or "").strip()
                if wa or st:
                    lines.append(f"{entry.get_day_display()}: {wa} | {st}")
            log.activities = "\n".join(lines)

            action = request.POST.get("action", "save")
            if action == "submit":
                log.submit()  # should set status="submitted"
            else:
                if log.status != "returned_for_edit":
                    log.status = "draft"
                log.save()

            formset.save()
            return redirect("student_logs")
    else:
        form = WeeklyLogForm(instance=log)
        formset = WeeklyLogEntryFormSet(instance=log, queryset=entries_qs)

    return render(request, "tracking/log_form.html", {
        "log": log,
        "placement": placement,
        "form": form,
        "formset": formset,
    })


@login_required
def student_log_delete(request, log_id):
    if request.method != "POST":
        return HttpResponseForbidden("POST only.")

    placement = _get_student_active_placement(request.user)
    if not placement:
        return HttpResponseForbidden("No active placement.")

    log = get_object_or_404(WeeklyLog, id=log_id, placement=placement)

    if log.status != "draft":
        return HttpResponseForbidden("Only draft logs can be deleted.")

    attachment_name = log.attachment.name if getattr(log, "attachment", None) else None
    log.delete()

    if attachment_name and default_storage.exists(attachment_name):
        default_storage.delete(attachment_name)

    return redirect("student_logs")


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

    logs = (
        WeeklyLog.objects
        .filter(placement__company=company, status="submitted")
        .select_related(
            "placement", "placement__company",
            "placement__request__student", "placement__request__student__user"
        )
        .prefetch_related(Prefetch("entries", queryset=WeeklyLogEntry.objects.order_by("day")))
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
        .prefetch_related(Prefetch("entries", queryset=WeeklyLogEntry.objects.order_by("day")))
        .order_by("placement__request__student__reg_no", "-week_no")
    )

    return render(request, "tracking/company_approved_logs.html", {"company": company, "logs": logs})


# -------------------------------------------------------------------
# SUPERVISORS: ASSIGNED STUDENTS (UNIVERSITY + INDUSTRY)
# Adds: industry score, academic score, and average when both submitted
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

        # Industry submitted evals for these placements
        ind_map = {
            e.placement_id: e
            for e in IndustryEvaluation.objects.filter(placement__in=placements, status="submitted")
        }

        # Academic evals by THIS supervisor for these placements
        ac_map = {
            e.placement_id: e
            for e in AcademicEvaluation.objects.filter(placement__in=placements, supervisor_user=u)
        }

        for p in placements:
            ind = ind_map.get(p.id)
            ac = ac_map.get(p.id)

            # Industry
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

            # Academic
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

            # Average (only when BOTH submitted)
            if p.eval_status == "submitted" and p.ac_eval_status == "submitted":
                avg100 = (float(p.eval_score100) + float(p.ac_eval_score100)) / 2.0
                p.avg_score100 = avg100
                p.avg_score10 = avg100 / 10.0
            else:
                p.avg_score100 = None
                p.avg_score10 = None

        return render(request, "tracking/supervisor_students.html", {
            "placements": placements,
            "view_mode": "university",
        })

    # -------------------------
    # ✅ INDUSTRY SUPERVISOR
    # -------------------------
    if is_industry_supervisor(u):
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
            if not ev:
                p.eval_status = None
                p.eval_total = None
                p.eval_max = 65
                p.eval_score10 = None
                p.eval_score100 = None
            else:
                p.eval_status = ev.status
                p.eval_total = ev.total_marks
                p.eval_max = ev.max_marks
                p.eval_score10 = ev.score_out_of_10
                p.eval_score100 = ev.score_out_of_100

        return render(request, "tracking/supervisor_students.html", {
            "placements": placements,
            "company": company,
            "view_mode": "industry",
        })

    return HttpResponseForbidden("Supervisors only.")


# -------------------------------------------------------------------
# UNIVERSITY SUPERVISOR: SITE VISITS
# -------------------------------------------------------------------
@login_required
def supervisor_add_site_visit(request, placement_id):
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University supervisors only.")

    staff = getattr(request.user, "staff_profile", None)
    if not staff:
        return HttpResponseForbidden("Staff profile not set.")

    placement = get_object_or_404(Placement, id=placement_id, university_supervisor=staff)

    if request.method == "POST":
        form = SiteVisitForm(request.POST, request.FILES)
        if form.is_valid():
            sv = form.save(commit=False)
            sv.placement = placement
            sv.supervisor = staff
            sv.save()
            return redirect("supervisor_students")
    else:
        form = SiteVisitForm()

    return render(request, "tracking/site_visit_form.html", {"form": form, "placement": placement})


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
        .prefetch_related(Prefetch("entries", queryset=WeeklyLogEntry.objects.order_by("day")))
        .order_by("placement__request__student__reg_no", "-week_no")
    )

    return render(request, "tracking/supervisor_approved_logs.html", {"logs": logs})


# -------------------------------------------------------------------
# COORDINATOR: MISSING LOGS
# -------------------------------------------------------------------
def week_bounds(today):
    start = today - datetime.timedelta(days=today.weekday())
    end = start + datetime.timedelta(days=6)
    return start, end


@login_required
def coordinator_missing_logs(request):
    if not is_coordinator(request.user):
        return HttpResponseForbidden("Coordinators only.")

    today = timezone.localdate()
    wk_start, wk_end = week_bounds(today)

    active_placements = (
        Placement.objects
        .exclude(status__in=["completed", "terminated"])
        .select_related("company", "request", "request__student", "request__student__user")
    )

    missing = []
    for p in active_placements:
        has_log = (
            WeeklyLog.objects
            .filter(placement=p, status__in=["submitted", "approved_by_company"])
            .filter(Q(from_date__lte=wk_end) & Q(to_date__gte=wk_start))
            .exists()
        )
        if not has_log:
            missing.append(p)

    return render(request, "tracking/coordinator_missing_logs.html", {
        "wk_start": wk_start,
        "wk_end": wk_end,
        "missing": missing,
        "count_missing": len(missing),
        "count_active": active_placements.count(),
    })


# -------------------------------------------------------------------
# INDUSTRY SUPERVISOR: EVALUATIONS
# -------------------------------------------------------------------
EVALUATION_WINDOW_DAYS = 234  # adjust as needed


@login_required
def company_evaluate_student(request, placement_id):
    if not is_industry_supervisor(request.user):
        return HttpResponseForbidden("Industry Supervisors only.")

    if not hasattr(request.user, "industry_profile") or not request.user.industry_profile.company:
        return HttpResponseForbidden("Industry profile/company not set for this user.")

    company = request.user.industry_profile.company
    placement = get_object_or_404(Placement, id=placement_id, company=company)

    today = timezone.localdate()
    if placement.end_date:
        days_to_end = (placement.end_date - today).days
        if days_to_end > EVALUATION_WINDOW_DAYS:
            return render(request, "tracking/evaluation_not_allowed.html", {
                "placement": placement,
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

    # If already submitted -> show read-only (THIS student's evaluation)
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
                evaluation.submit(user=request.user)  # your model method
                return redirect("company_approved_evaluations")

            evaluation.status = "draft"
            evaluation.save()
            return redirect("company_evaluate_student", placement_id=placement.id)
    else:
        form = IndustryEvaluationForm(instance=evaluation)

    return render(request, "tracking/company_evaluation_form.html", {
        "placement": placement,
        "company": company,
        "form": form,
        "evaluation": evaluation,
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


# -------------------------------------------------------------------
# UNIVERSITY SUPERVISOR: ACADEMIC EVALUATION
# -------------------------------------------------------------------
ACADEMIC_EVAL_WINDOW_DAYS = 232  # adjust like you did for industry


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
# UNIVERSITY SUPERVISOR: RESULTS REPORT (avg = industry + academic)
# -------------------------------------------------------------------
@login_required
def supervisor_results_report(request):
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = getattr(request.user, "staff_profile", None)
    if not staff:
        return HttpResponseForbidden("Staff profile not set.")

    placements = (
        Placement.objects
        .filter(university_supervisor=staff)
        .exclude(status__in=["completed", "terminated"])
        .select_related("company", "request", "request__student", "request__student__user")
        .order_by("request__student__reg_no")
    )

    ind_map = {
        e.placement_id: e
        for e in IndustryEvaluation.objects.filter(placement__in=placements, status="submitted")
    }
    ac_map = {
        e.placement_id: e
        for e in AcademicEvaluation.objects.filter(placement__in=placements, status="submitted", supervisor_user=request.user)
    }

    rows = []
    for p in placements:
        ind = ind_map.get(p.id)
        ac = ac_map.get(p.id)

        ind100 = float(ind.score_out_of_100) if ind else None
        ac100 = float(ac.score_out_of_100) if ac else None
        avg100 = (ind100 + ac100) / 2.0 if (ind100 is not None and ac100 is not None) else None

        rows.append({
            "placement_id": p.id,
            "reg_no": p.request.student.reg_no,
            "name": p.request.student.user.display_name,
            "company": p.company.name,
            "industry_100": ind100,
            "academic_100": ac100,
            "average_100": avg100,
        })

    return render(request, "tracking/supervisor_results_report.html", {
        "rows": rows,
        "count": len(rows),
    })


@login_required
def supervisor_results_report_pdf(request):
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = getattr(request.user, "staff_profile", None)
    if not staff:
        return HttpResponseForbidden("Staff profile not set.")

    placements = (
        Placement.objects
        .filter(university_supervisor=staff)
        .exclude(status__in=["completed", "terminated"])
        .select_related("company", "request", "request__student", "request__student__user")
        .order_by("request__student__reg_no")
    )

    ind_map = {
        e.placement_id: e
        for e in IndustryEvaluation.objects.filter(placement__in=placements, status="submitted")
    }
    ac_map = {
        e.placement_id: e
        for e in AcademicEvaluation.objects.filter(placement__in=placements, status="submitted", supervisor_user=request.user)
    }

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 50
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "Internship Results Report (University Supervisor)")
    y -= 18

    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Generated: {timezone.now().strftime('%Y-%m-%d %H:%M')}")
    y -= 25

    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Reg No")
    c.drawString(140, y, "Student")
    c.drawString(320, y, "Ind/100")
    c.drawString(390, y, "Acad/100")
    c.drawString(470, y, "Avg/100")
    y -= 14

    c.setFont("Helvetica", 9)

    for p in placements:
        ind = ind_map.get(p.id)
        ac = ac_map.get(p.id)

        ind100 = round(float(ind.score_out_of_100), 0) if ind else None
        ac100 = round(float(ac.score_out_of_100), 0) if ac else None
        avg100 = round((ind100 + ac100) / 2.0, 0) if (ind100 is not None and ac100 is not None) else None

        if y < 60:
            c.showPage()
            y = height - 50

        c.drawString(50, y, str(p.request.student.reg_no))
        c.drawString(140, y, (p.request.student.user.display_name or "")[:28])
        c.drawString(330, y, "-" if ind100 is None else str(int(ind100)))
        c.drawString(405, y, "-" if ac100 is None else str(int(ac100)))
        c.drawString(485, y, "-" if avg100 is None else str(int(avg100)))
        y -= 13

    c.showPage()
    c.save()
    buffer.seek(0)

    filename = f"results_report_{timezone.now().strftime('%Y%m%d_%H%M')}.pdf"
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def supervisor_submit_results_report(request):
    if request.method != "POST":
        return HttpResponseForbidden("POST only.")

    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = getattr(request.user, "staff_profile", None)
    if not staff:
        return HttpResponseForbidden("Staff profile not set.")

    placements = (
        Placement.objects
        .filter(university_supervisor=staff)
        .exclude(status__in=["completed", "terminated"])
        .select_related("company", "request", "request__student", "request__student__user")
        .order_by("request__student__reg_no")
    )

    ind_map = {
        e.placement_id: e
        for e in IndustryEvaluation.objects.filter(placement__in=placements, status="submitted")
    }
    ac_map = {
        e.placement_id: e
        for e in AcademicEvaluation.objects.filter(
            placement__in=placements,
            status="submitted",
            supervisor_user=request.user
        )
    }

    rows = []
    for p in placements:
        ind = ind_map.get(p.id)
        ac = ac_map.get(p.id)

        ind100 = float(ind.score_out_of_100) if ind else None
        ac100 = float(ac.score_out_of_100) if ac else None
        avg100 = (ind100 + ac100) / 2.0 if (ind100 is not None and ac100 is not None) else None

        rows.append({
            "placement_id": p.id,
            "reg_no": p.request.student.reg_no,
            "name": p.request.student.user.display_name,
            "company": p.company.name,
            "industry_100": ind100,
            "academic_100": ac100,
            "average_100": avg100,
        })

    # ✅ Update latest draft report if exists, else create new
    report = (
        SupervisorResultsReport.objects
        .filter(supervisor_user=request.user)
        .exclude(status="submitted")  # only drafts/others
        .order_by("-created_at")
        .first()
    )

    if report:
        report.rows = rows
        report.submit()   # sets status=submitted + submitted_at
    else:
        report = SupervisorResultsReport.objects.create(
            supervisor_user=request.user,
            rows=rows,
            status="draft",
        )
        report.submit()

    return redirect("supervisor_results_report")

def _get_latest_report(user):
    return (
        SupervisorResultsReport.objects
        .filter(supervisor_user=user)
        .order_by("-submitted_at", "-created_at")
        .first()
    )


@login_required
def supervisor_dashboard(request):
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = getattr(request.user, "staff_profile", None)
    if not staff:
        return HttpResponseForbidden("Staff profile not set. Admin must create StaffProfile for this user.")

    latest_report = _get_latest_report(request.user)

    # Optional quick stats (nice for dashboard badges)
    assigned_count = Placement.objects.filter(
        university_supervisor=staff
    ).exclude(status__in=["completed", "terminated"]).count()

    industry_submitted_count = IndustryEvaluation.objects.filter(
        placement__university_supervisor=staff,
        status="submitted"
    ).count()

    academic_submitted_count = AcademicEvaluation.objects.filter(
        placement__university_supervisor=staff,
        supervisor_user=request.user,
        status="submitted"
    ).count()

    # students where BOTH evals are submitted (ready for average)
    ready_for_average_count = Placement.objects.filter(
        university_supervisor=staff
    ).exclude(status__in=["completed", "terminated"]).filter(
        industryevaluation__status="submitted",
        academicevaluation__status="submitted",
        academicevaluation__supervisor_user=request.user,
    ).distinct().count()

    # ✅ NEW: submitted Student Evaluation Forms (from students)
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

    return render(request, "tracking/supervisor_dashboard.html", {
        "latest_report": latest_report,
        "assigned_count": assigned_count,
        "industry_submitted_count": industry_submitted_count,
        "academic_submitted_count": academic_submitted_count,
        "ready_for_average_count": ready_for_average_count,

        # ✅ pass to template
        "student_eval_count": student_eval_count,
        "latest_student_evals": latest_student_evals,
    })


"""""
@login_required
def coordinator_results_report(request):
    if not is_coordinator(request.user):
        return HttpResponseForbidden("Coordinators only.")

    reports = (
        SupervisorResultsReport.objects
        .filter(status="submitted")
        .select_related("supervisor_user")
        .order_by("-submitted_at", "-created_at")
    )

    return render(request, "tracking/coordinator_results_reports.html", {
        "reports": reports
    })
"""



@login_required
def coordinator_results_reports(request):
    if not is_coordinator(request.user):
        return HttpResponseForbidden("Coordinators Only.")

    reports = (
        SupervisorResultsReport.objects
        .filter(status__in=["submitted", "received"])
        .select_related("supervisor_user")
        .order_by("-submitted_at", "-created_at")
    )

    pending_count = reports.filter(status="submitted").count()
    received_count = reports.filter(status="received").count()
    latest_report = reports.first()

    return render(request, "tracking/coordinator_results_reports.html", {
        "reports": reports,
        "pending_count": pending_count,
        "received_count": received_count,
        "latest_report": latest_report,
    })

@login_required
def coordinator_results_report_detail(request, report_id):
    if not is_coordinator(request.user):
        return HttpResponseForbidden("Coordinators only.")

    report = get_object_or_404(
        SupervisorResultsReport,
        id=report_id,
        status__in=["submitted", "received"]
    )

    return render(request, "tracking/coordinator_results_report_detail.html", {
        "report": report,
        "rows": report.rows or [],
    })


@login_required
def coordinator_results_report_pdf(request, report_id):
    if not is_coordinator(request.user):
        return HttpResponseForbidden("Coordinators only.")

    report = get_object_or_404(
        SupervisorResultsReport,
        id=report_id,
        status__in=["submitted", "received"]
    )

    rows = report.rows or []

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 50
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "Internship Results Report (Submitted by University Supervisor)")
    y -= 18

    sup_name = getattr(report.supervisor_user, "display_name", "") or report.supervisor_user.get_username()
    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Supervisor: {sup_name}")
    y -= 14
    c.drawString(50, y, f"Submitted: {report.submitted_at.strftime('%Y-%m-%d %H:%M') if report.submitted_at else '-'}")
    y -= 20

    # headers
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

        reg_no = str(r.get("reg_no", ""))[:14]
        name = str(r.get("name", ""))[:28]
        ind100 = r.get("industry_100", None)
        ac100 = r.get("academic_100", None)
        avg100 = r.get("average_100", None)

        c.drawString(50, y, reg_no)
        c.drawString(140, y, name)
        c.drawString(330, y, "-" if ind100 is None else str(int(round(float(ind100), 0))))
        c.drawString(405, y, "-" if ac100 is None else str(int(round(float(ac100), 0))))
        c.drawString(485, y, "-" if avg100 is None else str(int(round(float(avg100), 0))))
        y -= 13

    c.showPage()
    c.save()
    buffer.seek(0)

    filename = f"submitted_report_{report.id}.pdf"
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response

@login_required
def coordinator_mark_report_received(request, report_id):
    if request.method != "POST":
        return HttpResponseForbidden("POST only.")
    if not is_coordinator(request.user):
        return HttpResponseForbidden("Coordinators only.")

    report = get_object_or_404(SupervisorResultsReport, id=report_id, status="submitted")
    report.status = "received"
    report.save(update_fields=["status"])
    return redirect("coordinator_results_reports")


@login_required
def coordinator_dashboard(request):
    if not is_coordinator(request.user):
        return HttpResponseForbidden("Coordinators only.")

    qs = SupervisorResultsReport.objects.filter(status__in=["submitted", "received"]).order_by("-submitted_at", "-created_at")
    latest_report = qs.first()
    pending_count = qs.filter(status="submitted").count()

    return render(request, "tracking/coordinator_dashboard.html", {
        "latest_report": latest_report,
        "pending_reports": pending_count,
    })


@login_required
def student_evaluation_form(request):
    # Student only
    if not hasattr(request.user, "student_profile"):
        return HttpResponseForbidden("Students only.")

    placement = _get_student_active_placement(request.user) or _get_student_latest_placement(request.user)
    if not placement:
        return render(request, "tracking/no_active_placement.html")

    evaluation, _ = StudentEvaluation.objects.get_or_create(
        placement=placement,
        defaults={
            "student_user": request.user,
            "program": "",
            "internship_site": placement.company.name if placement.company else "",
            "status": "draft",
        }
    )

    # If already submitted => read-only view
    if evaluation.status == "submitted":
        return render(request, "tracking/student_evaluation_submitted_view.html", {
            "placement": placement,
            "evaluation": evaluation,
        })

    if request.method == "POST":
        form = StudentEvaluationForm(request.POST, instance=evaluation)
        if form.is_valid():
            evaluation = form.save(commit=False)
            evaluation.student_user = request.user
            evaluation.placement = placement

            action = request.POST.get("action", "save")
            if action == "submit":
                evaluation.save()
                evaluation.submit()
                return redirect("student_evaluation_form")
            else:
                evaluation.status = "draft"
                evaluation.save()
                return redirect("student_evaluation_form")
    else:
        form = StudentEvaluationForm(instance=evaluation)

    return render(request, "tracking/student_evaluation_form.html", {
        "placement": placement,
        "evaluation": evaluation,
        "form": form,
    })

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

@login_required
def coordinator_student_evaluations(request):
    if not is_coordinator(request.user):
        return HttpResponseForbidden("Coordinators only.")

    evaluations = (
        StudentEvaluation.objects
        .filter(status="submitted")
        .select_related(
            "placement",
            "placement__company",
            "placement__request__student",
            "placement__request__student__user",
            "student_user",
            "placement__university_supervisor",
        )
        .order_by("-submitted_at")
    )

    return render(request, "tracking/coordinator_student_evaluations.html", {
        "evaluations": evaluations,
    })


@login_required
def coordinator_student_evaluation_detail(request, evaluation_id):
    if not is_coordinator(request.user):
        return HttpResponseForbidden("Coordinators only.")

    evaluation = get_object_or_404(StudentEvaluation, id=evaluation_id, status="submitted")

    return render(request, "tracking/coordinator_student_evaluation_detail.html", {
        "evaluation": evaluation,
        "placement": evaluation.placement,
    })



# You already have is_coordinator()
# def is_coordinator(user): ...



@login_required
def coordinator_dashboard(request):
    if not is_coordinator(request.user):
        return HttpResponseForbidden("Coordinators only.")

    today = timezone.localdate()

    # ----------------------------
    # PLACEMENTS / INTERNSHIP STATUS
    # ----------------------------
    placements = Placement.objects.select_related(
        "company", "request", "request__student", "request__student__user", "university_supervisor", "university_supervisor__user"
    )

    students_on_internship = placements.filter(status="active").count()
    students_completed = placements.filter(status="completed").count()
    students_on_hold = placements.filter(status="on_hold").count()
    students_terminated = placements.filter(status="terminated").count()
    pending_ack = placements.filter(status="pending_student_ack").count()

    # Companies hosting ACTIVE interns + number of interns per company
    companies_hosting = (
        placements.filter(status="active")
        .values("company_id", "company__name")
        .annotate(interns=Count("id"))
        .order_by("company__name")
    )
    companies_hosting_count = companies_hosting.count()

    total_companies_used = placements.values("company_id").distinct().count()

    # ----------------------------
    # ✅ UNIVERSITY SUPERVISOR ALLOCATION (NEW)
    # ----------------------------
    total_uni_supervisors = StaffProfile.objects.filter(
        user__groups__name="UniversitySupervisor",
        user__is_active=True
    ).count()

    # Active placements with / without assigned university supervisor
    active_with_uni_supervisor = placements.filter(status="active", university_supervisor__isnull=False).count()
    active_without_uni_supervisor = placements.filter(status="active", university_supervisor__isnull=True).count()

    # Supervisors who currently supervise at least 1 ACTIVE intern
    uni_supervisors_with_load = (
        placements.filter(status="active", university_supervisor__isnull=False)
        .values("university_supervisor_id")
        .distinct()
        .count()
    )

    uni_supervisors_zero_load = max(total_uni_supervisors - uni_supervisors_with_load, 0)

    # Workload table: supervisor -> number of ACTIVE interns
    uni_supervisor_workload = (
        placements.filter(status="active", university_supervisor__isnull=False)
        .values(
            "university_supervisor_id",
            "university_supervisor__staff_no",
            "university_supervisor__user__first_name",
            "university_supervisor__user__last_name",
            "university_supervisor__user__email",
        )
        .annotate(interns=Count("id"))
        .order_by(
            "university_supervisor__user__first_name",
            "university_supervisor__user__last_name",
        )
    )

    # ----------------------------
    # REQUEST PIPELINE
    # ----------------------------
    reqs = InternshipRequest.objects.select_related("student", "student__user", "preferred_company", "period")

    total_requests = reqs.count()
    draft_requests = reqs.filter(status="draft").count()
    submitted_requests = reqs.filter(status="submitted").count()
    under_review_requests = reqs.filter(status="under_review").count()

    recommendation_issued = reqs.filter(status="recommended").count()
    acceptance_uploaded = reqs.filter(status="acceptance_uploaded").count()
    acceptance_verified = reqs.filter(status="acceptance_verified").count()

    rejected_requests = reqs.filter(status="rejected").count()
    returned_for_acceptance = reqs.filter(status="returned_for_acceptance").count()

    # ----------------------------
    # WEEKLY LOGS OVERVIEW
    # ----------------------------
    logs_draft = WeeklyLog.objects.filter(status="draft").count()
    logs_submitted = WeeklyLog.objects.filter(status="submitted").count()
    logs_returned = WeeklyLog.objects.filter(status="returned_for_edit").count()
    logs_approved = WeeklyLog.objects.filter(status="approved_by_company").count()

    # ----------------------------
    # EVALUATIONS & REPORTS
    # ----------------------------
    industry_eval_submitted = IndustryEvaluation.objects.filter(status="submitted").count()
    academic_eval_submitted = AcademicEvaluation.objects.filter(status="submitted").count()
    student_eval_submitted = StudentEvaluation.objects.filter(status="submitted").count()

    supervisor_reports_submitted = SupervisorResultsReport.objects.filter(status="submitted").count()
    latest_report = SupervisorResultsReport.objects.filter(status="submitted").order_by("-submitted_at").first()

    ready_for_average = Placement.objects.filter(
        status__in=["active", "completed"],
        industry_evaluation__status="submitted",
        academic_evaluation__status="submitted",
    ).distinct().count()

    context = {
        "today": today,

        # placements
        "students_on_internship": students_on_internship,
        "students_completed": students_completed,
        "students_on_hold": students_on_hold,
        "students_terminated": students_terminated,
        "pending_ack": pending_ack,

        # companies
        "companies_hosting": companies_hosting,
        "companies_hosting_count": companies_hosting_count,
        "total_companies_used": total_companies_used,

        # request pipeline
        "total_requests": total_requests,
        "draft_requests": draft_requests,
        "submitted_requests": submitted_requests,
        "under_review_requests": under_review_requests,
        "recommendation_issued": recommendation_issued,
        "acceptance_uploaded": acceptance_uploaded,
        "acceptance_verified": acceptance_verified,
        "returned_for_acceptance": returned_for_acceptance,
        "rejected_requests": rejected_requests,

        # logs
        "logs_draft": logs_draft,
        "logs_submitted": logs_submitted,
        "logs_returned": logs_returned,
        "logs_approved": logs_approved,

        # evaluations
        "industry_eval_submitted": industry_eval_submitted,
        "academic_eval_submitted": academic_eval_submitted,
        "student_eval_submitted": student_eval_submitted,
        "ready_for_average": ready_for_average,

        # reports
        "supervisor_reports_submitted": supervisor_reports_submitted,
        "latest_report": latest_report,

        # ✅ supervisor allocation
        "total_uni_supervisors": total_uni_supervisors,
        "active_with_uni_supervisor": active_with_uni_supervisor,
        "active_without_uni_supervisor": active_without_uni_supervisor,
        "uni_supervisors_with_load": uni_supervisors_with_load,
        "uni_supervisors_zero_load": uni_supervisors_zero_load,
        "uni_supervisor_workload": uni_supervisor_workload,
    }

    return render(request, "dashboards/coordinator_dashboard.html", context)



@login_required
def student_dashboard(request):
    if not hasattr(request.user, "student_profile"):
        return HttpResponseForbidden("Students only.")

    placement = _get_student_active_placement(request.user)
    # (optional) fallback to latest placement if you want:
    # placement = _get_student_active_placement(request.user) or _get_student_latest_placement(request.user)

    return render(request, "dashboards/student_dashboard.html", {
        "placement": placement,
    })
