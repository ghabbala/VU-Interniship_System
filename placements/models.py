from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from companies.models import Company, CompanyContact
from django.conf import settings
from companies.models import Company


class InternshipPeriod(models.Model):
    name = models.CharField(max_length=120)  # e.g. "May–Aug 2026"
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_active", "-start_date"]

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "End date cannot be before start date."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
        if self.is_active:
            InternshipPeriod.objects.exclude(pk=self.pk).filter(is_active=True).update(is_active=False)

    @property
    def duration_days(self):
        if not self.start_date or not self.end_date:
            return 0
        return (self.end_date - self.start_date).days + 1

    @property
    def duration_weeks(self):
        if not self.duration_days:
            return 0
        return round(self.duration_days / 7, 1)

    @property
    def days_remaining(self):
        if not self.end_date:
            return 0
        return max((self.end_date - timezone.localdate()).days, 0)
    

    def __str__(self):
        return self.name


class RecommendationLetterSettings(models.Model):
    name = models.CharField(max_length=120, default="Default recommendation letter settings")
    stamp_image = models.ImageField(upload_to="recommendation_letter/stamps/", blank=True, null=True)
    signature_image = models.ImageField(upload_to="recommendation_letter/signatures/", blank=True, null=True)
    signatory_name = models.CharField(max_length=160, blank=True)
    signatory_title = models.CharField(max_length=160, blank=True, default="Dean")
    signatory_email = models.EmailField(blank=True)
    signatory_phone = models.CharField(max_length=60, blank=True)
    footer_address = models.CharField(
        max_length=255,
        blank=True,
        default="Victoria Tower, Plot No. 1-13 Jinja Road P.O. Box 30866 Kampala, Uganda",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_recommendation_letter_settings",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Recommendation letter setting"
        verbose_name_plural = "Recommendation letter settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def current(cls):
        settings_obj, _ = cls.objects.get_or_create(pk=1)
        return settings_obj

    def __str__(self):
        return self.name




class InternshipRequest(models.Model):
    SOURCE = [
        ("student_selected", "Student selected from list"),
        ("student_proposed", "Student proposed new company"),
        ("university_assigned", "University assigned"),
    ]

    STATUS = [
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("under_review", "Under review"),

        # ✅ NEW: generated but not yet approved/released to student
        ("recommendation_pending", "Recommendation pending approval"),

        ("recommended", "Recommendation issued"),
        ("acceptance_uploaded", "Acceptance uploaded"),
        ("acceptance_verified", "Acceptance verified"),
        ("rejected", "Rejected"),
        ("returned_for_acceptance", "Returned: Upload Acceptance Letter"),
    ]

    student = models.ForeignKey(
        "accounts.StudentProfile",
        on_delete=models.CASCADE,
        related_name="requests"
    )
    period = models.ForeignKey(InternshipPeriod, on_delete=models.PROTECT)
    request_source = models.CharField(max_length=30, choices=SOURCE)

    preferred_company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.SET_NULL)

    coordinator_comment = models.TextField(blank=True)
    coordinator_commented_at = models.DateTimeField(null=True, blank=True)

    # proposed company details
    proposed_company_name = models.CharField(max_length=200, blank=True)
    proposed_company_district = models.CharField(max_length=120, blank=True)
    proposed_company_address = models.CharField(max_length=255, blank=True)
    proposed_company_contact = models.CharField(max_length=200, blank=True)

    preferred_field = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    # attachments
    cv = models.FileField(upload_to="requests/cv/", blank=True, null=True)
    request_letter = models.FileField(upload_to="requests/letters/", blank=True, null=True)

    status = models.CharField(max_length=40, choices=STATUS, default="draft")
    submitted_at = models.DateTimeField(null=True, blank=True)

    reviewed_by = models.ForeignKey(
        "accounts.User",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_requests"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    # ==========================
    # Recommendation letter
    # ==========================
    recommendation_letter = models.FileField(
        upload_to="requests/recommendation_letters/",
        null=True, blank=True
    )
    recommendation_issued_at = models.DateTimeField(null=True, blank=True)

    # ✅ NEW: approval gate (student can only access when True)
    recommendation_approved = models.BooleanField(default=False)
    recommendation_approved_at = models.DateTimeField(null=True, blank=True)
    recommendation_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_recommendation_requests"
    )

    # ==========================
    # Acceptance letter
    # ==========================
    acceptance_letter = models.FileField(
        upload_to="requests/acceptance_letters/",
        null=True, blank=True
    )
    acceptance_uploaded_at = models.DateTimeField(null=True, blank=True)

    # Coordinator verifies acceptance
    acceptance_verified = models.BooleanField(default=False)
    acceptance_verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("student", "period")]  # one request per period

    def submit(self):
        self.status = "submitted"
        self.submitted_at = timezone.now()
        self.save(update_fields=["status", "submitted_at"])

    def __str__(self):
        return f"{self.student.reg_no} - {self.period.name} ({self.status})"




class Placement(models.Model):
    STATUS = [
        ("pending_student_ack", "Pending student acknowledgement"),
        ("active", "Active"),
        ("on_hold", "On hold"),
        ("completed", "Completed"),
        ("terminated", "Terminated"),
    ]

    request = models.OneToOneField(InternshipRequest, on_delete=models.PROTECT, related_name="placement")
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    industry_supervisor = models.ForeignKey(CompanyContact, null=True, blank=True, on_delete=models.SET_NULL)
    university_supervisor = models.ForeignKey("accounts.StaffProfile", null=True, blank=True, on_delete=models.SET_NULL)
    

    start_date = models.DateField()
    end_date = models.DateField()

    # attachment: placement letter generated/uploaded by coordinator
    placement_letter = models.FileField(upload_to="placements/letters/", blank=True, null=True)

    status = models.CharField(max_length=30, choices=STATUS, default="pending_student_ack")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.request.student.reg_no} @ {self.company.name}"

    @property
    def duration_days(self):
        if not self.start_date or not self.end_date:
            return 0
        return (self.end_date - self.start_date).days + 1

    @property
    def duration_weeks(self):
        if not self.duration_days:
            return 0
        return round(self.duration_days / 7, 1)




