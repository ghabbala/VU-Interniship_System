from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth import get_user_model

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

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "reg_no", "phone", "password1", "password2")
