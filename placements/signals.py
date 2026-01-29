from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db import transaction

from .models import InternshipRequest
from tracking.utils.recommendation_letter import generate_recommendation_letter_pdf

User = get_user_model()


def _get_faculty_name(req) -> str:
    """
    If you added StudentProfile.program -> Program -> Department -> Faculty
    """
    try:
        prog = getattr(req.student, "program", None)
        if prog and prog.department and prog.department.faculty:
            return prog.department.faculty.name
    except Exception:
        pass
    return ""


@receiver(pre_save, sender=InternshipRequest)
def flag_submitted_transition(sender, instance: InternshipRequest, **kwargs):
    """
    Mark instance._became_submitted = True only when status changes to submitted.
    """
    instance._became_submitted = False

    if not instance.pk:
        # New object: if it is being created as submitted
        if instance.status == "submitted":
            instance._became_submitted = True
        return

    old_status = InternshipRequest.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
    if old_status != "submitted" and instance.status == "submitted":
        instance._became_submitted = True


@receiver(post_save, sender=InternshipRequest)
def auto_generate_recommendation(sender, instance: InternshipRequest, created, **kwargs):
    """
    Generate PDF only once when request becomes submitted.
    Avoid recursion by updating via queryset.update().
    """
    # Only run when status just changed to submitted
    if not getattr(instance, "_became_submitted", False):
        return

    # If already generated, skip
    if instance.recommendation_letter:
        return

    coordinator = User.objects.filter(groups__name="Coordinator").order_by("id").first()
    if not coordinator:
        return

    faculty_name = _get_faculty_name(instance)

    def _do_generate():
        filename, content = generate_recommendation_letter_pdf(instance, coordinator)

        # Save file without triggering another status-transition
        instance.recommendation_letter.save(filename, content, save=False)

        # IMPORTANT: use update() to avoid signal loops
        InternshipRequest.objects.filter(pk=instance.pk).update(
            recommendation_letter=instance.recommendation_letter.name,
            recommendation_issued_at=timezone.now(),
            status="recommended",  # auto-issue
        )

    # Generate only after the DB transaction is committed
    transaction.on_commit(_do_generate)
