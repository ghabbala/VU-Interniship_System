from django import forms
from django.forms import inlineformset_factory
from .models import IndustryEvaluation
from .models import WeeklyLog, WeeklyLogEntry, SiteVisit
from .models import AcademicEvaluation
from .models import StudentEvaluation, StudentInternshipReport

from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import SiteVisit, SiteVisitReport


MAX_WEEKLY_LOG_ATTACHMENTS = 5
MAX_TOTAL_ATTACHMENT_SIZE = 20 * 1024 * 1024  # 20MB
MAX_INTERNSHIP_REPORT_SIZE = 20 * 1024 * 1024  # 20MB
ALLOWED_INTERNSHIP_REPORT_EXTENSIONS = {".pdf", ".doc", ".docx"}


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def clean(self, data, initial=None):
        if not data:
            return []
        if not isinstance(data, (list, tuple)):
            data = [data]
        return [super(MultipleFileField, self).clean(item, initial) for item in data]


class WeeklyLogForm(forms.ModelForm):
    week_no = forms.IntegerField(
        min_value=1,
        max_value=60,
        help_text="Week number (1–60).",
        widget=forms.NumberInput(attrs={"class": "a4-input", "placeholder": "e.g. 1"}),
    )
    attachments = MultipleFileField(
        required=False,
        widget=MultipleFileInput(attrs={"class": "a4-file", "multiple": True}),
        help_text="Upload up to 5 files. Combined size must be 20MB or smaller.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        existing_count = self._existing_attachment_count()
        existing_size = self._existing_attachment_size()
        self.fields["attachments"].widget.attrs.update({
            "data-existing-count": existing_count,
            "data-existing-size": existing_size,
        })

    class Meta:
        model = WeeklyLog
        fields = ["week_no", "from_date", "to_date", "challenges", "lessons"]
        widgets = {
            "from_date": forms.DateInput(attrs={"type": "date", "class": "a4-input"}),
            "to_date": forms.DateInput(attrs={"type": "date", "class": "a4-input"}),

            "challenges": forms.Textarea(attrs={
                "rows": 3,
                "class": "a4-textarea",
                "placeholder": "Challenges faced during the week (optional)...",
            }),
            "lessons": forms.Textarea(attrs={
                "rows": 3,
                "class": "a4-textarea",
                "placeholder": "Lessons learnt / key takeaways (optional)...",
            }),
        }

    def clean_week_no(self):
        w = self.cleaned_data.get("week_no")
        if w is None:
            return w
        if w < 1 or w > 60:
            raise forms.ValidationError("Week number must be between 1 and 60.")
        return w

    def clean_attachments(self):
        files = self.cleaned_data.get("attachments") or []
        existing_count = self._existing_attachment_count()
        existing_size = self._existing_attachment_size()
        total_count = existing_count + len(files)
        uploaded_size = sum(f.size for f in files)
        total_size = existing_size + uploaded_size

        if total_count > MAX_WEEKLY_LOG_ATTACHMENTS:
            remaining = max(MAX_WEEKLY_LOG_ATTACHMENTS - existing_count, 0)
            raise ValidationError(
                f"You can attach a maximum of {MAX_WEEKLY_LOG_ATTACHMENTS} files per weekly log. "
                f"You can add {remaining} more file(s)."
            )

        if total_size > MAX_TOTAL_ATTACHMENT_SIZE:
            remaining_mb = max((MAX_TOTAL_ATTACHMENT_SIZE - existing_size) / (1024 * 1024), 0)
            raise ValidationError(
                "The total size of all attachments must be 20MB or smaller. "
                f"You have {remaining_mb:.1f}MB remaining for this log."
            )

        return files

    def _existing_attachment_count(self):
        if not self.instance or not self.instance.pk:
            return 0
        count = 1 if getattr(self.instance, "attachment", None) else 0
        return count + self.instance.attachments.count()

    def _existing_attachment_size(self):
        if not self.instance or not self.instance.pk:
            return 0

        total = 0
        legacy_attachment = getattr(self.instance, "attachment", None)
        if legacy_attachment:
            try:
                total += legacy_attachment.size
            except (OSError, ValueError):
                pass

        for item in self.instance.attachments.all():
            try:
                total += item.file.size
            except (OSError, ValueError):
                pass

        return total


class WeeklyLogEntryForm(forms.ModelForm):
    class Meta:
        model = WeeklyLogEntry
        fields = ["day", "work_assignment", "activities_steps"]
        widgets = {
            "day": forms.HiddenInput(),
            "work_assignment": forms.Textarea(attrs={
                "rows": 5,
                "class": "cell-textarea",
                "placeholder": "Type the work assignment for this day...",
            }),
            "activities_steps": forms.Textarea(attrs={
                "rows": 5,
                "class": "cell-textarea",
                "placeholder": "Type the activities/steps done...",
            }),
        }



WeeklyLogEntryFormSet = inlineformset_factory(
    WeeklyLog,
    WeeklyLogEntry,
    form=WeeklyLogEntryForm,
    extra=0,
    can_delete=False,
)

RATING_CHOICES = [(1, "1"), (2, "2"), (3, "3"), (4, "4"), (5, "5")]

class IndustryEvaluationForm(forms.ModelForm):
    class Meta:
        model = IndustryEvaluation
        fields = [
            # ratings
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

            # comments per section
            "basic_work_expectations_comment",
            "knowledge_and_learning_comment",
            "ethical_awareness_comment",
            "interpersonal_relations_comment",
            "communication_skills_comment",
            "attendance_comment",
            "punctuality_comment",
            "flexibility_comment",
            "dependability_comment",
            "culture_fit_comment",
            "dress_code_comment",
            "behaviour_comment",
            "work_productivity_comment",

            # recommendation
            "recommend_employment",
            "recommend_comment",

            # other comments + signoff
            "other_comments",
            "supervisor_name",
            "supervisor_signature",
        ]

        widgets = {
            # ratings as radio
            "basic_work_expectations": forms.RadioSelect(choices=RATING_CHOICES),
            "knowledge_and_learning": forms.RadioSelect(choices=RATING_CHOICES),
            "ethical_awareness": forms.RadioSelect(choices=RATING_CHOICES),
            "interpersonal_relations": forms.RadioSelect(choices=RATING_CHOICES),
            "communication_skills": forms.RadioSelect(choices=RATING_CHOICES),
            "attendance": forms.RadioSelect(choices=RATING_CHOICES),
            "punctuality": forms.RadioSelect(choices=RATING_CHOICES),
            "flexibility": forms.RadioSelect(choices=RATING_CHOICES),
            "dependability": forms.RadioSelect(choices=RATING_CHOICES),
            "culture_fit": forms.RadioSelect(choices=RATING_CHOICES),
            "dress_code": forms.RadioSelect(choices=RATING_CHOICES),
            "behaviour": forms.RadioSelect(choices=RATING_CHOICES),
            "work_productivity": forms.RadioSelect(choices=RATING_CHOICES),

            # comments as textarea
            "basic_work_expectations_comment": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "knowledge_and_learning_comment": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "ethical_awareness_comment": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "interpersonal_relations_comment": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "communication_skills_comment": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "attendance_comment": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "punctuality_comment": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "flexibility_comment": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "dependability_comment": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "culture_fit_comment": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "dress_code_comment": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "behaviour_comment": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "work_productivity_comment": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),

            "recommend_comment": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "other_comments": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),

            "supervisor_name": forms.TextInput(attrs={"class": "form-control"}),
            "supervisor_signature": forms.TextInput(attrs={"class": "form-control"}),

            "recommend_employment": forms.Select(
                attrs={"class": "form-select"},
                choices=[(True, "YES"), (False, "NO")]
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # ✅ make ALL fields required by default...
        for name, field in self.fields.items():
            field.required = True

        # ✅ ...but keep comments optional (recommended UX)
        optional_fields = [
            "basic_work_expectations_comment",
            "knowledge_and_learning_comment",
            "ethical_awareness_comment",
            "interpersonal_relations_comment",
            "communication_skills_comment",
            "attendance_comment",
            "punctuality_comment",
            "flexibility_comment",
            "dependability_comment",
            "culture_fit_comment",
            "dress_code_comment",
            "behaviour_comment",
            "work_productivity_comment",
            "recommend_comment",
            "other_comments",
        ]
        for f in optional_fields:
            if f in self.fields:
                self.fields[f].required = False

        # ✅ ensure radios have consistent class
        for name, f in self.fields.items():
            if isinstance(f.widget, forms.RadioSelect):
                f.widget.attrs.update({"class": "form-check-input"})




SCORE_CHOICES = [(1, "1"), (2, "2"), (3, "3"), (4, "4"), (5, "5")]

class AcademicEvaluationForm(forms.ModelForm):
    class Meta:
        model = AcademicEvaluation
        fields = [
            "understanding_of_internship",
            "support_framework",
            "culture_fit",
            "work_output",
            "general_presentation",
            "understanding_of_internship_comment",
            "support_framework_comment",
            "culture_fit_comment",
            "work_output_comment",
            "general_presentation_comment",
            "recommendation",
            "supervisor_name",
            "supervisor_signature",
        ]
        widgets = {
            "understanding_of_internship": forms.RadioSelect(choices=SCORE_CHOICES),
            "support_framework": forms.RadioSelect(choices=SCORE_CHOICES),
            "culture_fit": forms.RadioSelect(choices=SCORE_CHOICES),
            "work_output": forms.RadioSelect(choices=SCORE_CHOICES),
            "general_presentation": forms.RadioSelect(choices=SCORE_CHOICES),

            "understanding_of_internship_comment": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "support_framework_comment": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "culture_fit_comment": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "work_output_comment": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "general_presentation_comment": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "recommendation": forms.Textarea(attrs={"class": "form-control", "rows": 3}),

            "supervisor_name": forms.TextInput(attrs={"class": "form-control"}),
            "supervisor_signature": forms.TextInput(attrs={"class": "form-control"}),
        }




class StudentEvaluationForm(forms.ModelForm):
    class Meta:
        model = StudentEvaluation
        fields = [
            "program",
            "internship_site",
            "eval_date",
            "q1", "q2", "q3", "q4", "q5",
            "q6", "q7", "q8", "q9", "q10",
        ]
        widgets = {
            "eval_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "program": forms.TextInput(attrs={"class": "form-control"}),
            "internship_site": forms.TextInput(attrs={"class": "form-control"}),

            "q1": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "q2": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "q3": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "q4": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "q5": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "q6": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "q7": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "q8": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "q9": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "q10": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


class StudentInternshipReportForm(forms.ModelForm):
    class Meta:
        model = StudentInternshipReport
        fields = ["report_file", "note"]
        widgets = {
            "report_file": forms.ClearableFileInput(attrs={
                "class": "form-control",
                "accept": ".pdf,.doc,.docx",
            }),
            "note": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Optional note to your university supervisor...",
            }),
        }

    def clean_report_file(self):
        report_file = self.cleaned_data.get("report_file")
        if not report_file:
            return report_file

        if report_file.size > MAX_INTERNSHIP_REPORT_SIZE:
            raise ValidationError("The internship report must be 20MB or smaller.")

        name = (report_file.name or "").lower()
        if not any(name.endswith(ext) for ext in ALLOWED_INTERNSHIP_REPORT_EXTENSIONS):
            raise ValidationError("Upload a PDF, DOC, or DOCX internship report.")

        return report_file



class SiteVisitScheduleForm(forms.ModelForm):
    class Meta:
        model = SiteVisit
        fields = ["visit_type", "meeting_link", "scheduled_at", "duration_minutes", "agenda"]
        widgets = {
            "scheduled_at": forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
            "duration_minutes": forms.NumberInput(attrs={"class": "form-control", "min": 15, "max": 300}),
            "agenda": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "meeting_link": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://..."}),
            "visit_type": forms.Select(attrs={"class": "form-select"}),
        }

    def clean(self):
        cleaned = super().clean()
        visit_type = cleaned.get("visit_type")
        meeting_link = (cleaned.get("meeting_link") or "").strip()
        scheduled_at = cleaned.get("scheduled_at")

        if scheduled_at and scheduled_at < timezone.now():
            self.add_error("scheduled_at", "Scheduled date/time must be in the future.")

        if visit_type in ["zoom", "gmeet", "other"] and not meeting_link:
            self.add_error("meeting_link", "Meeting link is required for virtual visits.")

        if visit_type == "physical":
            cleaned["meeting_link"] = ""

        return cleaned


class SiteVisitReportForm(forms.ModelForm):
    class Meta:
        model = SiteVisitReport
        fields = [
            "student_attended",
            "industry_supervisor_present",
            "assessment",
            "summary",
            "progress",
            "challenges",
            "recommendations",
            "attachment",
        ]
        widgets = {
            "assessment": forms.Select(attrs={"class": "form-select"}),
            "summary": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "progress": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "challenges": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "recommendations": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "student_attended": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "industry_supervisor_present": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
