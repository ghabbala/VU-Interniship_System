# tracking/views/student_views.py
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from tracking.forms import (
    StudentInternshipReportForm,
    WeeklyLogForm,
    WeeklyLogEntryFormSet,
    StudentEvaluationForm,
)
from tracking.models import (
    AcademicEvaluation,
    IndustryEvaluation,
    SiteVisit,
    SiteVisitReport,
    StudentEvaluation,
    StudentInternshipReport,
    WeeklyLog,
    WeeklyLogAttachment,
    WeeklyLogEntry,
)

from .common import (
    DAYS, DAY_ORDER,
    _get_student_active_placement, _get_student_latest_placement,
    ensure_dashboard_notification, get_notification_context, notify, resolve_dashboard_notification,
)
from placements.models import InternshipRequest
from django.http import FileResponse, Http404
from django.views.decorators.clickjacking import xframe_options_sameorigin


INDUSTRY_SCORE_LABELS = [
    ("basic_work_expectations", "Basic work expectations"),
    ("knowledge_and_learning", "Knowledge and ability to learn"),
    ("ethical_awareness", "Ethical awareness and conduct"),
    ("interpersonal_relations", "Interpersonal relations"),
    ("communication_skills", "Communication skills"),
    ("attendance", "Attendance"),
    ("punctuality", "Punctuality"),
    ("flexibility", "Flexibility"),
    ("dependability", "Dependability"),
    ("culture_fit", "Culture fit"),
    ("dress_code", "Dress code"),
    ("behaviour", "Behaviour"),
    ("work_productivity", "Work productivity"),
]

ACADEMIC_SCORE_LABELS = [
    ("understanding_of_internship", "Understanding of internship"),
    ("support_framework", "Support framework"),
    ("culture_fit", "Culture fit"),
    ("work_output", "Work output"),
    ("general_presentation", "General presentation"),
]


def _evaluation_breakdown(evaluation, labels):
    if not evaluation:
        return []

    return [
        {
            "label": label,
            "score": getattr(evaluation, field, None),
            "max_score": 5,
        }
        for field, label in labels
    ]


def _student_marks_context(placement):
    if not placement:
        return {
            "industry": None,
            "academic": None,
            "industry_breakdown": [],
            "academic_breakdown": [],
            "overall_percent": None,
            "overall_total": None,
            "overall_max": None,
        }

    industry = (
        IndustryEvaluation.objects
        .filter(placement=placement, status="submitted")
        .select_related("supervisor_user")
        .first()
    )
    academic = (
        AcademicEvaluation.objects
        .filter(placement=placement, status="submitted")
        .select_related("supervisor_user")
        .first()
    )

    overall_total = None
    overall_max = None
    overall_percent = None

    submitted_evaluations = [ev for ev in (industry, academic) if ev]
    if submitted_evaluations:
        overall_total = sum(ev.total_marks for ev in submitted_evaluations)
        overall_max = sum(ev.max_marks for ev in submitted_evaluations)
        overall_percent = (overall_total / overall_max) * 100 if overall_max else 0

    return {
        "industry": industry,
        "academic": academic,
        "industry_breakdown": _evaluation_breakdown(industry, INDUSTRY_SCORE_LABELS),
        "academic_breakdown": _evaluation_breakdown(academic, ACADEMIC_SCORE_LABELS),
        "overall_percent": overall_percent,
        "overall_total": overall_total,
        "overall_max": overall_max,
    }

# -------------------------------------------------------------------
# STUDENT: LOGS
# -------------------------------------------------------------------
@login_required
def student_logs(request):
    placement = _get_student_active_placement(request.user)
    if not placement:
        return render(request, "tracking/no_active_placement.html")

    logs = WeeklyLog.objects.filter(placement=placement).prefetch_related("attachments").order_by("-week_no")
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
        activities="",
    )

    WeeklyLogEntry.objects.bulk_create([WeeklyLogEntry(weekly_log=log, day=d) for d, _ in DAYS])
    return redirect("student_log_edit", log_id=log.id)


@login_required
def student_log_edit(request, log_id):
    placement = _get_student_active_placement(request.user)
    if not placement:
        return render(request, "tracking/no_active_placement.html")

    log = get_object_or_404(WeeklyLog, id=log_id, placement=placement)

    if log.status == "approved_by_company":
        return HttpResponseForbidden("This log is already approved.")

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

            lines = []
            for entry in entries_qs:
                wa = (entry.work_assignment or "").strip()
                st = (entry.activities_steps or "").strip()
                if wa or st:
                    lines.append(f"{entry.get_day_display()}: {wa} | {st}")
            log.activities = "\n".join(lines)

            action = request.POST.get("action", "save")
            if action == "submit":
                log.submit()
            else:
                if log.status != "returned_for_edit":
                    log.status = "draft"
                log.save()

            for uploaded_file in form.cleaned_data.get("attachments") or []:
                WeeklyLogAttachment.objects.create(weekly_log=log, file=uploaded_file)

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

    attachment_names = []
    if getattr(log, "attachment", None):
        attachment_names.append(log.attachment.name)
    attachment_names.extend(log.attachments.values_list("file", flat=True))
    log.delete()

    for attachment_name in attachment_names:
        if attachment_name and default_storage.exists(attachment_name):
            default_storage.delete(attachment_name)

    return redirect("student_logs")

@login_required
def student_log_detail(request, log_id):
    placement = _get_student_active_placement(request.user)
    if not placement:
        return render(request, "tracking/no_active_placement.html")

    log = get_object_or_404(
        WeeklyLog.objects.prefetch_related("attachments"),
        id=log_id,
        placement=placement,
    )

    # ✅ Only approved logs should open here
    if log.status != "approved_by_company":
        return HttpResponseForbidden("This log is not approved yet. Open it using edit mode.")

    entries_qs = log.entries.all().order_by(DAY_ORDER)

    # Build same form + formset, but disable everything (view-only)
    form = WeeklyLogForm(instance=log)
    formset = WeeklyLogEntryFormSet(instance=log, queryset=entries_qs)

    for name, field in form.fields.items():
        field.disabled = True

    for f in formset.forms:
        for name, field in f.fields.items():
            field.disabled = True

    return render(request, "tracking/student_log_detail.html", {
        "placement": placement,
        "log": log,
        "form": form,
        "formset": formset,
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
    if not hasattr(request.user, "student_profile"):
        return HttpResponseForbidden("Students only.")

    visit = get_object_or_404(
        SiteVisit.objects.select_related("placement"),
        id=visit_id,
        placement__request__student__user=request.user
    )

    if visit.status != "completed":
        messages.error(request, "You can only acknowledge a completed site visit.")
        return redirect("student_site_visits")

    has_report = SiteVisitReport.objects.filter(site_visit=visit).exists()
    if not has_report:
        messages.error(request, "You can only acknowledge a visit that has a report.")
        return redirect("student_site_visits")

    if request.method == "POST":
        messages.success(request, "Acknowledged. Thank you.")
        return redirect("student_site_visits")

    return render(request, "tracking/student_ack_site_visit.html", {"visit": visit})


# -------------------------------------------------------------------
# STUDENT: EVALUATION FORM
# -------------------------------------------------------------------
@login_required
def student_evaluation_form(request):
    if not hasattr(request.user, "student_profile"):
        return HttpResponseForbidden("Students only.")

    student = request.user.student_profile
    placement = _get_student_active_placement(request.user) or _get_student_latest_placement(request.user)
    if not placement:
        return render(request, "tracking/no_active_placement.html")

    # ✅ Student program may be FK (Program model) or a string
    prog_obj = getattr(student, "program", None) or getattr(student, "course", None) or getattr(student, "programme", None)

    if prog_obj is None:
        student_program = ""
    else:
        # FK object? -> take name if available, else str()
        student_program = getattr(prog_obj, "name", None) or str(prog_obj)

    evaluation, _ = StudentEvaluation.objects.get_or_create(
        placement=placement,
        defaults={
            "student_user": request.user,
            "program": student_program,  # ✅ always string
            "internship_site": placement.company.name if placement.company else "",
            "status": "draft",
        }
    )

    # ✅ Keep program synced
    if student_program and evaluation.program != student_program:
        evaluation.program = student_program
        evaluation.save(update_fields=["program"])

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

            # ✅ Force program from student profile (string only)
            evaluation.program = student_program

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

    # ✅ Disable program input in UI
    if "program" in form.fields:
        form.fields["program"].disabled = True

    return render(request, "tracking/student_evaluation_form.html", {
        "placement": placement,
        "evaluation": evaluation,
        "form": form,
        "student_program": student_program,
    })


@login_required
def student_internship_report(request):
    if not hasattr(request.user, "student_profile"):
        return HttpResponseForbidden("Students only.")

    placement = _get_student_active_placement(request.user) or _get_student_latest_placement(request.user)
    if not placement:
        return render(request, "tracking/no_active_placement.html")

    report = StudentInternshipReport.objects.filter(
        placement=placement,
        student_user=request.user,
    ).first()

    if request.method == "POST":
        form = StudentInternshipReportForm(request.POST, request.FILES, instance=report)
        if form.is_valid():
            report = form.save(commit=False)
            report.placement = placement
            report.student_user = request.user
            report.status = "submitted"
            report.submitted_at = timezone.now()
            report.save()

            supervisor_user = getattr(getattr(placement, "university_supervisor", None), "user", None)
            if supervisor_user:
                student_name = getattr(request.user, "display_name", "") or request.user.get_username()
                notify(
                    supervisor_user,
                    title="Internship report submitted",
                    message=f"{student_name} submitted an internship report for review.",
                    level="info",
                    action_url=reverse("supervisor_students"),
                    action_text="View Students",
                )

            messages.success(request, "Internship report submitted to your university supervisor.")
            return redirect("student_dashboard")
    else:
        form = StudentInternshipReportForm(instance=report)

    return render(request, "tracking/student_internship_report_form.html", {
        "placement": placement,
        "report": report,
        "form": form,
    })


@login_required
def student_internship_report_download(request, report_id):
    report = get_object_or_404(
        StudentInternshipReport.objects.select_related(
            "placement",
            "placement__university_supervisor__user",
            "student_user",
        ),
        id=report_id,
    )

    is_owner = report.student_user_id == request.user.id
    supervisor_user = getattr(getattr(report.placement, "university_supervisor", None), "user", None)
    is_assigned_supervisor = supervisor_user and supervisor_user.id == request.user.id

    if not (is_owner or is_assigned_supervisor):
        return HttpResponseForbidden("You are not allowed to access this report.")

    if not report.report_file:
        raise Http404("Report file not found.")

    return FileResponse(
        report.report_file.open("rb"),
        as_attachment=True,
        filename=report.report_file.name.rsplit("/", 1)[-1],
    )
# -------------------------------------------------------------------
# STUDENT DASHBOARD
# -------------------------------------------------------------------
@login_required
def student_dashboard(request):
    if not hasattr(request.user, "student_profile"):
        return HttpResponseForbidden("Students only.")

    now = timezone.now()
    notification_keys = [
        "student:no_request",
        "student:request_submitted",
        "student:request_rejected",
        "student:recommendation_pending",
        "student:recommendation_not_ready",
        "student:recommendation_ready",
        "student:recommendation_processing",
        "student:approved_no_letter",
        "student:request_status",
        "student:logs_returned",
        "student:logs_pending",
        "student:site_visit_confirm",
        "student:site_visit_upcoming",
        "student:evaluation_due",
        "student:internship_report_due",
    ]
    active_notification_keys = set()

    def notify_hint(key, **kwargs):
        active_notification_keys.add(key)
        ensure_dashboard_notification(request.user, key=key, **kwargs)

    def finalize_notifications():
        for key in notification_keys:
            if key not in active_notification_keys:
                resolve_dashboard_notification(request.user, key)
        return get_notification_context(request.user)

    student = request.user.student_profile

    # ✅ Always fetch latest request (even if no placement yet)
    latest_req = (
        InternshipRequest.objects
        .filter(student=student)
        .order_by("-id")
        .first()
    )

    # ✅ Gate boolean computed in VIEW (Option B)
    # Acceptance upload allowed ONLY after recommendation letter is present AND approved
    can_upload_acceptance = bool(
        latest_req
        and latest_req.recommendation_letter
        and latest_req.recommendation_approved
    )

    placement = _get_student_active_placement(request.user)
    student_marks = _student_marks_context(placement)
    internship_report = None

    # =========================================================
    # CASE 1: No active placement yet (still show request stages)
    # =========================================================
    if not placement:

        # 0) No request at all
        if not latest_req:
            notify_hint("student:no_request",
                level="warning",
                title="No internship request found",
                message="Submit your internship request to begin the process.",
                action_text="Submit Request",
                action_url=reverse("submit_request"),
            )

        else:
            s = (latest_req.status or "").strip().lower()

            # 1) Under review / submitted
            if s in ["submitted", "under_review", "pending"]:
                notify_hint("student:request_submitted",
                    level="info",
                    title="Request submitted",
                    message="Your internship request is under review. You will be notified once approved or rejected.",
                    action_text="View Request",
                    action_url=reverse("student_request_status"),  # change if your url differs
                )

            # 2) Rejected
            elif s in ["rejected", "declined"]:
                rejection_note = (latest_req.review_notes or "").strip()
                rejection_message = "Your internship request was rejected. Please update your details and resubmit."
                if rejection_note:
                    rejection_message = f"{rejection_message} Coordinator comment: {rejection_note}"

                notify_hint("student:request_rejected",
                    level="danger",
                    title="Request rejected",
                    message=rejection_message,
                    action_text="Update & Resubmit",
                    action_url=reverse("my_request"),
                )

            # ✅ 3) Letter generated but awaiting coordinator approval
            # (Matches coordinator view: status="recommendation_pending")
            elif s == "recommendation_pending":
                if latest_req.recommendation_letter and not latest_req.recommendation_approved:
                    notify_hint("student:recommendation_pending",
                        level="warning",
                        title="Recommendation letter pending approval",
                        message="Your recommendation letter has been generated and is awaiting coordinator approval.",
                        action_text="Open Recommendation",
                        action_url=reverse("recommendation_letter_page"),
                    )
                else:
                    notify_hint("student:recommendation_not_ready",
                        level="warning",
                        title="Recommendation letter not ready",
                        message="Your recommendation letter is not available yet. Please check again later.",
                        action_text="Refresh",
                        action_url=reverse("student_dashboard"),
                    )

            # ✅ 4) Approved & issued to student (matches: status="recommended")
            elif s == "recommended":
                if latest_req.recommendation_letter and latest_req.recommendation_approved:
                    notify_hint("student:recommendation_ready",
                        level="success",
                        title="Recommendation letter ready",
                        message="Your recommendation letter is approved and ready for download.",
                        action_text="Download Letter",
                        action_url=reverse("recommendation_letter_page"),
                    )
                else:
                    notify_hint("student:recommendation_processing",
                        level="info",
                        title="Recommendation letter processing",
                        message="Your recommendation letter is being prepared. Please check again shortly.",
                        action_text="Refresh",
                        action_url=reverse("student_dashboard"),
                    )

            # 5) Coordinator approved request but hasn’t generated letter yet
            elif s in ["approved", "accepted"]:
                notify_hint("student:approved_no_letter",
                    level="warning",
                    title="Recommendation letter not generated yet",
                    message="Your request was approved, but the recommendation letter is not yet generated. Please check again later.",
                    action_text="Refresh",
                    action_url=reverse("student_dashboard"),
                )

            # 6) Any other status fallback
            else:
                notify_hint("student:request_status",
                    level="info",
                    title="Request status update",
                    message=f"Your internship request status is: {latest_req.get_status_display if hasattr(latest_req,'get_status_display') else latest_req.status}.",
                    action_text="Refresh",
                    action_url=reverse("student_dashboard"),
                )

        notification_context = finalize_notifications()

        return render(request, "dashboards/student_dashboard.html", {
            "placement": None,
            "latest_req": latest_req,
            "can_upload_acceptance": can_upload_acceptance,  # ✅ ADD THIS
            "student_marks": student_marks,
            **notification_context,
            "site_visit_next": None,
            "site_visit_last_completed": None,
            "pending_company_logs": 0,
            "returned_logs": 0,
            "approved_logs": 0,
            "internship_report": internship_report,
        })

    # =========================================================
    # CASE 2: Placement exists (your existing logic unchanged)
    # =========================================================
    student_log_qs = WeeklyLog.objects.filter(placement=placement)

    pending_company = student_log_qs.filter(status="submitted").count()
    returned_for_edit = student_log_qs.filter(status="returned_for_edit").count()
    approved_by_company = student_log_qs.filter(status="approved_by_company").count()
    internship_report = StudentInternshipReport.objects.filter(
        placement=placement,
        student_user=request.user,
    ).first()

    if returned_for_edit:
        notify_hint("student:logs_returned",
            level="danger",
            title="Weekly log returned",
            message=f"{returned_for_edit} log(s) were returned for edit. Please correct and resubmit.",
            action_text="Open Logs",
            action_url=reverse("student_logs"),
        )

    if pending_company:
        notify_hint("student:logs_pending",
            level="info",
            title="Logs awaiting approval",
            message=f"{pending_company} submitted log(s) are waiting for your industry supervisor to approve.",
            action_text="View Logs",
            action_url=reverse("student_logs"),
        )

    site_visits_qs = (
        SiteVisit.objects
        .filter(placement=placement)
        .order_by("scheduled_at")
    )

    site_visit_next = (
        site_visits_qs
        .filter(status__in=["scheduled", "confirmed"], scheduled_at__gte=now)
        .order_by("scheduled_at")
        .first()
    )

    if site_visit_next and site_visit_next.status == "scheduled":
        notify_hint("student:site_visit_confirm",
            level="warning",
            title="Site visit needs confirmation",
            message=f"A site visit is scheduled for {site_visit_next.scheduled_at.strftime('%d %b %Y %H:%M')}. Please confirm attendance.",
            action_text="Confirm Visit",
            action_url=reverse("student_confirm_site_visit", args=[site_visit_next.id]),
        )

    if site_visit_next and site_visit_next.status == "confirmed":
        notify_hint("student:site_visit_upcoming",
            level="info",
            title="Upcoming site visit",
            message=f"You have a confirmed site visit on {site_visit_next.scheduled_at.strftime('%d %b %Y %H:%M')}. Be ready.",
            action_text="View Visits",
            action_url=reverse("student_site_visits"),
        )

    site_visit_last_completed = (
        site_visits_qs
        .filter(status="completed")
        .order_by("-actual_at", "-scheduled_at")
        .first()
    )

    if placement.status == "active":
        if not internship_report:
            notify_hint("student:internship_report_due",
                level="secondary",
                title="Internship report",
                message="Upload and submit your internship report to your university supervisor.",
                action_text="Upload Report",
                action_url=reverse("student_internship_report"),
            )

        ev = StudentEvaluation.objects.filter(
            placement=placement,
            student_user=request.user
        ).first()

        if not ev:
            notify_hint("student:evaluation_due",
                level="secondary",
                title="Student evaluation",
                message="Remember to fill the student evaluation form at the end of internship.",
                action_text="Open Form",
                action_url=reverse("student_evaluation_form"),
            )

    notification_context = finalize_notifications()

    return render(request, "dashboards/student_dashboard.html", {
        "placement": placement,
        "latest_req": latest_req,
        "can_upload_acceptance": can_upload_acceptance,  # ✅ ADD THIS
        "student_marks": student_marks,
        **notification_context,
        "site_visit_next": site_visit_next,
        "site_visit_last_completed": site_visit_last_completed,
        "pending_company_logs": pending_company,
        "returned_logs": returned_for_edit,
        "approved_logs": approved_by_company,
        "internship_report": internship_report,
    })

@login_required
@xframe_options_sameorigin
def view_recommendation_letter(request, request_id):
    req = InternshipRequest.objects.filter(id=request_id, student=request.user.student_profile).first()
    if not req or not req.recommendation_letter:
        raise Http404("Letter not found")

    # Serve inline (preview) - NOT attachment
    return FileResponse(
        req.recommendation_letter.open("rb"),
        content_type="application/pdf",
        as_attachment=False,  # ✅ inline preview
        filename=f"recommendation_{req.id}.pdf",
    )
