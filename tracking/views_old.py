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
from django.db.models import OuterRef, Subquery


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
#from .utils import generate_recommendation_letter_pdf

from django.db.models import (
    Q, OuterRef, Subquery, F, Value,
    IntegerField, FloatField, ExpressionWrapper,
    Case, When
)
from django.db.models.functions import Coalesce, Cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import Placement, SiteVisit, SiteVisitReport, SiteVisitAcknowledgement
from .forms import SiteVisitScheduleForm, SiteVisitReportForm
from .models import WeeklyLog, Placement
from companies.models import CompanyContact
from django.urls import reverse
from django.db import transaction



def is_university_supervisor(user):
    return user.is_authenticated and (user.is_superuser or user.has_perm("accounts.role_university_supervisor"))

def is_industry_supervisor(user):
    return user.is_authenticated and (user.is_superuser or user.has_perm("accounts.role_industry_supervisor"))

def is_coordinator(user):
    return user.is_authenticated and (user.is_superuser or user.has_perm("accounts.role_coordinator"))



def _get_staff_profile(user):
    # ✅ correct related_name="staff_profile"
    return getattr(user, "staff_profile", None)


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
        Placement.objects.filter(request__student=student)
        .select_related(
            "company", "request", "request__student", "request__student__user",
            "university_supervisor", "university_supervisor__user"
        )
        .order_by("-created_at")
        .first()
    )


def _get_latest_report(user):
    return (
        SupervisorResultsReport.objects
        .filter(supervisor_user=user)
        .annotate(
            submitted_rank=Case(
                When(status="submitted", then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        .order_by("-submitted_rank", "-submitted_at", "-created_at")
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
# Small helpers
# -------------------------------------------------------------------
def _safe_int(v):
    try:
        return int(v or 0)
    except Exception:
        return 0


def _get_attr(obj, name, default=None):
    if not obj:
        return default
    return getattr(obj, name, default)


def _build_rows(obj, items):
    """
    items = [(field_mark, field_comment, "Label"), ...]
    Returns (rows, total)
    """
    rows = []
    total = 0
    for mark_field, comment_field, label in items:
        mark = _safe_int(_get_attr(obj, mark_field, 0))
        comment = (_get_attr(obj, comment_field, "") or "").strip()
        total += mark
        rows.append({"field": mark_field, "label": label, "mark": mark, "comment": comment})
    return rows, total

def _extract_industry_rows_and_total(industry_eval):
    """
    Based on your IndustryEvaluation fields from the error:
    attendance, punctuality, dependability, behaviour, communication_skills,
    culture_fit, flexibility, interpersonal_relations, knowledge_and_learning,
    ethical_awareness, dress_code, basic_work_expectations, work_productivity
    """
    IND_ITEMS = [
        ("attendance", "attendance_comment", "Attendance"),
        ("punctuality", "punctuality_comment", "Punctuality / Time Management"),
        ("dependability", "dependability_comment", "Dependability"),
        ("behaviour", "behaviour_comment", "Behaviour / Conduct"),
        ("communication_skills", "communication_skills_comment", "Communication Skills"),
        ("interpersonal_relations", "interpersonal_relations_comment", "Interpersonal Relations"),
        ("knowledge_and_learning", "knowledge_and_learning_comment", "Knowledge & Learning"),
        ("basic_work_expectations", "basic_work_expectations_comment", "Basic Work Expectations"),
        ("work_productivity", "work_productivity_comment", "Work Productivity"),
        ("culture_fit", "culture_fit_comment", "Culture Fit"),
        ("flexibility", "flexibility_comment", "Flexibility / Adaptability"),
        ("ethical_awareness", "ethical_awareness_comment", "Ethical Awareness"),
        ("dress_code", "dress_code_comment", "Dress Code / Professionalism"),
    ]
    rows, total = _build_rows(industry_eval, IND_ITEMS)
    # If you want a max shown, set it here (optional)
    max_marks = 65
    return rows, total, max_marks


def _extract_academic_rows_and_total(academic_eval):
    """
    Based on your AcademicEvaluation fields from the error:
    culture_fit, general_presentation, support_framework,
    understanding_of_internship, work_output
    """
    AC_ITEMS = [
        ("understanding_of_internship", "understanding_of_internship_comment", "Understanding of Internship"),
        ("support_framework", "support_framework_comment", "Support Framework at Placement"),
        ("work_output", "work_output_comment", "Work Output / Contribution"),
        ("general_presentation", "general_presentation_comment", "General Presentation"),
        ("culture_fit", "culture_fit_comment", "Culture Fit"),
    ]
    rows, total = _build_rows(academic_eval, AC_ITEMS)
    max_marks = 25
    return rows, total, max_marks



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

    # ✅ Force entries order: Monday → Friday (mon, tue, wed, thu, fri)
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
        .prefetch_related(Prefetch("entries", queryset=entry_qs))
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
    staff_profile = getattr(request.user, "staffprofile", None)
    if not staff_profile:
        return HttpResponseForbidden("University Supervisors only.")

    placement = get_object_or_404(
        Placement.objects.select_related(
            "company", "request__student__user", "university_supervisor"
        ),
        pk=placement_id
    )

    # Ensure supervisor is assigned to this placement
    if placement.university_supervisor_id != staff_profile.id:
        return HttpResponseForbidden("You are not assigned to this student.")

    form = SiteVisitScheduleForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        visit = form.save(commit=False)
        visit.placement = placement
        visit.supervisor = staff_profile
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
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")


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

    # ✅ THIS IS THE MISSING PART: build criteria list for template loop
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
        "criteria": criteria,  # ✅ now the 13 rating sections will show
        "today": today,        # optional: for showing Date in template
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

def build_results_rows(supervisor_user, staff):
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
            supervisor_user=supervisor_user
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

    return rows


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

    # Latest report for this supervisor (most recent revision)
    latest_report = (
        SupervisorResultsReport.objects
        .filter(supervisor_user=request.user)
        .order_by("-created_at")
        .first()
    )

    # Decide what rows to display:
    # - If there is a report, show its stored rows
    # - Otherwise generate preview rows (not saved)
    if latest_report:
        rows = latest_report.rows or []
    else:
        rows = build_results_rows(request.user, staff)

    return render(request, "tracking/supervisor_results_report.html", {
        "rows": rows,
        "count": len(rows),
        "latest_report": latest_report,
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

    rows = build_results_rows(request.user, staff)

    # Open editable report: draft OR needs_changes
    report = (
        SupervisorResultsReport.objects
        .select_for_update()
        .filter(supervisor_user=request.user, status__in=["draft", "needs_changes"])
        .order_by("-created_at")
        .first()
    )

    if not report:
        report = SupervisorResultsReport.objects.create(
            supervisor_user=request.user,
            status="draft",
            rows=rows
        )
    else:
        report.rows = rows
        report.save(update_fields=["rows", "last_updated_at"])

    return redirect("supervisor_results_report")


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
@transaction.atomic
def supervisor_submit_results_report(request):
    if request.method != "POST":
        return HttpResponseForbidden("POST only.")
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = getattr(request.user, "staff_profile", None)
    if not staff:
        return HttpResponseForbidden("Staff profile not set.")

    # Find editable report
    report = (
        SupervisorResultsReport.objects
        .select_for_update()
        .filter(supervisor_user=request.user, status__in=["draft", "needs_changes"])
        .order_by("-created_at")
        .first()
    )

    # If none, create a fresh draft from current evaluations
    if not report:
        rows = build_results_rows(request.user, staff)
        report = SupervisorResultsReport.objects.create(
            supervisor_user=request.user,
            status="draft",
            rows=rows
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

from .models import Notification
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

def notify(user, title, message, level="info", action_url="", action_text="Open"):
    # Adjust import path to your real Notification model
    from .models import Notification

    return Notification.objects.create(
        user=user,
        title=title,
        message=message,
        level=level,
        action_url=action_url,
        action_text=action_text,
        is_read=False,
        created_at=timezone.now(),
    )

def notify_coordinators(title, message, level="info", action_url=None, action_text="Open"):
    User = get_user_model()

    # users who have coordinator permission either directly OR via group
    qs = User.objects.filter(is_active=True).filter(
        is_superuser=True
    ) | User.objects.filter(is_active=True, user_permissions__codename="role_coordinator", user_permissions__content_type__app_label="accounts") \
      | User.objects.filter(is_active=True, groups__permissions__codename="role_coordinator", groups__permissions__content_type__app_label="accounts")

    qs = qs.distinct()

    Notification.objects.bulk_create([
        Notification(
            user=u,
            title=title,
            message=message,
            level=level,
            action_url=action_url,
            action_text=action_text,
            is_read=False,
        )
        for u in qs
    ])

@login_required
def supervisor_dashboard(request):
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = getattr(request.user, "staff_profile", None)
    if not staff:
        return HttpResponseForbidden("Staff profile not set. Admin must create StaffProfile for this user.")

    now = timezone.now()

    # ------------------------------------------------------------------
    # ✅ DB Notifications (this is what will show "Needs changes" messages)
    # ------------------------------------------------------------------
    notifications_qs = (
        Notification.objects
        .filter(user=request.user)
        .order_by("-created_at")
    )
    unread_notifications = notifications_qs.filter(is_read=False).count()

    # show recent 8 (you can increase)
    notifications = list(notifications_qs[:8])

    # ------------------------------------------------------------------
    # Latest report + KPI counts
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Site visits: counts + latest
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Student evaluation forms (student feedback)
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # ✅ Add "system hints" into DB notifications ONLY IF not already present
    # (This avoids double-counting unread_notifications)
    # ------------------------------------------------------------------
    def _maybe_add_hint(key: str, title: str, message: str, level="info", action_url="", action_text="Open"):
        """
        Create a lightweight hint notification once per day per key.
        Requires Notification to have 'key' (optional). If you don't have it, remove this helper.
        """
        try:
            # If your model doesn't have "key", this will fail and we just skip.
            exists = Notification.objects.filter(user=request.user, key=key, created_at__date=now.date()).exists()
            if not exists:
                Notification.objects.create(
                    user=request.user,
                    key=key,
                    title=title,
                    message=message,
                    level=level,
                    action_url=action_url,
                    action_text=action_text,
                    is_read=False,
                )
        except Exception:
            # If your Notification model doesn't have 'key', ignore hints
            pass

    # Results report hints
    if ready_for_average_count and (not latest_report or latest_report.status not in ["submitted", "resubmitted", "approved"]):
        _maybe_add_hint(
            key="results_ready",
            title="Results report ready to submit",
            message=f"{ready_for_average_count} placement(s) have both evaluations submitted. Generate/refresh and submit your results report.",
            level="info",
            action_url=reverse("supervisor_results_report"),
            action_text="Open Results Report",
        )

    # Site visit hints
    if next_visit and next_visit.status == "scheduled":
        _maybe_add_hint(
            key="visit_scheduled",
            title="Upcoming site visit (awaiting confirmation)",
            message=(
                f"{next_visit.placement.request.student.user.display_name} — "
                f"{next_visit.placement.company.name} on {next_visit.scheduled_at.strftime('%d %b %Y %H:%M')}."
            ),
            level="warning",
            action_url=reverse("supervisor_site_visits"),
            action_text="View Site Visits",
        )

    if next_visit and next_visit.status == "confirmed":
        _maybe_add_hint(
            key="visit_confirmed",
            title="Upcoming site visit (confirmed)",
            message=(
                f"{next_visit.placement.request.student.user.display_name} — "
                f"{next_visit.placement.company.name} on {next_visit.scheduled_at.strftime('%d %b %Y %H:%M')}."
            ),
            level="info",
            action_url=reverse("submit_site_visit_report", args=[next_visit.id]),
            action_text="Open Visit",
        )

    completed_no_report_qs = site_visits_qs.filter(status="completed", report__isnull=True)
    completed_no_report_count = completed_no_report_qs.count()
    if completed_no_report_count:
        any_v = completed_no_report_qs.order_by("-scheduled_at").first()
        _maybe_add_hint(
            key="visit_report_pending",
            title="Site visit report pending",
            message=f"{completed_no_report_count} completed visit(s) need a report. Please submit the visit report(s).",
            level="danger",
            action_url=reverse("submit_site_visit_report", args=[any_v.id]) if any_v else reverse("supervisor_site_visits"),
            action_text="Submit Report",
        )

    if student_eval_count:
        _maybe_add_hint(
            key="student_feedback",
            title="New student feedback available",
            message=f"{student_eval_count} student evaluation form(s) submitted.",
            level="secondary",
            action_url=reverse("supervisor_student_evaluations"),
            action_text="Open Feedback",
        )

    # ------------------------------------------------------------------
    # Refresh notification list after adding hints (optional)
    # ------------------------------------------------------------------
    notifications_qs = Notification.objects.filter(user=request.user).order_by("-created_at")
    unread_notifications = notifications_qs.filter(is_read=False).count()
    notifications = list(notifications_qs[:8])

    return render(request, "dashboards/supervisor_dashboard.html", {
        "latest_report": latest_report,
        "assigned_count": assigned_count,
        "industry_submitted_count": industry_submitted_count,
        "academic_submitted_count": academic_submitted_count,
        "ready_for_average_count": ready_for_average_count,

        "student_eval_count": student_eval_count,
        "latest_student_evals": latest_student_evals,

        # site visit context
        "latest_site_visits": latest_site_visits,
        "site_visits_scheduled": site_visits_scheduled,
        "site_visits_confirmed": site_visits_confirmed,
        "site_visits_completed": site_visits_completed,
        "site_visits_pending_count": site_visits_pending_count,

        # ✅ DB notifications (will include "Needs changes" sent by coordinator)
        "notifications": notifications,
        "unread_notifications": unread_notifications,
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




from django.views.decorators.http import require_POST
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# Make sure SupervisorResultsReport has these statuses:
# draft, submitted, needs_changes, resubmitted, approved, rejected


@login_required
def coordinator_results_reports(request):
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")


    reports = (
        SupervisorResultsReport.objects
        .exclude(status="draft")  # coordinator sees only sent/reviewed reports
        .select_related("supervisor_user")
        .order_by("-submitted_at", "-updated_at", "-created_at")
    )

    pending_count = reports.filter(status__in=["submitted", "resubmitted"]).count()
    needs_changes_count = reports.filter(status="needs_changes").count()
    approved_count = reports.filter(status="approved").count()
    rejected_count = reports.filter(status="rejected").count()

    return render(request, "tracking/coordinator_results_reports.html", {
        "reports": reports,
        "pending_count": pending_count,
        "needs_changes_count": needs_changes_count,
        "approved_count": approved_count,
        "rejected_count": rejected_count,
    })


@login_required
def coordinator_results_report_detail(request, report_id):
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")


    report = get_object_or_404(
        SupervisorResultsReport,
        id=report_id
    )

    # Coordinator should not open drafts (they're not sent)
    if report.status == "draft":
        return HttpResponseForbidden("This report is still in draft and not submitted.")

    return render(request, "tracking/coordinator_results_report_detail.html", {
        "report": report,
        "rows": report.rows or [],
    })


@login_required
def coordinator_results_report_pdf(request, report_id):
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")


    report = get_object_or_404(SupervisorResultsReport, id=report_id)

    if report.status == "draft":
        return HttpResponseForbidden("Draft report cannot be exported by coordinator.")

    rows = report.rows or []

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 50
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "Internship Results Report (Coordinator Copy)")
    y -= 18

    sup_name = getattr(report.supervisor_user, "display_name", "") or report.supervisor_user.get_username()
    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Supervisor: {sup_name}")
    y -= 14
    c.drawString(50, y, f"Status: {report.status.upper()}   •   Revision: {getattr(report, 'revision', 1)}")
    y -= 14
    c.drawString(50, y, f"Submitted: {report.submitted_at.strftime('%Y-%m-%d %H:%M') if report.submitted_at else '-'}")
    y -= 20

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

    filename = f"results_report_{report.id}_rev{getattr(report, 'revision', 1)}.pdf"
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@require_POST
@login_required
def coordinator_approve_report(request, report_id):
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")


    report = get_object_or_404(SupervisorResultsReport, id=report_id)

    # Only approve reports that are currently under review
    if report.status not in ["submitted", "resubmitted"]:
        return HttpResponseForbidden("Only submitted reports can be approved.")

    report.approve()
    return redirect("coordinator_results_report_detail", report_id=report.id)


@require_POST
@login_required
def coordinator_request_changes_report(request, report_id):
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")


    report = get_object_or_404(SupervisorResultsReport, id=report_id)

    if report.status not in ["submitted", "resubmitted", "approved"]:
        return HttpResponseForbidden("This report cannot be reopened now.")

    comment = (request.POST.get("comment") or "").strip()
    if not comment:
        comment = "Please review and correct the report, then resubmit."

    # ✅ Change status and store comment
    report.mark_needs_changes(comment=comment)

    # ✅ Send notification to that supervisor
    action_url = reverse("supervisor_results_report")
    notify(
        user=report.supervisor_user,
        title="Results Report: Changes Requested",
        message=f"Coordinator requested changes on your results report (Rev {getattr(report, 'revision', 1)}). "
                f"Comment: {comment}",
        level="warning",
        action_url=action_url,
        action_text="Open Results Report",
    )

    return redirect("coordinator_results_report_detail", report_id=report.id)

@require_POST
@login_required
def coordinator_reject_report(request, report_id):
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")


    report = get_object_or_404(SupervisorResultsReport, id=report_id)

    if report.status not in ["submitted", "resubmitted"]:
        return HttpResponseForbidden("Only submitted reports can be rejected.")

    comment = (request.POST.get("comment") or "").strip()
    if not comment:
        comment = "Report rejected. Please contact the coordinator for details."

    report.reject(comment=comment)
    return redirect("coordinator_results_report_detail", report_id=report.id)



def _ensure_notification(user, *, title, message, level="info", action_url="", action_text="Open"):
    """
    Create a notification only if a similar unread one doesn't already exist.
    Prevents duplicates on each dashboard refresh.
    """
    qs = Notification.objects.filter(
        user=user,
        title=title,
        action_url=action_url,
        is_read=False,
    )
    if not qs.exists():
        Notification.objects.create(
            user=user,
            title=title,
            message=message,
            level=level,
            action_url=action_url,
            action_text=action_text,
            is_read=False,
        )


@login_required
def coordinator_dashboard(request):
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")

    today = timezone.localdate()

    # =========================
    # RESULTS REPORTS
    # =========================
    qs_reports = SupervisorResultsReport.objects.filter(
        status__in=["submitted", "received"]
    ).order_by("-submitted_at", "-created_at")

    latest_report = qs_reports.first()
    pending_reports = qs_reports.filter(status="submitted").count()

    # =========================
    # PLACEMENTS / INTERNSHIP STATUS
    # =========================
    placements = Placement.objects.select_related(
        "company", "request", "request__student", "request__student__user"
    )

    students_on_internship = placements.filter(status="active").count()
    students_completed = placements.filter(status="completed").count()
    pending_ack = placements.filter(status="pending_student_ack").count()
    students_on_hold = placements.filter(status="on_hold").count()

    companies_hosting = (
        placements.filter(status="active")
        .values("company_id", "company__name")
        .annotate(interns=Count("id"))
        .order_by("company__name")
    )
    companies_hosting_count = companies_hosting.count()

    # =========================
    # REQUEST PIPELINE + RECENT SUBMISSIONS
    # =========================
    reqs = InternshipRequest.objects.select_related(
        "student", "student__user", "preferred_company", "period"
    )

    total_requests = reqs.count()
    draft_requests = reqs.filter(status="draft").count()
    submitted_requests = reqs.filter(status="submitted").count()
    under_review_requests = reqs.filter(status="under_review").count()
    recommendation_pending_requests = reqs.filter(status="recommendation_pending").count()
    recommendation_issued = reqs.filter(status="recommended").count()
    acceptance_uploaded = reqs.filter(status="acceptance_uploaded").count()
    acceptance_verified = reqs.filter(status="acceptance_verified").count()
    rejected_requests = reqs.filter(status="rejected").count()
    returned_for_acceptance = reqs.filter(status="returned_for_acceptance").count()

    recent_requests = (
        reqs.filter(status__in=["submitted", "under_review", "recommendation_pending"])
        .order_by("-submitted_at")[:10]
    )

    # =========================
    # UNIVERSITY SUPERVISOR ALLOCATION
    # =========================
    total_uni_supervisors = (
        StaffProfile.objects.filter(user__is_active=True)
        .filter(
            Q(
                user__user_permissions__codename="role_university_supervisor",
                user__user_permissions__content_type__app_label="accounts",
            )
            |
            Q(
                user__groups__permissions__codename="role_university_supervisor",
                user__groups__permissions__content_type__app_label="accounts",
            )
        )
        .distinct()
        .count()
    )

    active_with_uni_supervisor = placements.filter(status="active", university_supervisor__isnull=False).count()
    active_without_uni_supervisor = placements.filter(status="active", university_supervisor__isnull=True).count()

    uni_supervisors_with_load = (
        placements.filter(status="active", university_supervisor__isnull=False)
        .values("university_supervisor_id")
        .distinct()
        .count()
    )
    uni_supervisors_zero_load = max(total_uni_supervisors - uni_supervisors_with_load, 0)

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
        .order_by("university_supervisor__user__first_name", "university_supervisor__user__last_name")
    )

    # =========================
    # PERFORMANCE STATS
    # =========================
    logs_approved = WeeklyLog.objects.filter(status="approved_by_company").count()
    industry_eval_submitted = IndustryEvaluation.objects.filter(status="submitted").count()
    academic_eval_submitted = AcademicEvaluation.objects.filter(status="submitted").count()
    student_eval_submitted = StudentEvaluation.objects.filter(status="submitted").count()

    ready_for_average = Placement.objects.filter(
        industry_evaluation__status="submitted",
        academic_evaluation__status="submitted",
    ).distinct().count()

    # =========================
    # ✅ AUTO-GENERATE DASHBOARD ALERTS (THIS FIXES YOUR ISSUE)
    # =========================
    # These create actual Notification rows so your UI can show them.
    if acceptance_uploaded > 0:
        _ensure_notification(
            request.user,
            title="Acceptance letters waiting verification",
            message=f"There are {acceptance_uploaded} acceptance letter(s) uploaded and waiting for verification.",
            level="warning",
            action_url="/placements/coordinator/acceptance-queue/",  # ✅ or reverse("coordinator_acceptance_queue")
            action_text="Open Acceptance Queue",
        )

    if recommendation_pending_requests > 0:
        _ensure_notification(
            request.user,
            title="Requests pending approval",
            message=f"There are {recommendation_pending_requests} request(s) pending approval.",
            level="info",
            action_url="/placements/coordinator/queue/",  # ✅ or reverse("coordinator_queue")
            action_text="Open Request Queue",
        )

    if pending_reports > 0:
        _ensure_notification(
            request.user,
            title="Results reports pending review",
            message=f"There are {pending_reports} results report(s) submitted and waiting for coordinator action.",
            level="danger",
            action_url="/tracking/coordinator/results-reports/",  # ✅ or reverse("coordinator_results_reports")
            action_text="Open Results Reports",
        )

    if active_without_uni_supervisor > 0:
        _ensure_notification(
            request.user,
            title="Active placements missing University Supervisor",
            message=f"{active_without_uni_supervisor} active placement(s) have no University Supervisor assigned.",
            level="warning",
            action_url="/placements/coordinator/acceptance-queue/",
            action_text="Assign Supervisors",
        )

    # =========================
    # NOTIFICATIONS (latest)
    # =========================
    notifications = Notification.objects.filter(user=request.user).order_by("-created_at")[:8]
    unread_notifications = Notification.objects.filter(user=request.user, is_read=False).count()

    return render(request, "dashboards/coordinator_dashboard.html", {
        "today": today,

        "latest_report": latest_report,
        "pending_reports": pending_reports,

        "students_on_internship": students_on_internship,
        "students_completed": students_completed,
        "pending_ack": pending_ack,
        "students_on_hold": students_on_hold,

        "companies_hosting": companies_hosting,
        "companies_hosting_count": companies_hosting_count,

        "total_requests": total_requests,
        "draft_requests": draft_requests,
        "submitted_requests": submitted_requests,
        "under_review_requests": under_review_requests,
        "recommendation_pending_requests": recommendation_pending_requests,
        "recommendation_issued": recommendation_issued,
        "acceptance_uploaded": acceptance_uploaded,
        "acceptance_verified": acceptance_verified,
        "returned_for_acceptance": returned_for_acceptance,
        "rejected_requests": rejected_requests,

        "logs_approved": logs_approved,
        "industry_eval_submitted": industry_eval_submitted,
        "academic_eval_submitted": academic_eval_submitted,
        "student_eval_submitted": student_eval_submitted,
        "ready_for_average": ready_for_average,

        "recent_requests": recent_requests,

        "total_uni_supervisors": total_uni_supervisors,
        "active_with_uni_supervisor": active_with_uni_supervisor,
        "active_without_uni_supervisor": active_without_uni_supervisor,
        "uni_supervisors_with_load": uni_supervisors_with_load,
        "uni_supervisors_zero_load": uni_supervisors_zero_load,
        "uni_supervisor_workload": uni_supervisor_workload,

        "notifications": notifications,
        "unread_notifications": unread_notifications,
    })

@require_POST
@login_required
def coordinator_notifications_mark_read(request, pk):
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")

    n = get_object_or_404(Notification, pk=pk, user=request.user)
    if not n.is_read:
        n.is_read = True
        n.save(update_fields=["is_read"])
    return redirect("coordinator_dashboard")


@require_POST
@login_required
def coordinator_notifications_mark_all(request):
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")

    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return redirect("coordinator_dashboard")

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
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")


    evaluation = get_object_or_404(StudentEvaluation, id=evaluation_id, status="submitted")

    return render(request, "tracking/coordinator_student_evaluation_detail.html", {
        "evaluation": evaluation,
        "placement": evaluation.placement,
    })



@login_required
def coordinator_student_performance(request):
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")

    placements = (
        Placement.objects
        .select_related(
            "company",
            "request",
            "request__student",
            "request__student__user",
            "university_supervisor",
            "university_supervisor__user",
        )
        .exclude(status__in=["terminated"])
        .order_by("-created_at")
    )

    # -------------------------
    # INDUSTRY totals (13 fields * 5 = 65)
    # -------------------------
    IND_MAX = 65

    ind_total_expr = (
        Coalesce(F("attendance"), 0) +
        Coalesce(F("basic_work_expectations"), 0) +
        Coalesce(F("behaviour"), 0) +
        Coalesce(F("communication_skills"), 0) +
        Coalesce(F("culture_fit"), 0) +
        Coalesce(F("dependability"), 0) +
        Coalesce(F("dress_code"), 0) +
        Coalesce(F("ethical_awareness"), 0) +
        Coalesce(F("flexibility"), 0) +
        Coalesce(F("interpersonal_relations"), 0) +
        Coalesce(F("knowledge_and_learning"), 0) +
        Coalesce(F("punctuality"), 0) +
        Coalesce(F("work_productivity"), 0)
    )

    ind_qs = (
        IndustryEvaluation.objects
        .filter(placement_id=OuterRef("pk"), status="submitted")
        .annotate(
            total_marks=Cast(ind_total_expr, IntegerField()),
            max_marks=Value(IND_MAX, output_field=IntegerField()),
        )
        .order_by("-submitted_at", "-created_at")
    )

    # -------------------------
    # ACADEMIC totals (5 fields * 5 = 25)
    # -------------------------
    AC_MAX = 25

    ac_total_expr = (
        Coalesce(F("understanding_of_internship"), 0) +
        Coalesce(F("support_framework"), 0) +
        Coalesce(F("culture_fit"), 0) +
        Coalesce(F("work_output"), 0) +
        Coalesce(F("general_presentation"), 0)
    )

    ac_qs = (
        AcademicEvaluation.objects
        .filter(placement_id=OuterRef("pk"), status="submitted")
        .annotate(
            total_marks=Cast(ac_total_expr, IntegerField()),
            max_marks=Value(AC_MAX, output_field=IntegerField()),
        )
        .order_by("-submitted_at", "-created_at")
    )

    # -------------------------
    # Annotate placements with latest submitted evaluations
    # -------------------------
    placements = placements.annotate(
        industry_eval_id=Subquery(ind_qs.values("id")[:1]),
        industry_total=Subquery(ind_qs.values("total_marks")[:1]),
        industry_max=Subquery(ind_qs.values("max_marks")[:1]),
        industry_submitted_at=Subquery(ind_qs.values("submitted_at")[:1]),

        academic_eval_id=Subquery(ac_qs.values("id")[:1]),
        academic_total=Subquery(ac_qs.values("total_marks")[:1]),
        academic_max=Subquery(ac_qs.values("max_marks")[:1]),
        academic_submitted_at=Subquery(ac_qs.values("submitted_at")[:1]),
    )

    # Optional average using totals (not /100)
    placements = placements.annotate(
        avg_total=Case(
            When(
                industry_eval_id__isnull=False,
                academic_eval_id__isnull=False,
                then=ExpressionWrapper(
                    (Coalesce(F("industry_total"), 0.0) + Coalesce(F("academic_total"), 0.0)) / Value(2.0),
                    output_field=FloatField(),
                ),
            ),
            default=Value(None),
            output_field=FloatField(),
        )
    )

    # Search
    q = (request.GET.get("q") or "").strip()
    if q:
        placements = placements.filter(
            Q(request__student__reg_no__icontains=q)
            | Q(request__student__user__first_name__icontains=q)
            | Q(request__student__user__last_name__icontains=q)
            | Q(company__name__icontains=q)
        )

    return render(request, "tracking/coordinator_student_performance.html", {
        "placements": placements,
        "q": q,
        "count": placements.count(),
    })

@login_required
def coordinator_student_performance_detail(request, placement_id):
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")


    placement = get_object_or_404(
        Placement.objects.select_related(
            "company",
            "request",
            "request__student",
            "request__student__user",
            "university_supervisor",
            "university_supervisor__user",
        ),
        id=placement_id
    )

    industry_eval = (
        IndustryEvaluation.objects
        .filter(placement=placement, status="submitted")
        .order_by("-submitted_at", "-created_at")
        .first()
    )

    academic_eval = (
        AcademicEvaluation.objects
        .filter(placement=placement, status="submitted")
        .order_by("-submitted_at", "-created_at")
        .first()
    )

    # ✅ EXACT order from your IndustryEvaluation.SCORE_FIELDS
    IND_ITEMS = [
        ("basic_work_expectations", "basic_work_expectations_comment", "Basic Work Expectations"),
        ("knowledge_and_learning", "knowledge_and_learning_comment", "Knowledge and Learning"),
        ("ethical_awareness", "ethical_awareness_comment", "Ethical Awareness"),
        ("interpersonal_relations", "interpersonal_relations_comment", "Interpersonal Relations"),
        ("communication_skills", "communication_skills_comment", "Communication Skills"),
        ("attendance", "attendance_comment", "Attendance"),
        ("punctuality", "punctuality_comment", "Punctuality"),
        ("flexibility", "flexibility_comment", "Flexibility"),
        ("dependability", "dependability_comment", "Dependability"),
        ("culture_fit", "culture_fit_comment", "Culture Fit"),
        ("dress_code", "dress_code_comment", "Dress Code"),
        ("behaviour", "behaviour_comment", "Behaviour"),
        ("work_productivity", "work_productivity_comment", "Work Productivity"),
    ]

    # ✅ EXACT order from your AcademicEvaluation.SCORE_FIELDS
    AC_ITEMS = [
        ("understanding_of_internship", "understanding_of_internship_comment", "Understanding of Internship"),
        ("support_framework", "support_framework_comment", "Support Framework"),
        ("culture_fit", "culture_fit_comment", "Culture Fit"),
        ("work_output", "work_output_comment", "Work Output"),
        ("general_presentation", "general_presentation_comment", "General Presentation"),
    ]

    ind_rows, ind_total = _build_rows(industry_eval, IND_ITEMS)
    ac_rows, ac_total = _build_rows(academic_eval, AC_ITEMS)

    ind_max = industry_eval.max_marks if industry_eval else 65
    ac_max = academic_eval.max_marks if academic_eval else 25

    return render(request, "tracking/coordinator_student_performance_detail.html", {
        "placement": placement,

        "industry_eval": industry_eval,
        "ind_rows": ind_rows,
        "ind_total": ind_total,
        "ind_max": ind_max,

        "academic_eval": academic_eval,
        "ac_rows": ac_rows,
        "ac_total": ac_total,
        "ac_max": ac_max,
    })


@login_required
def student_dashboard(request):
    if not hasattr(request.user, "student_profile"):
        return HttpResponseForbidden("Students only.")

    placement = _get_student_active_placement(request.user)

    notifications = []
    now = timezone.now()

    # If no active placement
    if not placement:
        notifications.append({
            "level": "warning",
            "title": "No active placement",
            "message": "Submit your internship request and upload an acceptance letter once you get it.",
            "created_at": now,
            "action_text": "Submit Request",
            "action_url": reverse("submit_request"),
        })
        return render(request, "dashboards/student_dashboard.html", {
            "placement": None,
            "notifications": notifications,
            "unread_notifications": len(notifications),
            "site_visit_next": None,
            "site_visit_last_completed": None,
        })

    # ---------------------------
    # Weekly Logs status (optional)
    # ---------------------------
    student_log_qs = WeeklyLog.objects.filter(placement=placement)

    pending_company = student_log_qs.filter(status="submitted").count()
    returned_for_edit = student_log_qs.filter(status="returned_for_edit").count()
    approved_by_company = student_log_qs.filter(status="approved_by_company").count()

    if returned_for_edit:
        notifications.append({
            "level": "danger",
            "title": "Weekly log returned",
            "message": f"{returned_for_edit} log(s) were returned for edit. Please correct and resubmit.",
            "created_at": now,
            "action_text": "Open Logs",
            "action_url": reverse("student_logs"),
        })

    if pending_company:
        notifications.append({
            "level": "info",
            "title": "Logs awaiting approval",
            "message": f"{pending_company} submitted log(s) are waiting for your industry supervisor to approve.",
            "created_at": now,
            "action_text": "View Logs",
            "action_url": reverse("student_logs"),
        })

    # ---------------------------
    # Site Visits (scheduled/confirmed notifications only)
    # ---------------------------
    site_visits_qs = (
        SiteVisit.objects
        .filter(placement=placement)  # ✅ ONLY this student's placement
        .order_by("scheduled_at")
    )

    # next visit: upcoming scheduled/confirmed
    site_visit_next = (
        site_visits_qs
        .filter(status__in=["scheduled", "confirmed"], scheduled_at__gte=now)
        .order_by("scheduled_at")
        .first()
    )

    # ✅ Notification for scheduled visit (needs confirmation)
    if site_visit_next and site_visit_next.status == "scheduled":
        notifications.append({
            "level": "warning",
            "title": "Site visit needs confirmation",
            "message": f"A site visit is scheduled for {site_visit_next.scheduled_at.strftime('%d %b %Y %H:%M')}. Please confirm attendance.",
            "created_at": now,
            "action_text": "Confirm Visit",
            "action_url": reverse("student_confirm_site_visit", args=[site_visit_next.id]),
        })

    # ✅ Optional: reminder for confirmed upcoming visit (no action needed)
    if site_visit_next and site_visit_next.status == "confirmed":
        notifications.append({
            "level": "info",
            "title": "Upcoming site visit",
            "message": f"You have a confirmed site visit on {site_visit_next.scheduled_at.strftime('%d %b %Y %H:%M')}. Be ready.",
            "created_at": now,
            "action_text": "View Visits",
            "action_url": reverse("student_site_visits"),
        })

    # ✅ Keep this for display in the template (NOT a notification)
    site_visit_last_completed = (
        site_visits_qs
        .filter(status="completed")
        .order_by("-actual_at", "-scheduled_at")
        .first()
    )

    # ---------------------------
    # Student Evaluation availability reminder (optional)
    # ---------------------------
    if placement.status == "active":
        ev = StudentEvaluation.objects.filter(placement=placement, student_user=request.user).first()
        if not ev:
            notifications.append({
                "level": "secondary",
                "title": "Student evaluation",
                "message": "Remember to fill the student evaluation form at the end of internship.",
                "created_at": now,
                "action_text": "Open Form",
                "action_url": reverse("student_evaluation_form"),
            })

    return render(request, "dashboards/student_dashboard.html", {
        "placement": placement,
        "notifications": notifications,
        "unread_notifications": len(notifications),
        "site_visit_next": site_visit_next,
        "site_visit_last_completed": site_visit_last_completed,

        # optional counts
        "pending_company_logs": pending_company,
        "returned_logs": returned_for_edit,
        "approved_logs": approved_by_company,
    })

# you already have role helpers like is_industry_supervisor(...)
# assume you have: is_university_supervisor(user), is_student(user), is_coordinator(user)
# adjust to your project helpers.




@login_required
def supervisor_add_site_visit(request, placement_id):
    # ✅ must be University Supervisor
    if not is_university_supervisor(request.user):
        return HttpResponseForbidden("University Supervisors only.")

    staff = _get_staff_profile(request.user)  # ✅ FIXED (no staffprofile)
    if not staff:
        return HttpResponseForbidden("Staff profile not set. Admin must create StaffProfile for this user.")

    placement = get_object_or_404(
        Placement.objects.select_related("company", "request__student__user", "university_supervisor"),
        pk=placement_id,
    )

    # ✅ ensure supervisor is assigned to this placement
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

    # Always allow viewing (GET) for the supervisor's own visits
    report, _ = SiteVisitReport.objects.get_or_create(site_visit=visit)
    form = SiteVisitReportForm(request.POST or None, request.FILES or None, instance=report)

    # Only restrict submitting/editing (POST)
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
# STUDENT: SITE VISITS
# -------------------------------------------------------------------
@login_required
def student_site_visits(request):
    if not hasattr(request.user, "student_profile"):
        return HttpResponseForbidden("Students only.")

    visits = (
        SiteVisit.objects
        .filter(placement__request__student__user=request.user)
        .select_related("placement", "placement__company", "supervisor__user")
        .order_by("-scheduled_at")
    )
    return render(request, "tracking/student_site_visits.html", {"visits": visits})


@login_required
def student_confirm_site_visit(request, visit_id):
    if not hasattr(request.user, "student_profile"):
        return HttpResponseForbidden("Students only.")

    visit = get_object_or_404(
        SiteVisit,
        id=visit_id,
        placement__request__student__user=request.user
    )

    if visit.status != "scheduled":
        messages.info(request, "This visit is not in a schedulable state.")
        return redirect("student_site_visits")

    if request.method == "POST":
        visit.status = "confirmed"
        visit.save(update_fields=["status"])
        messages.success(request, "Visit confirmed.")
        return redirect("student_site_visits")

    return render(request, "tracking/student_confirm_site_visit.html", {"visit": visit})


@login_required
def student_ack_site_visit(request, visit_id):
    """
    Student acknowledges a completed visit.
    If you have a real SiteVisitAcknowledgement model, store it there.
    If not, we just show a success message (no DB write).
    """
    if not hasattr(request.user, "student_profile"):
        return HttpResponseForbidden("Students only.")

    visit = get_object_or_404(
        SiteVisit.objects.select_related("placement"),
        id=visit_id,
        placement__request__student__user=request.user
    )

    # Only acknowledge after report + completion
    # (Adjust statuses to match your SiteVisit model)
    if visit.status != "completed":
        messages.error(request, "You can only acknowledge a completed site visit.")
        return redirect("student_site_visits")

    # If your report is OneToOne with related_name="report"
    has_report = SiteVisitReport.objects.filter(site_visit=visit).exists()
    if not has_report:
        messages.error(request, "You can only acknowledge a visit that has a report.")
        return redirect("student_site_visits")

    if request.method == "POST":
        messages.success(request, "Acknowledged. Thank you.")
        return redirect("student_site_visits")

    return render(request, "tracking/student_ack_site_visit.html", {"visit": visit})

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



# -------------------------------------------------------------------
# COORDINATOR: SITE VISITS
@login_required
def coordinator_site_visits(request):
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")


    qs = (
        SiteVisit.objects.select_related(
            "placement",
            "placement__company",
            "placement__request__student__user",
            "supervisor__user",
            "report",  # ✅ this assumes related_name="report"
        )
        .order_by("-scheduled_at")
    )

    grouped = {}
    for v in qs:
        student = v.placement.request.student
        sid = student.id

        if sid not in grouped:
            grouped[sid] = {
                "student": student,
                "company_name": getattr(v.placement.company, "name", ""),
                "supervisor": v.supervisor,
                "visit": v,  # latest visit
                "report": getattr(v, "report", None),  # ✅ safe
                "all_visits": [],
            }

        grouped[sid]["all_visits"].append(v)

    student_rows = list(grouped.values())

    return render(request, "tracking/coordinator_site_visits.html", {
        "student_rows": student_rows
    })


def is_coordinator(user):
    return user.is_superuser or user.groups.filter(name__in=["Coordinator", "Admin"]).exists()

@login_required
def coordinator_site_visit_report_detail(request, visit_id):
    if not (request.user.is_superuser or request.user.has_perm("accounts.role_coordinator")):
        return HttpResponseForbidden("VU_Coordinators only.")


    visit = get_object_or_404(
        SiteVisit.objects.select_related(
            "placement",
            "placement__company",
            "placement__request__student__user",
            "supervisor__user",
            "report",
        ),
        id=visit_id,
    )

    report = getattr(visit, "report", None)
    if not report:
        messages.error(request, "No report has been submitted for this visit yet.")
        return redirect("coordinator_site_visits")

    return render(request, "tracking/coordinator_site_visit_report_detail.html", {
        "visit": visit,
        "report": report,
    })

@login_required
def industry_dashboard(request):
    if not is_industry_supervisor(request.user):
        return HttpResponseForbidden("Industry Supervisors only.")

    user_email = (request.user.email or "").strip()
    contact = CompanyContact.objects.filter(email__iexact=user_email).select_related("company").first()

    # Prefer company from industry_profile (same as other company views)
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
            "unread_notifications": 1,
        }
        notifications = [{
            "title": "Profile not linked",
            "message": "No company linked to your account. Ask the coordinator to link your Industry Profile / Company Contact.",
            "created_at": timezone.now(),
        }]
        return render(request, "dashboards/industry_dashboard.html", {
            "pending_logs": 0,
            "approved_logs": 0,
            "returned_logs": 0,
            "assigned_students": 0,
            "submitted_evaluations": 0,
            "unread_notifications": 1,
            "notifications": notifications,
            "recent_logs": [],
            "contact": contact,
            "stats": empty_stats,
        })

    # ✅ COUNT BY COMPANY (not by CompanyContact)
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

    # ✅ If you have IndustryEvaluation model, count them properly
    submitted_evaluations = IndustryEvaluation.objects.filter(company=company, status="submitted").count()

    notifications = []
    now = timezone.now()
    if pending_logs:
        notifications.append({
            "title": "Pending logs need review",
            "message": f"You have {pending_logs} submitted weekly log(s) waiting for approval.",
            "created_at": now,
        })
    if returned_logs:
        notifications.append({
            "title": "Returned logs",
            "message": f"{returned_logs} log(s) were returned for edit. Students may resubmit anytime.",
            "created_at": now,
        })

    pending_ack = Placement.objects.filter(company=company, status="pending_student_ack").count()
    if pending_ack:
        notifications.append({
            "title": "Placements pending acknowledgement",
            "message": f"{pending_ack} placement(s) are pending student acknowledgement.",
            "created_at": now,
        })

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
        "unread_notifications": len(notifications),
    }

    return render(request, "dashboards/industry_dashboard.html", {
        "pending_logs": pending_logs,
        "approved_logs": approved_logs,
        "returned_logs": returned_logs,
        "assigned_students": assigned_students,
        "submitted_evaluations": submitted_evaluations,
        "unread_notifications": len(notifications),

        "notifications": notifications,
        "recent_logs": recent_logs,
        "contact": contact,
        "stats": stats,
    })


@login_required
def mark_notification_read(request, notif_id):
    n = get_object_or_404(Notification, id=notif_id, user=request.user)
    n.is_read = True
    n.save(update_fields=["is_read"])
    return redirect(n.action_url or "supervisor_dashboard")
