from django.db import models
from django.utils import timezone
from companies.models import Company, CompanyContact

class InternshipPeriod(models.Model):
    name = models.CharField(max_length=120)  # e.g. "May–Aug 2026"
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=False)
    

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
        ("recommended", "Recommendation issued"),
        ("acceptance_uploaded", "Acceptance uploaded"),
        ("acceptance_verified", "Acceptance verified"),
        ("rejected", "Rejected"),
        ("returned_for_acceptance", "Returned: Upload Acceptance Letter"),

    ]

    student = models.ForeignKey("accounts.StudentProfile", on_delete=models.CASCADE, related_name="requests")
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

    reviewed_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_requests")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    class Meta:
        unique_together = [("student", "period")]  # one request per period

    def submit(self):
        self.status = "submitted"
        self.submitted_at = timezone.now()
        self.save()

    def __str__(self):
        return f"{self.student.reg_no} - {self.period.name} ({self.status})"
    

        # Coordinator issues recommendation letter
    recommendation_letter = models.FileField(
        upload_to="requests/recommendation_letters/", null=True, blank=True
    )
    recommendation_issued_at = models.DateTimeField(null=True, blank=True)

    # Student uploads acceptance letter
    acceptance_letter = models.FileField(
        upload_to="requests/acceptance_letters/", null=True, blank=True
    )
    acceptance_uploaded_at = models.DateTimeField(null=True, blank=True)

    # Coordinator verifies acceptance
    acceptance_verified = models.BooleanField(default=False)
    acceptance_verified_at = models.DateTimeField(null=True, blank=True)




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




