from django import forms
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm, UserCreationForm
from django.contrib.auth import get_user_model

from academics.models import Program
from companies.models import Company
from .models import IndustrySupervisorProfile, PasswordResetOTP
User = get_user_model()


class EmailAuthenticationForm(AuthenticationForm):
    """
    Login form that shows an 'email' field (Django still uses username internally,
    but since USERNAME_FIELD = 'email', it works as email).
    """
    username = forms.EmailField(widget=forms.EmailInput(attrs={"autofocus": True}))



class StudentRegistrationForm(UserCreationForm):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    reg_no = forms.CharField(max_length=50)
    phone = forms.CharField(max_length=30, required=False)

    # ✅ NEW
    program = forms.ModelChoiceField(
        queryset=Program.objects.select_related("department", "department__faculty").order_by(
            "department__faculty__name", "department__name", "name"
        ),
        required=True,
        empty_label="Select program…",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    # ✅ Remove default password rules text
    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="",   # removes the long validator help text
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="",   # removes the long validator help text
    )

    class Meta:
        model = User
        fields = (
            "first_name",
            "last_name",
            "email",
            "reg_no",
            "phone",
            "program",
            "password1",
            "password2",
        )


class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={
                "autocomplete": "email",
                "autofocus": True,
                "placeholder": "Enter your registered email",
            }
        )
    )

    def get_active_user(self):
        email = self.cleaned_data["email"]
        return User.objects.filter(email__iexact=email, is_active=True).first()


class OTPPasswordResetConfirmForm(SetPasswordForm):
    otp = forms.CharField(
        label="OTP code",
        min_length=6,
        max_length=6,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "one-time-code",
                "inputmode": "numeric",
                "placeholder": "Enter 6-digit code",
            }
        ),
    )

    def clean_otp(self):
        code = self.cleaned_data["otp"].strip()
        if not code.isdigit():
            raise forms.ValidationError("Enter the 6-digit code sent to your email.")

        otp = (
            PasswordResetOTP.objects.filter(user=self.user, used_at__isnull=True)
            .order_by("-created_at")
            .first()
        )

        if not otp or otp.is_expired or otp.attempts >= 5:
            raise forms.ValidationError("This OTP is invalid or has expired. Request a new code.")

        if not otp.check_code(code):
            otp.attempts += 1
            otp.save(update_fields=["attempts"])
            raise forms.ValidationError("The OTP you entered is not correct.")

        self.otp = otp
        return code


class IndustrySupervisorAccountForm(forms.Form):
    first_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    last_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": "form-control", "autocomplete": "email"}),
    )
    phone = forms.CharField(
        max_length=40,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    title = forms.CharField(
        max_length=120,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Site Supervisor"}),
    )
    company = forms.ModelChoiceField(
        queryset=Company.objects.filter(status="approved").order_by("name"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"])
        existing = User.objects.filter(email__iexact=email).first()
        if existing and not hasattr(existing, "industry_profile"):
            raise forms.ValidationError("This email already belongs to a non-industry-supervisor account.")
        return email

    def clean_company(self):
        company = self.cleaned_data["company"]
        from placements.models import Placement
        from django.utils import timezone

        has_current_placement = Placement.objects.filter(
            company=company,
            status__in=["pending_student_ack", "active", "on_hold"],
            end_date__gte=timezone.localdate(),
        ).exists()
        if not has_current_placement:
            raise forms.ValidationError(
                "This company has no current or upcoming active placement. Create the account after placement activation."
            )
        return company
