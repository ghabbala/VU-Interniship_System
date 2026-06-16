from django import forms

from .models import Company, CompanyContact


class CoordinatorCompanyForm(forms.ModelForm):
    contact_name = forms.CharField(
        required=False,
        label="Primary contact name",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Jane Doe"}),
    )
    contact_title = forms.CharField(
        required=False,
        label="Primary contact title",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. HR Manager"}),
    )
    contact_phone = forms.CharField(
        required=False,
        label="Primary contact phone",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. +256 ..."}),
    )
    contact_email = forms.EmailField(
        required=False,
        label="Primary contact email",
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "contact@company.com"}),
    )

    class Meta:
        model = Company
        fields = ["name", "industry", "district", "address", "status"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Company or organisation name"}),
            "industry": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. ICT, Finance, Health"}),
            "district": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Kampala"}),
            "address": forms.TextInput(attrs={"class": "form-control", "placeholder": "Physical address"}),
            "status": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial.setdefault("status", "approved")

    def save(self, commit=True):
        company = super().save(commit=commit)
        contact_name = (self.cleaned_data.get("contact_name") or "").strip()
        contact_email = (self.cleaned_data.get("contact_email") or "").strip()
        contact_phone = (self.cleaned_data.get("contact_phone") or "").strip()
        contact_title = (self.cleaned_data.get("contact_title") or "").strip()

        if commit and (contact_name or contact_email or contact_phone):
            CompanyContact.objects.create(
                company=company,
                name=contact_name or contact_email or contact_phone,
                title=contact_title,
                phone=contact_phone,
                email=contact_email,
            )
        return company
