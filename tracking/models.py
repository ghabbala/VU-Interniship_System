from django.db import models
from django.utils import timezone
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator

from placements.models import Placement
    
from django.db.models import Case, When, Value, IntegerField

class WeeklyLog(models.Model):
    STATUS = [
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("returned_for_edit", "Returned for edit"),
        ("approved_by_company", "Approved by company"),
    ]

    placement = models.ForeignKey("placements.Placement", on_delete=models.CASCADE, related_name="weekly_logs")

    week_no = models.PositiveIntegerField()  # 1,2,3...
    from_date = models.DateField()
    to_date = models.DateField()

    activities = models.TextField()
    challenges = models.TextField(blank=True)
    lessons = models.TextField(blank=True)

    attachment = models.FileField(upload_to="tracking/weekly_logs/", null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS, default="draft")

    submitted_at = models.DateTimeField(null=True, blank=True)

    company_action_by = models.ForeignKey(
        "accounts.User",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="company_log_actions",
    )
    company_action_at = models.DateTimeField(null=True, blank=True)
    return_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("placement", "week_no")]
        ordering = ["-from_date"]

    def submit(self):
        self.status = "submitted"
        self.submitted_at = timezone.now()
        self.save()

    def approve(self, user):
        self.status = "approved_by_company"
        self.company_action_by = user
        self.company_action_at = timezone.now()
        self.return_reason = ""
        self.save()

    def return_for_edit(self, user, reason: str):
        self.status = "returned_for_edit"
        self.company_action_by = user
        self.company_action_at = timezone.now()
        self.return_reason = reason or "Please revise and resubmit."
        self.save()

    def __str__(self):
        return f"{self.placement} - Week {self.week_no} ({self.status})"


class WeeklyLogAttachment(models.Model):
    weekly_log = models.ForeignKey(
        WeeklyLog,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file = models.FileField(upload_to="tracking/weekly_logs/attachments/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at", "id"]

    def __str__(self):
        return f"Attachment for {self.weekly_log}"


class WeeklyLogEntry(models.Model):
    DAYS = [
        ("mon", "Monday"),
        ("tue", "Tuesday"),
        ("wed", "Wednesday"),
        ("thu", "Thursday"),
        ("fri", "Friday"),
    ]

    weekly_log = models.ForeignKey(
        "tracking.WeeklyLog",
        on_delete=models.CASCADE,
        related_name="entries",
    )
    day = models.CharField(max_length=3, choices=DAYS)

    work_assignment = models.TextField(blank=True)
    activities_steps = models.TextField(blank=True)

    class Meta:
        unique_together = [("weekly_log", "day")]

    @staticmethod
    def day_order_case():
        return Case(
            When(day="mon", then=Value(1)),
            When(day="tue", then=Value(2)),
            When(day="wed", then=Value(3)),
            When(day="thu", then=Value(4)),
            When(day="fri", then=Value(5)),
            default=Value(99),
            output_field=IntegerField(),
        )

    def __str__(self):
        return f"{self.get_day_display()} — Week {self.weekly_log.week_no}"
    

class SiteVisit(models.Model):
    VISIT_TYPE = [
        ("physical", "Physical"),
        ("zoom", "Virtual (Zoom)"),
        ("gmeet", "Virtual (Google Meet)"),
        ("other", "Virtual (Other)"),
    ]

    STATUS = [
        ("scheduled", "Scheduled"),
        ("confirmed", "Confirmed"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    placement = models.ForeignKey("placements.Placement", on_delete=models.CASCADE, related_name="site_visits")
    supervisor = models.ForeignKey("accounts.StaffProfile", on_delete=models.CASCADE, related_name="site_visits")

    visit_type = models.CharField(max_length=12, choices=VISIT_TYPE)
    meeting_link = models.URLField(blank=True)  # required for zoom/gmeet/other
    scheduled_at = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField(default=60)

    status = models.CharField(max_length=12, choices=STATUS, default="scheduled")

    # optional participants / context
    agenda = models.TextField(blank=True)

    # what actually happened
    actual_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-scheduled_at"]

    def __str__(self):
        return f"{self.placement} — {self.get_visit_type_display()} ({self.get_status_display()})"

    @property
    def is_virtual(self):
        return self.visit_type in ["zoom", "gmeet", "other"]


class SiteVisitReport(models.Model):
    ASSESSMENT = [
        ("satisfactory", "Satisfactory"),
        ("needs_improvement", "Needs improvement"),
    ]

    site_visit = models.OneToOneField(SiteVisit, on_delete=models.CASCADE, related_name="report")

    summary = models.TextField()
    progress = models.TextField(blank=True)
    challenges = models.TextField(blank=True)
    recommendations = models.TextField(blank=True)

    student_attended = models.BooleanField(default=True)
    industry_supervisor_present = models.BooleanField(default=False)

    assessment = models.CharField(max_length=20, choices=ASSESSMENT, default="satisfactory")

    attachment = models.FileField(upload_to="site_visits/", blank=True)  # photo/signed form/screenshot
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Report — {self.site_visit}"


class SiteVisitAcknowledgement(models.Model):
    site_visit = models.OneToOneField(SiteVisit, on_delete=models.CASCADE, related_name="ack")
    student = models.ForeignKey("accounts.StudentProfile", on_delete=models.CASCADE)  # adjust to your student profile model
    acknowledged_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Acknowledged — {self.site_visit}"





class IndustryEvaluation(models.Model):
    STATUS = [
        ("draft", "Draft"),
        ("submitted", "Submitted"),
    ]

    placement = models.OneToOneField(
        "placements.Placement",
        on_delete=models.CASCADE,
        related_name="industry_evaluation",
    )

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.PROTECT,
        related_name="industry_evaluations",
    )

    supervisor_user = models.ForeignKey(
        "accounts.User",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="industry_evaluations",
    )

    # ---- Ratings (1–5) ----
    def _rating_field():
        return models.PositiveSmallIntegerField(
            validators=[MinValueValidator(1), MaxValueValidator(5)],
            null=True, blank=True
        )

    basic_work_expectations = _rating_field()
    knowledge_and_learning = _rating_field()
    ethical_awareness = _rating_field()
    interpersonal_relations = _rating_field()
    communication_skills = _rating_field()
    attendance = _rating_field()
    punctuality = _rating_field()
    flexibility = _rating_field()
    dependability = _rating_field()
    culture_fit = _rating_field()
    dress_code = _rating_field()
    behaviour = _rating_field()
    work_productivity = _rating_field()

    # ---- Comments per section (optional) ----
    basic_work_expectations_comment = models.TextField(blank=True)
    knowledge_and_learning_comment = models.TextField(blank=True)
    ethical_awareness_comment = models.TextField(blank=True)
    interpersonal_relations_comment = models.TextField(blank=True)
    communication_skills_comment = models.TextField(blank=True)
    attendance_comment = models.TextField(blank=True)
    punctuality_comment = models.TextField(blank=True)
    flexibility_comment = models.TextField(blank=True)
    dependability_comment = models.TextField(blank=True)
    culture_fit_comment = models.TextField(blank=True)
    dress_code_comment = models.TextField(blank=True)
    behaviour_comment = models.TextField(blank=True)
    work_productivity_comment = models.TextField(blank=True)

    recommend_employment = models.BooleanField(null=True, blank=True)  # YES/NO
    recommend_comment = models.TextField(blank=True)

    other_comments = models.TextField(blank=True)

    supervisor_name = models.CharField(max_length=120, blank=True)
    supervisor_signature = models.CharField(max_length=120, blank=True)  # typed name/signature

    status = models.CharField(max_length=20, choices=STATUS, default="draft")
    submitted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def submit(self, user=None):
        self.status = "submitted"
        self.submitted_at = timezone.now()
        if user:
            self.supervisor_user = user
        self.save()

    def __str__(self):
        return f"Evaluation: {self.placement} ({self.status})"


    SCORE_FIELDS = [
        "basic_work_expectations",
        "knowledge_and_learning",
        "ethical_awareness",
        "interpersonal_relations",
        "communication_skills",
        "attendance",
        "punctuality",
        "flexibility",
        "dependability",
        "culture_fit",
        "dress_code",
        "behaviour",
        "work_productivity",
    ]

    @property
    def total_marks(self) -> int:
        total = 0
        for f in self.SCORE_FIELDS:
            v = getattr(self, f, 0) or 0
            total += int(v)
        return total

    @property
    def max_marks(self) -> int:
        return len(self.SCORE_FIELDS) * 5  # 65

    @property
    def score_out_of_100(self) -> float:
        if self.max_marks == 0:
            return 0.0
        return (self.total_marks / self.max_marks) * 100

    @property
    def score_out_of_10(self) -> float:
        if self.max_marks == 0:
            return 0.0
        return (self.total_marks / self.max_marks) * 10
    
    
class AcademicEvaluation(models.Model):
    STATUS_CHOICES = [("draft", "Draft"), ("submitted", "Submitted")]

    placement = models.OneToOneField("placements.Placement", on_delete=models.CASCADE, related_name="academic_evaluation")

    # who submitted it
    supervisor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="academic_evaluations"
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    submitted_at = models.DateTimeField(null=True, blank=True)

    # Scores (1-5)
    understanding_of_internship = models.PositiveSmallIntegerField(default=0)
    support_framework = models.PositiveSmallIntegerField(default=0)
    culture_fit = models.PositiveSmallIntegerField(default=0)
    work_output = models.PositiveSmallIntegerField(default=0)
    general_presentation = models.PositiveSmallIntegerField(default=0)

    # Comments
    understanding_of_internship_comment = models.TextField(blank=True, default="")
    support_framework_comment = models.TextField(blank=True, default="")
    culture_fit_comment = models.TextField(blank=True, default="")
    work_output_comment = models.TextField(blank=True, default="")
    general_presentation_comment = models.TextField(blank=True, default="")

    # optional recommendation (text)
    recommendation = models.TextField(blank=True, default="")

    supervisor_name = models.CharField(max_length=255, blank=True, default="")
    supervisor_signature = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    SCORE_FIELDS = [
        "understanding_of_internship",
        "support_framework",
        "culture_fit",
        "work_output",
        "general_presentation",
    ]

    @property
    def total_marks(self) -> int:
        return sum(int(getattr(self, f, 0) or 0) for f in self.SCORE_FIELDS)

    @property
    def max_marks(self) -> int:
        return len(self.SCORE_FIELDS) * 5  # 25

    @property
    def score_out_of_100(self) -> float:
        return (self.total_marks / self.max_marks) * 100 if self.max_marks else 0.0

    @property
    def score_out_of_10(self) -> float:
        return (self.total_marks / self.max_marks) * 10 if self.max_marks else 0.0

    def submit(self, user=None):
        self.status = "submitted"
        self.submitted_at = timezone.now()
        if user:
            self.supervisor_user = user
        self.save()



class SupervisorResultsReport(models.Model):
    """
    University Supervisor -> Coordinator results report lifecycle.

    draft         : editable, not yet sent
    submitted     : sent, under review (locked for supervisor)
    needs_changes : coordinator requested edits (editable again)
    resubmitted   : supervisor edited + sent again (under review)
    approved      : coordinator accepted (locked)
    rejected      : optional final rejection (locked unless you reopen)
    """
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("needs_changes", "Needs Changes"),
        ("resubmitted", "Resubmitted"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    )

    supervisor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="results_reports",
    )

    # Snapshot of what was reported at that time (NOT live recalculation)
    rows = models.JSONField(default=list, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")

    # Revision control / audit
    revision = models.PositiveIntegerField(default=1)

    # Coordinator feedback (optional but very useful for update workflow)
    coordinator_comment = models.TextField(blank=True, default="")

    submitted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # -------------------------
    # Workflow helpers
    # -------------------------
    def can_edit(self) -> bool:
        """
        Supervisor can edit only if report is draft or needs_changes.
        """
        return self.status in ("draft", "needs_changes")

    def mark_needs_changes(self, comment: str = ""):
        """
        Coordinator uses this to reopen the report for supervisor edits.
        """
        self.status = "needs_changes"
        if comment is not None:
            self.coordinator_comment = comment
        self.save(update_fields=["status", "coordinator_comment", "updated_at"])

    def approve(self):
        """
        Coordinator approves. Locks supervisor edits.
        """
        self.status = "approved"
        self.save(update_fields=["status", "updated_at"])

    def reject(self, comment: str = ""):
        """
        Optional coordinator rejection.
        """
        self.status = "rejected"
        if comment is not None:
            self.coordinator_comment = comment
        self.save(update_fields=["status", "coordinator_comment", "updated_at"])

    def submit(self):
        """
        Supervisor submits or resubmits.
        - draft -> submitted
        - needs_changes -> resubmitted (+ revision)
        """
        now = timezone.now()

        if self.status == "draft":
            self.status = "submitted"
            self.submitted_at = now
            self.save(update_fields=["status", "submitted_at", "updated_at"])
            return

        if self.status == "needs_changes":
            self.status = "resubmitted"
            self.revision += 1
            self.submitted_at = now
            self.save(update_fields=["status", "revision", "submitted_at", "updated_at"])
            return

        # Any other status shouldn't be submitted again unless coordinator reopens it.
        # (Don't silently change state; raise to catch bugs)
        raise ValueError(f"Cannot submit report in status '{self.status}'. Reopen it first.")


class IndustrySupervisorResultsReport(models.Model):
    """
    Industry Supervisor -> University Supervisor report lifecycle.

    The report is a snapshot of company assessment rows at submission time.
    """
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("submitted", "Submitted"),
    )

    supervisor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="industry_results_reports",
    )
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="industry_results_reports",
    )
    rows = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]

    def can_edit(self):
        return self.status == "draft"

    def submit(self):
        if self.status != "draft":
            raise ValueError(f"Cannot submit report in status '{self.status}'.")
        self.status = "submitted"
        self.submitted_at = timezone.now()
        self.save(update_fields=["status", "submitted_at", "updated_at"])

    def __str__(self):
        return f"Industry report: {self.company} by {self.supervisor_user} ({self.status})"



class StudentEvaluation(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("submitted", "Submitted"),
    ]

    placement = models.OneToOneField(
        Placement, on_delete=models.CASCADE, related_name="student_evaluation"
    )
    student_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="student_evaluations",
    )

    # Header fields
    program = models.CharField(max_length=200, blank=True)
    internship_site = models.CharField(max_length=200, blank=True)
    eval_date = models.DateField(default=timezone.localdate)

    # Q1–Q10
    q1 = models.TextField(blank=True)
    q2 = models.TextField(blank=True)
    q3 = models.TextField(blank=True)
    q4 = models.TextField(blank=True)
    q5 = models.TextField(blank=True)
    q6 = models.TextField(blank=True)
    q7 = models.TextField(blank=True)
    q8 = models.TextField(blank=True)
    q9 = models.TextField(blank=True)
    q10 = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    submitted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def submit(self):
        self.status = "submitted"
        self.submitted_at = timezone.now()
        self.save(update_fields=["status", "submitted_at", "updated_at"])

    def __str__(self):
        return f"StudentEvaluation({self.placement_id}, {self.student_user})"


class StudentInternshipReport(models.Model):
    STATUS_CHOICES = [
        ("submitted", "Submitted"),
    ]

    placement = models.OneToOneField(
        Placement,
        on_delete=models.CASCADE,
        related_name="student_internship_report",
    )
    student_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="internship_reports",
    )
    report_file = models.FileField(upload_to="tracking/student_reports/")
    note = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="submitted")
    submitted_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-submitted_at", "-updated_at"]

    def __str__(self):
        return f"Internship report: {self.placement_id} ({self.student_user})"



class Notification(models.Model):
    LEVELS = [
        ("info", "Info"),
        ("warning", "Warning"),
        ("danger", "Danger"),
        ("secondary", "Secondary"),
        ("success", "Success"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    title = models.CharField(max_length=200)
    message = models.TextField()

    level = models.CharField(max_length=20, choices=LEVELS, default="info")
    key = models.CharField(max_length=120, blank=True, default="", db_index=True)

    action_url = models.CharField(max_length=400, blank=True, default="")
    action_text = models.CharField(max_length=50, blank=True, default="Open")

    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} - {self.title}"
