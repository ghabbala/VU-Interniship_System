from django import forms
from django.forms import inlineformset_factory
from .models import IndustryEvaluation
from .models import WeeklyLog, WeeklyLogEntry, SiteVisit
from .models import AcademicEvaluation
from .models import StudentEvaluation

from django.core.exceptions import ValidationError


MAX_ATTACHMENT_SIZE = 5 * 1024 * 1024  # 5MB


class WeeklyLogForm(forms.ModelForm):
    week_no = forms.IntegerField(
        min_value=1,
        max_value=60,
        help_text="Week number (1–60).",
        widget=forms.NumberInput(attrs={"class": "a4-input", "placeholder": "e.g. 1"}),
    )

    class Meta:
        model = WeeklyLog
        fields = ["week_no", "from_date", "to_date", "challenges", "lessons", "attachment"]
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
            "attachment": forms.ClearableFileInput(attrs={"class": "a4-file"}),
        }

    def clean_week_no(self):
        w = self.cleaned_data.get("week_no")
        if w is None:
            return w
        if w < 1 or w > 60:
            raise forms.ValidationError("Week number must be between 1 and 60.")
        return w

    def clean_attachment(self):
        f = self.cleaned_data.get("attachment")
        if not f:
            return f

        if f.size > MAX_ATTACHMENT_SIZE:
            raise ValidationError("Attachment is too large. Maximum allowed size is 5MB.")

        return f


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


class SiteVisitForm(forms.ModelForm):
    class Meta:
        model = SiteVisit
        fields = ["visit_date", "findings", "recommendations", "attachment"]
        widgets = {
            "visit_date": forms.DateInput(attrs={"type": "date", "class": "a4-input"}),
            "findings": forms.Textarea(attrs={"rows": 4, "class": "a4-textarea"}),
            "recommendations": forms.Textarea(attrs={"rows": 4, "class": "a4-textarea"}),
            "attachment": forms.ClearableFileInput(attrs={"class": "a4-file"}),
        }


from .models import IndustryEvaluation

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

        # Add Bootstrap styling to radio groups
        for k, f in self.fields.items():
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
