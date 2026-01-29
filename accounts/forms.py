from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth import get_user_model

from academics.models import Program
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
