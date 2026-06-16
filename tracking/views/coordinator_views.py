# tracking/views/coordinator_views.py
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden


# ------------------------------------------------------------
# Coordinator permission helper + decorator (MUST be first)
# ------------------------------------------------------------
def is_coordinator_user(user):
    return user.is_authenticated and (
        user.is_superuser or user.has_perm("accounts.role_coordinator")
    )


def coordinator_required(view_func):
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not is_coordinator_user(request.user):
            return HttpResponseForbidden("VU_Coordinators only.")
        return view_func(request, *args, **kwargs)
    return _wrapped


# ------------------------------------------------------------
# Now imports (safe to import models after decorator exists)
# ------------------------------------------------------------
import datetime
from io import BytesIO

from django.contrib import messages
from django.db import transaction
from django.db.models import (
    Count, Q, OuterRef, Subquery, F, Value,
    IntegerField, FloatField, ExpressionWrapper, Case, When
)
from django.db.models.functions import Coalesce, Cast
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from accounts.models import IndustrySupervisorProfile, StaffProfile
from placements.models import InternshipPeriod, InternshipRequest, Placement
from tracking.models import (
    WeeklyLog,
    IndustryEvaluation,
    AcademicEvaluation,
    StudentEvaluation,
    SupervisorResultsReport,
    SiteVisit,
    SiteVisitReport,
    Notification,
)
from tracking.views.common import (
    ensure_dashboard_notification,
    get_notification_context,
    resolve_dashboard_notification,
)

# ✅ from here down: all your coordinator views...



# ------------------------------------------------------------
# Coordinator permission helper
# ------------------------------------------------------------
def is_coordinator_user(user):
    return user.is_authenticated and (
        user.is_superuser or user.has_perm("accounts.role_coordinator")
    )


def coordinator_required(view_func):
    def _wrapped(request, *args, **kwargs):
        if not is_coordinator_user(request.user):
            return HttpResponseForbidden("VU_Coordinators only.")
        return view_func(request, *args, **kwargs)
    return login_required(_wrapped)


# ------------------------------------------------------------
# Small helper to avoid duplicate dashboard notifications
# ------------------------------------------------------------
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


# ============================================================
# RESULTS REPORTS (Coordinator)
# ============================================================

@coordinator_required
def coordinator_results_reports(request):
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


@coordinator_required
def coordinator_results_report_detail(request, report_id):
    report = get_object_or_404(SupervisorResultsReport, id=report_id)

    if report.status == "draft":
        return HttpResponseForbidden("This report is still in draft and not submitted.")

    return render(request, "tracking/coordinator_results_report_detail.html", {
        "report": report,
        "rows": report.rows or [],
    })


@coordinator_required
def coordinator_results_report_pdf(request, report_id):
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
@coordinator_required
def coordinator_approve_report(request, report_id):
    report = get_object_or_404(SupervisorResultsReport, id=report_id)

    if report.status not in ["submitted", "resubmitted"]:
        return HttpResponseForbidden("Only submitted reports can be approved.")

    report.approve()
    Notification.objects.create(
        user=report.supervisor_user,
        title="Results Report Approved",
        message=f"Your results report (Rev {getattr(report, 'revision', 1)}) has been approved by the coordinator.",
        level="success",
        action_url=reverse("supervisor_results_report"),
        action_text="Open Results Report",
        is_read=False,
    )
    messages.success(request, "Results report approved.")
    return redirect("coordinator_results_report_detail", report_id=report.id)


@require_POST
@coordinator_required
def coordinator_request_changes_report(request, report_id):
    report = get_object_or_404(SupervisorResultsReport, id=report_id)

    if report.status not in ["submitted", "resubmitted", "approved"]:
        return HttpResponseForbidden("This report cannot be reopened now.")

    comment = (request.POST.get("comment") or "").strip() or "Please review and correct the report, then resubmit."

    report.mark_needs_changes(comment=comment)

    # notify supervisor
    action_url = reverse("supervisor_results_report")
    Notification.objects.create(
        user=report.supervisor_user,
        title="Results Report: Changes Requested",
        message=(
            f"Coordinator requested changes on your results report (Rev {getattr(report, 'revision', 1)}). "
            f"Comment: {comment}"
        ),
        level="warning",
        action_url=action_url,
        action_text="Open Results Report",
        is_read=False,
    )

    return redirect("coordinator_results_report_detail", report_id=report.id)


@require_POST
@coordinator_required
def coordinator_reject_report(request, report_id):
    report = get_object_or_404(SupervisorResultsReport, id=report_id)

    if report.status not in ["submitted", "resubmitted"]:
        return HttpResponseForbidden("Only submitted reports can be rejected.")

    comment = (request.POST.get("comment") or "").strip() or "Report rejected. Please contact the coordinator for details."
    report.reject(comment=comment)
    Notification.objects.create(
        user=report.supervisor_user,
        title="Results Report Rejected",
        message=f"Your results report was rejected. Comment: {comment}",
        level="danger",
        action_url=reverse("supervisor_results_report"),
        action_text="Open Results Report",
        is_read=False,
    )
    messages.success(request, "Results report rejected.")
    return redirect("coordinator_results_report_detail", report_id=report.id)


# ============================================================
# COORDINATOR DASHBOARD + NOTIFICATIONS
# ============================================================

@coordinator_required
def coordinator_dashboard(request):
    today = timezone.localdate()
    active_period = InternshipPeriod.objects.filter(is_active=True).first()
    periods_count = InternshipPeriod.objects.count()

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
    # ✅ NEW: STUDENTS RECOMMENDED BY THIS COORDINATOR
    # =========================
    my_recommended_qs = (
        reqs.filter(
            status="recommended",
            recommendation_approved=True,
            recommendation_approved_by=request.user,
        )
        .order_by("-recommendation_issued_at", "-recommendation_approved_at", "-id")
    )

    my_recommended_count = my_recommended_qs.count()
    my_recommended_recent = my_recommended_qs[:10]  # show last 10 on dashboard

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
    # AUTO-GENERATE DASHBOARD ALERTS
    # =========================
    dashboard_keys = [
        "coordinator:acceptance_uploaded",
        "coordinator:requests_pending_approval",
        "coordinator:results_reports_pending",
        "coordinator:placements_missing_supervisor",
    ]
    active_keys = set()

    def notify_hint(key, **kwargs):
        active_keys.add(key)
        ensure_dashboard_notification(request.user, key=key, **kwargs)

    if acceptance_uploaded > 0:
        notify_hint(
            "coordinator:acceptance_uploaded",
            title="Acceptance letters waiting verification",
            message=f"There are {acceptance_uploaded} acceptance letter(s) uploaded and waiting for verification.",
            level="warning",
            action_url="/placements/coordinator/acceptance-queue/",
            action_text="Open Acceptance Queue",
        )

    if recommendation_pending_requests > 0:
        notify_hint(
            "coordinator:requests_pending_approval",
            title="Requests pending approval",
            message=f"There are {recommendation_pending_requests} request(s) pending approval.",
            level="info",
            action_url="/placements/coordinator/queue/",
            action_text="Open Request Queue",
        )

    if pending_reports > 0:
        notify_hint(
            "coordinator:results_reports_pending",
            title="Results reports pending review",
            message=f"There are {pending_reports} results report(s) submitted and waiting for coordinator action.",
            level="danger",
            action_url="/tracking/coordinator/results-reports/",
            action_text="Open Results Reports",
        )

    if active_without_uni_supervisor > 0:
        notify_hint(
            "coordinator:placements_missing_supervisor",
            title="Active placements missing University Supervisor",
            message=f"{active_without_uni_supervisor} active placement(s) have no University Supervisor assigned.",
            level="warning",
            action_url="/placements/coordinator/acceptance-queue/",
            action_text="Assign Supervisors",
        )

    for key in dashboard_keys:
        if key not in active_keys:
            resolve_dashboard_notification(request.user, key)
    notification_context = get_notification_context(request.user)

    return render(request, "dashboards/coordinator_dashboard.html", {
        "today": today,
        "active_period": active_period,
        "periods_count": periods_count,

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

        # ✅ NEW: my recommended students
        "my_recommended_count": my_recommended_count,
        "my_recommended_recent": my_recommended_recent,

        "total_uni_supervisors": total_uni_supervisors,
        "active_with_uni_supervisor": active_with_uni_supervisor,
        "active_without_uni_supervisor": active_without_uni_supervisor,
        "uni_supervisors_with_load": uni_supervisors_with_load,
        "uni_supervisors_zero_load": uni_supervisors_zero_load,
        "uni_supervisor_workload": uni_supervisor_workload,

        **notification_context,
    })


@coordinator_required
def coordinator_active_interns(request):
    query = (request.GET.get("q") or "").strip()
    supervisor_filter = (request.GET.get("supervisor") or "").strip()

    placements = (
        Placement.objects
        .filter(status="active")
        .select_related(
            "company",
            "industry_supervisor",
            "university_supervisor",
            "university_supervisor__user",
            "request",
            "request__student",
            "request__student__user",
            "request__period",
        )
        .order_by("request__student__reg_no")
    )

    if query:
        placements = placements.filter(
            Q(request__student__reg_no__icontains=query)
            | Q(request__student__user__first_name__icontains=query)
            | Q(request__student__user__last_name__icontains=query)
            | Q(request__student__user__email__icontains=query)
            | Q(company__name__icontains=query)
            | Q(company__district__icontains=query)
            | Q(university_supervisor__user__first_name__icontains=query)
            | Q(university_supervisor__user__last_name__icontains=query)
            | Q(university_supervisor__user__email__icontains=query)
            | Q(industry_supervisor__name__icontains=query)
            | Q(industry_supervisor__email__icontains=query)
        ).distinct()

    if supervisor_filter == "assigned":
        placements = placements.filter(university_supervisor__isnull=False)
    elif supervisor_filter == "unassigned":
        placements = placements.filter(university_supervisor__isnull=True)

    placements = list(placements)
    company_ids = {p.company_id for p in placements}
    industry_profiles = (
        IndustrySupervisorProfile.objects
        .filter(company_id__in=company_ids, user__is_active=True)
        .select_related("user", "company")
        .order_by("user__first_name", "user__last_name", "user__email")
    )
    profiles_by_company = {}
    for profile in industry_profiles:
        profiles_by_company.setdefault(profile.company_id, []).append(profile)
    for placement in placements:
        placement.industry_supervisor_profiles = profiles_by_company.get(placement.company_id, [])

    total_active = Placement.objects.filter(status="active").count()
    active_companies = (
        Placement.objects
        .filter(status="active")
        .values("company_id")
        .distinct()
        .count()
    )
    unassigned_count = Placement.objects.filter(status="active", university_supervisor__isnull=True).count()

    return render(request, "tracking/coordinator_active_interns.html", {
        "placements": placements,
        "query": query,
        "supervisor_filter": supervisor_filter,
        "total_active": total_active,
        "active_companies": active_companies,
        "unassigned_count": unassigned_count,
    })



@require_POST
@coordinator_required
def coordinator_notifications_mark_read(request, pk):
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    if not n.is_read:
        n.is_read = True
        n.save(update_fields=["is_read"])
    return redirect("coordinator_dashboard")


@require_POST
@coordinator_required
def coordinator_notifications_mark_all(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return redirect("coordinator_dashboard")


# ============================================================
# STUDENT EVALUATIONS (Coordinator)
# ============================================================

@coordinator_required
def coordinator_student_evaluations(request):
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


@coordinator_required
def coordinator_student_evaluation_detail(request, evaluation_id):
    evaluation = get_object_or_404(StudentEvaluation, id=evaluation_id, status="submitted")
    return render(request, "tracking/coordinator_student_evaluation_detail.html", {
        "evaluation": evaluation,
        "placement": evaluation.placement,
    })


# ============================================================
# STUDENT PERFORMANCE (Coordinator)
# ============================================================

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
    rows = []
    total = 0
    for mark_field, comment_field, label in items:
        mark = _safe_int(_get_attr(obj, mark_field, 0))
        comment = (_get_attr(obj, comment_field, "") or "").strip()
        total += mark
        rows.append({"field": mark_field, "label": label, "mark": mark, "comment": comment})
    return rows, total


@coordinator_required
def coordinator_student_performance(request):
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

    # Industry totals (13 fields * 5 = 65)
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

    # Academic totals (5 fields * 5 = 25)
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

    placements = placements.annotate(
        industry_eval_id=Subquery(ind_qs.values("id")[:1]),
        industry_total=Subquery(ind_qs.values("total_marks")[:1]),
        industry_max=Subquery(ind_qs.values("max_marks")[:1]),
        industry_submitted_at=Subquery(ind_qs.values("submitted_at")[:1]),

        academic_eval_id=Subquery(ac_qs.values("id")[:1]),
        academic_total=Subquery(ac_qs.values("total_marks")[:1]),
        academic_max=Subquery(ac_qs.values("max_marks")[:1]),
        academic_submitted_at=Subquery(ac_qs.values("submitted_at")[:1]),
    ).annotate(
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


@coordinator_required
def coordinator_student_performance_detail(request, placement_id):
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


# ============================================================
# SITE VISITS (Coordinator)
# ============================================================

@coordinator_required
def coordinator_site_visits(request):
    qs = (
        SiteVisit.objects.select_related(
            "placement",
            "placement__company",
            "placement__request__student__user",
            "supervisor__user",
            "report",  # assumes OneToOne related_name="report"
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
                "report": getattr(v, "report", None),
                "all_visits": [],
            }

        grouped[sid]["all_visits"].append(v)

    student_rows = list(grouped.values())

    return render(request, "tracking/coordinator_site_visits.html", {
        "student_rows": student_rows
    })


@coordinator_required
def coordinator_site_visit_report_detail(request, visit_id):
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
