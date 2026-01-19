from django import forms
from .models import InternshipRequest
from companies.models import Company
from accounts.models import StaffProfile

class InternshipRequestForm(forms.ModelForm):
    preferred_company = forms.ModelChoiceField(
        queryset=Company.objects.filter(status="approved"),
        required=False
    )

    class Meta:
        model = InternshipRequest
        fields = [
            "preferred_company",
            "proposed_company_name",
            "proposed_company_district",
            "proposed_company_address",
            "proposed_company_contact",
            "preferred_field",
            "notes",
            "cv",
            "request_letter",
        ]

    def clean(self):
        cleaned = super().clean()
        preferred = cleaned.get("preferred_company")
        proposed_name = (cleaned.get("proposed_company_name") or "").strip()

        if not preferred and not proposed_name:
            raise forms.ValidationError("Select an approved company OR propose a new company.")

        if preferred and proposed_name:
            raise forms.ValidationError("Choose only ONE option: approved company OR proposed company.")

        return cleaned

class RecommendationLetterForm(forms.ModelForm):
    class Meta:
        model = InternshipRequest
        fields = ["recommendation_letter"]

class AcceptanceLetterUploadForm(forms.ModelForm):
    class Meta:
        model = InternshipRequest
        fields = ["acceptance_letter"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["acceptance_letter"].required = True 


class VerifyAcceptanceAssignSupervisorForm(forms.Form):
    university_supervisor = forms.ModelChoiceField(
        queryset=StaffProfile.objects.all(),
        required=True,
        help_text="Select the University Supervisor to assign to this student.",
    )

class CoordinatorAcceptanceCommentForm(forms.Form):
    coordinator_comment = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}),
        required=True,
        label="Comment to student",
        help_text="Explain what the student must do (e.g., upload the acceptance letter).",
    )


