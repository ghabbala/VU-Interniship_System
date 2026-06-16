from django import forms
from .models import InternshipPeriod, InternshipRequest, RecommendationLetterSettings
from companies.models import Company
from accounts.models import StaffProfile
from django.core.exceptions import ValidationError


MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB

def validate_file_size(f):
    if f and f.size > MAX_UPLOAD_SIZE:
        raise ValidationError("File too large. Maximum allowed size is 5MB.")
    return f


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
            "request_letter",
        ]

    def clean_cv(self):
        return validate_file_size(self.cleaned_data.get("cv"))

    def clean_request_letter(self):
        return validate_file_size(self.cleaned_data.get("request_letter"))

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

    def clean_acceptance_letter(self):
        f = self.cleaned_data.get("acceptance_letter")
        if f and f.size > MAX_UPLOAD_SIZE:
            raise ValidationError("File too large. Maximum allowed size is 5MB.")
        return f

class VerifyAcceptanceAssignSupervisorForm(forms.Form):
    university_supervisor = forms.ModelChoiceField(
        queryset=StaffProfile.objects.all(),
        required=True,
        help_text="Select the University Supervisor to assign to this student.",
    )
    placement_start_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        required=True,
        label="Placement start date",
        help_text="Defaults to the official internship period start date.",
    )
    placement_end_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        required=True,
        label="Placement end date",
        help_text="Defaults to the official internship period end date.",
    )

    def __init__(self, *args, request_period=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request_period = request_period
        self.fields["university_supervisor"].widget.attrs.update({"class": "form-select"})
        if request_period and not self.is_bound:
            self.initial.setdefault("placement_start_date", request_period.start_date)
            self.initial.setdefault("placement_end_date", request_period.end_date)

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("placement_start_date")
        end = cleaned.get("placement_end_date")

        if start and end and end < start:
            raise forms.ValidationError("Placement end date cannot be before the start date.")

        return cleaned


class InternshipPeriodForm(forms.ModelForm):
    class Meta:
        model = InternshipPeriod
        fields = ["name", "start_date", "end_date", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. May-Aug 2026"}),
            "start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "End date cannot be before start date.")
        return cleaned


class RecommendationLetterSettingsForm(forms.ModelForm):
    class Meta:
        model = RecommendationLetterSettings
        fields = [
            "stamp_image",
            "signature_image",
            "signatory_name",
            "signatory_title",
            "signatory_email",
            "signatory_phone",
            "footer_address",
        ]
        widgets = {
            "stamp_image": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "signature_image": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "signatory_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Dr. Jane Doe"}),
            "signatory_title": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Dean, Faculty of Science and Technology"}),
            "signatory_email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "official email"}),
            "signatory_phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "official phone"}),
            "footer_address": forms.TextInput(attrs={"class": "form-control"}),
        }
        help_texts = {
            "stamp_image": "Upload a clear PNG or JPG stamp. Transparent PNG works best.",
            "signature_image": "Upload a clear PNG or JPG signature. Transparent PNG works best.",
            "signatory_name": "Leave blank to use the approving coordinator's name.",
            "signatory_title": "Shown below the signature line on generated letters.",
            "signatory_email": "Leave blank to use the approving coordinator's email.",
            "signatory_phone": "Leave blank to use the approving coordinator's phone, if available.",
        }

    def clean_stamp_image(self):
        stamp = self.cleaned_data.get("stamp_image")
        if stamp and getattr(stamp, "size", 0) > MAX_UPLOAD_SIZE:
            raise ValidationError("Stamp image is too large. Maximum allowed size is 5MB.")
        return stamp

    def clean_signature_image(self):
        signature = self.cleaned_data.get("signature_image")
        if signature and getattr(signature, "size", 0) > MAX_UPLOAD_SIZE:
            raise ValidationError("Signature image is too large. Maximum allowed size is 5MB.")
        return signature


class CoordinatorAcceptanceCommentForm(forms.Form):
    coordinator_comment = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}),
        required=True,
        label="Comment to student",
        help_text="Explain what the student must do (e.g., upload the acceptance letter).",
    )


