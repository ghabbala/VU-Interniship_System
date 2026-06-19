# tracking/views/common.py
import datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.db.models.functions import Coalesce
from django.http import HttpResponseForbidden
from django.urls import reverse
from django.utils import timezone


# -----------------------------
# ROLE HELPERS
# -----------------------------
def is_university_supervisor(user):
    return user.is_authenticated and (user.is_superuser or user.has_perm("accounts.role_university_supervisor"))

def is_industry_supervisor(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if not user.has_perm("accounts.role_industry_supervisor"):
        return False
    profile = getattr(user, "industry_profile", None)
    if profile and not profile.has_current_placement_access():
        user.is_active = False
        user.save(update_fields=["is_active"])
        return False
    return True

def is_coordinator(user):
    return user.is_authenticated and (user.is_superuser or user.has_perm("accounts.role_coordinator"))


def _get_staff_profile(user):
    # correct related_name="staff_profile"
    return getattr(user, "staff_profile", None)


# -----------------------------
# PLACEMENT HELPERS
# -----------------------------
def _get_student_active_placement(user):
    from placements.models import Placement
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
    from placements.models import Placement
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



def week_bounds(today):
    start = today - datetime.timedelta(days=today.weekday())
    end = start + datetime.timedelta(days=6)
    return start, end



# -----------------------------
# RESULTS REPORT: latest report
# -----------------------------
def _get_latest_report(user):
    from tracking.models import SupervisorResultsReport
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


# -----------------------------
# WEEKDAY CONSTANTS
# -----------------------------
DAYS = [("mon", "Monday"), ("tue", "Tuesday"), ("wed", "Wednesday"), ("thu", "Thursday"), ("fri", "Friday")]

DAY_ORDER = Case(
    When(day="mon", then=0),
    When(day="tue", then=1),
    When(day="wed", then=2),
    When(day="thu", then=3),
    When(day="fri", then=4),
    output_field=IntegerField(),
)


# -----------------------------
# SMALL HELPERS
# -----------------------------
def week_bounds(today):
    start = today - datetime.timedelta(days=today.weekday())
    end = start + datetime.timedelta(days=6)
    return start, end

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
    max_marks = 65
    return rows, total, max_marks


def _extract_academic_rows_and_total(academic_eval):
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


# -----------------------------
# RESULTS REPORT ROW BUILDER
# -----------------------------
def build_results_rows(supervisor_user, staff):
    from placements.models import Placement
    from tracking.models import (
        AcademicEvaluation,
        IndustryEvaluation,
        SiteVisit,
        StudentEvaluation,
        StudentInternshipReport,
        WeeklyLog,
    )

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
    log_counts = {
        row["placement_id"]: row
        for row in WeeklyLog.objects.filter(placement__in=placements)
        .values("placement_id")
        .annotate(
            total_logs=Count("id"),
            approved_logs=Count("id", filter=Q(status="approved_by_company")),
            submitted_logs=Count("id", filter=Q(status="submitted")),
            returned_logs=Count("id", filter=Q(status="returned_for_edit")),
        )
    }
    visit_counts = {
        row["placement_id"]: row
        for row in SiteVisit.objects.filter(placement__in=placements)
        .values("placement_id")
        .annotate(
            total_visits=Count("id"),
            completed_visits=Count("id", filter=Q(status="completed")),
        )
    }
    student_eval_map = {
        e.placement_id: e
        for e in StudentEvaluation.objects.filter(placement__in=placements, status="submitted")
    }
    student_report_map = {
        r.placement_id: r
        for r in StudentInternshipReport.objects.filter(placement__in=placements, status="submitted")
    }

    rows = []
    for p in placements:
        ind = ind_map.get(p.id)
        ac = ac_map.get(p.id)
        logs = log_counts.get(p.id, {})
        visits = visit_counts.get(p.id, {})

        ind100 = float(ind.score_out_of_100) if ind else None
        ac100 = float(ac.score_out_of_100) if ac else None
        avg100 = (ind100 + ac100) / 2.0 if (ind100 is not None and ac100 is not None) else None
        required_weeks = max(((p.end_date - p.start_date).days // 7) + 1, 1) if p.start_date and p.end_date else 0
        approved_logs = int(logs.get("approved_logs") or 0)
        log_progress = round(min((approved_logs / required_weeks) * 100, 100), 0) if required_weeks else 0
        missing_items = []
        if ind100 is None:
            missing_items.append("industry marks")
        if ac100 is None:
            missing_items.append("academic marks")
        if approved_logs < required_weeks:
            missing_items.append("approved weekly logs")
        if not int(visits.get("completed_visits") or 0):
            missing_items.append("site visit")
        if p.end_date and p.end_date <= timezone.localdate() and p.id not in student_eval_map:
            missing_items.append("student feedback")
        if p.id not in student_report_map:
            missing_items.append("internship report")

        rows.append({
            "placement_id": p.id,
            "reg_no": p.request.student.reg_no,
            "name": p.request.student.user.display_name,
            "company": p.company.name,
            "placement_status": p.get_status_display(),
            "start_date": p.start_date.isoformat() if p.start_date else "",
            "end_date": p.end_date.isoformat() if p.end_date else "",
            "days_remaining": max((p.end_date - timezone.localdate()).days, 0) if p.end_date else None,
            "required_weeks": required_weeks,
            "total_logs": int(logs.get("total_logs") or 0),
            "approved_logs": approved_logs,
            "submitted_logs": int(logs.get("submitted_logs") or 0),
            "returned_logs": int(logs.get("returned_logs") or 0),
            "log_progress": log_progress,
            "total_visits": int(visits.get("total_visits") or 0),
            "completed_visits": int(visits.get("completed_visits") or 0),
            "student_feedback_submitted": p.id in student_eval_map,
            "student_report_submitted": p.id in student_report_map,
            "missing_items": missing_items,
            "industry_100": ind100,
            "academic_100": ac100,
            "average_100": avg100,
        })

    return rows


# -----------------------------
# NOTIFICATIONS
# -----------------------------
def notify(user, title, message, level="info", action_url="", action_text="Open"):
    from tracking.models import Notification
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


def get_notification_context(user, limit=8):
    from tracking.models import Notification
    qs = Notification.objects.filter(user=user, is_read=False).order_by("-created_at")
    return {
        "notifications": list(qs[:limit]),
        "unread_notifications": qs.count(),
    }


def ensure_dashboard_notification(user, *, key, title, message, level="info", action_url="", action_text="Open"):
    from tracking.models import Notification

    notification = (
        Notification.objects
        .filter(user=user, key=key)
        .order_by("-created_at")
        .first()
    )
    if notification:
        fields = []
        updates = {
            "title": title,
            "message": message,
            "level": level,
            "action_url": action_url,
            "action_text": action_text,
        }
        for field, value in updates.items():
            if getattr(notification, field) != value:
                setattr(notification, field, value)
                fields.append(field)
        if fields:
            notification.save(update_fields=fields)
        return notification

    return Notification.objects.create(
        user=user,
        key=key,
        title=title,
        message=message,
        level=level,
        action_url=action_url,
        action_text=action_text,
        is_read=False,
    )


def resolve_dashboard_notification(user, key):
    from tracking.models import Notification
    Notification.objects.filter(user=user, key=key, is_read=False).update(is_read=True)

def notify_coordinators(title, message, level="info", action_url=None, action_text="Open"):
    from tracking.models import Notification

    User = get_user_model()

    qs = User.objects.filter(is_active=True).filter(is_superuser=True) | \
         User.objects.filter(is_active=True, user_permissions__codename="role_coordinator",
                             user_permissions__content_type__app_label="accounts") | \
         User.objects.filter(is_active=True, groups__permissions__codename="role_coordinator",
                             groups__permissions__content_type__app_label="accounts")

    qs = qs.distinct()

    Notification.objects.bulk_create([
        Notification(
            user=u,
            title=title,
            message=message,
            level=level,
            action_url=action_url or "",
            action_text=action_text,
            is_read=False,
        )
        for u in qs
    ])

def _ensure_notification(user, *, title, message, level="info", action_url="", action_text="Open"):
    from tracking.models import Notification
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
