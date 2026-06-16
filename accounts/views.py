# accounts/views.py
import secrets
import smtplib
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.contrib.auth.views import LoginView, LogoutView
from django.core.mail import EmailMultiAlternatives
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.contrib.auth.decorators import login_required

from .forms import (
    EmailAuthenticationForm,
    IndustrySupervisorAccountForm,
    OTPPasswordResetConfirmForm,
    PasswordResetRequestForm,
    StudentRegistrationForm,
)
from .models import IndustrySupervisorProfile, PasswordResetOTP, StudentProfile
from companies.models import CompanyContact


User = get_user_model()


# ✅ Role checks (permission-based, safe even if you rename Groups in admin)
def is_university_supervisor(user):
    return user.is_authenticated and (
        user.is_superuser or user.has_perm("accounts.role_university_supervisor")
    )

def is_industry_supervisor(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if not user.has_perm("accounts.role_industry_supervisor"):
        return False
    profile = getattr(user, "industry_profile", None)
    if profile and not profile.has_current_placement_access():
        user.is_active = False
        user.save(update_fields=["is_active"])
        return False
    return True

def is_coordinator(user):
    return user.is_authenticated and (
        user.is_superuser or user.has_perm("accounts.role_coordinator")
    )


def coordinator_required(view_func):
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not is_coordinator(request.user):
            return HttpResponseForbidden("VU_Coordinators only.")
        return view_func(request, *args, **kwargs)
    return _wrapped


class EmailLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm


class EmailLogoutView(LogoutView):
    next_page = reverse_lazy("login")


class PasswordResetRequestView(View):
    template_name = "accounts/password_reset_form.html"

    def get(self, request):
        return render(request, self.template_name, {"form": PasswordResetRequestForm()})

    def post(self, request):
        form = PasswordResetRequestForm(request.POST)
        if form.is_valid():
            user = form.get_active_user()
            if user:
                code = f"{secrets.randbelow(900000) + 100000}"
                expires_at = timezone.now() + timedelta(minutes=10)
                otp = PasswordResetOTP.create_for_user(user, code, expires_at)
                request.session["password_reset_user_id"] = user.pk
                try:
                    self.send_otp_email(request, user, code)
                except smtplib.SMTPException:
                    otp.mark_used()
                    form.add_error(
                        None,
                        "We could not send the OTP email. Check the system email credentials and try again.",
                    )
                    return render(request, self.template_name, {"form": form})

            return redirect("password_reset_done")

        return render(request, self.template_name, {"form": form})

    def send_otp_email(self, request, user, code):
        context = {
            "user": user,
            "code": code,
            "expires_minutes": 10,
        }
        subject = "Victoria University Internship Portal password reset OTP"
        text_body = render_to_string("accounts/password_reset_otp_email.txt", context)
        html_body = render_to_string("accounts/password_reset_otp_email.html", context)
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        email.attach_alternative(html_body, "text/html")
        email.send()


class PasswordResetOTPConfirmView(View):
    template_name = "accounts/password_reset_confirm.html"

    def get_user(self, request):
        user_id = request.session.get("password_reset_user_id")
        if not user_id:
            return None
        from django.contrib.auth import get_user_model

        return get_user_model().objects.filter(pk=user_id, is_active=True).first()

    def get(self, request):
        user = self.get_user(request)
        if not user:
            return redirect("password_reset")

        form = OTPPasswordResetConfirmForm(user)
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        user = self.get_user(request)
        if not user:
            return redirect("password_reset")

        form = OTPPasswordResetConfirmForm(user, request.POST)
        if form.is_valid():
            form.save()
            form.otp.mark_used()
            request.session.pop("password_reset_user_id", None)
            return redirect("password_reset_complete")

        return render(request, self.template_name, {"form": form})


class RegisterStudentView(View):
    def get(self, request):
        form = StudentRegistrationForm()
        return render(request, "accounts/register_student.html", {"form": form})

    def post(self, request):
        form = StudentRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.first_name = form.cleaned_data["first_name"]
            user.last_name = form.cleaned_data["last_name"]
            user.save()

            StudentProfile.objects.create(
                user=user,
                reg_no=form.cleaned_data["reg_no"],
                phone=form.cleaned_data.get("phone", ""),
                program=form.cleaned_data["program"],
            )

            student_group, _ = Group.objects.get_or_create(name="Student")
            user.groups.add(student_group)

            messages.success(request, "Student account created successfully. Please log in.")
            return redirect("login")

        return render(request, "accounts/register_student.html", {"form": form})


@coordinator_required
def industry_supervisor_accounts(request):
    profiles = (
        IndustrySupervisorProfile.objects
        .select_related("user", "company")
        .order_by("company__name", "user__email")
    )
    rows = []
    for profile in profiles:
        rows.append({
            "profile": profile,
            "has_access": profile.user.is_active and profile.has_current_placement_access(),
        })

    return render(request, "accounts/industry_supervisor_accounts.html", {"rows": rows})


@coordinator_required
def industry_supervisor_account_create(request):
    generated_password = None

    if request.method == "POST":
        form = IndustrySupervisorAccountForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            user = User.objects.filter(email__iexact=data["email"]).first()
            created_user = user is None

            if created_user:
                generated_password = secrets.token_urlsafe(10)
                user = User.objects.create_user(
                    email=data["email"],
                    password=generated_password,
                    first_name=data["first_name"],
                    last_name=data["last_name"],
                    is_active=True,
                )
            else:
                user.first_name = data["first_name"]
                user.last_name = data["last_name"]
                user.is_active = True
                user.save(update_fields=["first_name", "last_name", "is_active"])

            permission = Permission.objects.get(
                content_type__app_label="accounts",
                codename="role_industry_supervisor",
            )
            user.user_permissions.add(permission)

            IndustrySupervisorProfile.objects.update_or_create(
                user=user,
                defaults={"company": data["company"]},
            )
            CompanyContact.objects.update_or_create(
                email=data["email"],
                defaults={
                    "company": data["company"],
                    "name": f"{data['first_name']} {data['last_name']}".strip(),
                    "title": data.get("title", ""),
                    "phone": data.get("phone", ""),
                },
            )

            try:
                self_service_note = "Use Forgot password on the login page to set a new password."
                context = {
                    "user": user,
                    "company": data["company"],
                    "generated_password": generated_password,
                    "self_service_note": self_service_note,
                }
                body = render_to_string("accounts/industry_supervisor_welcome_email.txt", context)
                email = EmailMultiAlternatives(
                    subject="Victoria University Internship Portal account",
                    body=body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[user.email],
                )
                email.send()
                messages.success(request, "Industry supervisor account created and email sent.")
            except smtplib.SMTPException:
                messages.warning(
                    request,
                    "Account created, but the email could not be sent. Check SMTP settings.",
                )

            return redirect("industry_supervisor_accounts")
    else:
        form = IndustrySupervisorAccountForm()

    return render(request, "accounts/industry_supervisor_account_form.html", {
        "form": form,
        "generated_password": generated_password,
    })


@coordinator_required
def industry_supervisor_account_deactivate(request, user_id):
    if request.method != "POST":
        return redirect("industry_supervisor_accounts")

    user = get_object_or_404(User, id=user_id, industry_profile__isnull=False)
    user.is_active = False
    user.save(update_fields=["is_active"])
    messages.success(request, f"{user.email} has been deactivated.")
    return redirect("industry_supervisor_accounts")


@login_required
def dashboard_redirect(request):
    u = request.user

    if is_coordinator(u):
        return redirect("coordinator_dashboard")

    if is_university_supervisor(u):
        return redirect("supervisor_dashboard")

    if is_industry_supervisor(u):
        return redirect("industry_dashboard")

    return redirect("student_dashboard")
