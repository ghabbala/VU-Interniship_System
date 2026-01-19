from django.db import models
from django.utils import timezone
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator

from placements.models import Placement

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
        ordering = ["day"]

    def __str__(self):
        return f"{self.get_day_display()} — Week {self.weekly_log.week_no}"



class SiteVisit(models.Model):
    placement = models.ForeignKey("placements.Placement", on_delete=models.CASCADE, related_name="site_visits")
    supervisor = models.ForeignKey("accounts.StaffProfile", on_delete=models.PROTECT)

    visit_date = models.DateField()
    findings = models.TextField()
    recommendations = models.TextField(blank=True)
    attachment = models.FileField(upload_to="tracking/site_visits/", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-visit_date"]

    def __str__(self):
        return f"{self.placement} visit on {self.visit_date}"




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
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("submitted", "Submitted"),
    )

    supervisor_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    rows = models.JSONField(default=list, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    submitted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def submit(self):
        self.status = "submitted"
        self.submitted_at = timezone.now()
        self.save(update_fields=["status", "submitted_at", "updated_at"])



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
