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
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views import View
from django.contrib.auth.decorators import login_required
from django.db.models import Q

from .forms import (
    EmailAuthenticationForm,
    IndustrySupervisorAccountForm,
    OTPPasswordResetConfirmForm,
    PasswordResetRequestForm,
    StudentRegistrationForm,
    SystemAdminAccountForm,
    SystemAdminPasswordResetForm,
)
from .models import AccountActionLog, IndustrySupervisorProfile, PasswordResetOTP, StaffProfile, StudentProfile
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


def is_system_admin(user):
    return user.is_authenticated and (
        user.is_superuser or user.has_perm("accounts.role_system_admin")
    )


def coordinator_required(view_func):
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not is_coordinator(request.user):
            return HttpResponseForbidden("VU_Coordinators only.")
        return view_func(request, *args, **kwargs)
    return _wrapped


def system_admin_required(view_func):
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not is_system_admin(request.user):
            return HttpResponseForbidden("System Admins only.")
        return view_func(request, *args, **kwargs)
    return _wrapped


ROLE_CONFIG = {
    "system_admin": {
        "permission": "role_system_admin",
        "group": "SystemAdmin",
        "label": "System Admin",
    },
    "coordinator": {
        "permission": "role_coordinator",
        "group": "Coordinator",
        "label": "Coordinator",
    },
    "university_supervisor": {
        "permission": "role_university_supervisor",
        "group": "UniversitySupervisor",
        "label": "University Supervisor",
    },
    "industry_supervisor": {
        "permission": "role_industry_supervisor",
        "group": "IndustrySupervisor",
        "label": "Industry Supervisor",
    },
}


def _role_for_user(user):
    if user.has_perm("accounts.role_system_admin"):
        return "System Admin"
    if user.has_perm("accounts.role_coordinator"):
        return "Coordinator"
    if user.has_perm("accounts.role_university_supervisor"):
        return "University Supervisor"
    if user.has_perm("accounts.role_industry_supervisor"):
        return "Industry Supervisor"
    if hasattr(user, "student_profile"):
        return "Student"
    return "Unassigned"


def _assign_role(user, role):
    config = ROLE_CONFIG[role]
    permission = Permission.objects.get(
        content_type__app_label="accounts",
        codename=config["permission"],
    )
    group, _ = Group.objects.get_or_create(name=config["group"])
    group.permissions.add(permission)
    user.user_permissions.add(permission)
    user.groups.add(group)


def _log_account_action(actor, target_user, action, note=""):
    AccountActionLog.objects.create(
        actor=actor,
        target_user=target_user,
        action=action,
        note=note,
    )


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
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if next_url and not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = ""
    allow_without_current_placement = (request.POST.get("allow_pending_placement") or request.GET.get("allow_pending_placement")) == "1"

    if request.method == "POST":
        form = IndustrySupervisorAccountForm(
            request.POST,
            allow_without_current_placement=allow_without_current_placement,
        )
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
            group, _ = Group.objects.get_or_create(name="IndustrySupervisor")
            user.groups.add(group)

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

            if next_url:
                return redirect(next_url)
            return redirect("industry_supervisor_accounts")
    else:
        initial = {}
        company_id = request.GET.get("company") or request.GET.get("company_id")
        if company_id:
            initial["company"] = company_id
        form = IndustrySupervisorAccountForm(
            initial=initial,
            allow_without_current_placement=allow_without_current_placement,
        )

    return render(request, "accounts/industry_supervisor_account_form.html", {
        "form": form,
        "generated_password": generated_password,
        "next": next_url,
        "allow_pending_placement": allow_without_current_placement,
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


@system_admin_required
def system_admin_dashboard(request):
    users = User.objects.filter(is_superuser=False)
    recent_actions = AccountActionLog.objects.select_related("actor", "target_user")[:8]
    context = {
        "total_users": users.count(),
        "active_users": users.filter(is_active=True).count(),
        "inactive_users": users.filter(is_active=False).count(),
        "coordinators": users.filter(user_permissions__codename="role_coordinator").distinct().count(),
        "university_supervisors": users.filter(user_permissions__codename="role_university_supervisor").distinct().count(),
        "industry_supervisors": users.filter(user_permissions__codename="role_industry_supervisor").distinct().count(),
        "system_admins": users.filter(user_permissions__codename="role_system_admin").distinct().count(),
        "recent_actions": recent_actions,
    }
    return render(request, "dashboards/system_admin_dashboard.html", context)


@system_admin_required
def system_admin_users(request):
    query = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    users = (
        User.objects
        .filter(is_superuser=False)
        .prefetch_related("groups", "user_permissions")
        .select_related("staff_profile", "industry_profile", "student_profile")
        .order_by("first_name", "last_name", "email")
    )

    if query:
        users = users.filter(
            Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(staff_profile__staff_no__icontains=query)
            | Q(student_profile__reg_no__icontains=query)
            | Q(industry_profile__company__name__icontains=query)
        ).distinct()

    if status == "active":
        users = users.filter(is_active=True)
    elif status == "inactive":
        users = users.filter(is_active=False)

    rows = [{"user": user, "role": _role_for_user(user)} for user in users]
    return render(request, "accounts/system_admin_users.html", {
        "rows": rows,
        "query": query,
        "status": status,
    })


@system_admin_required
def system_admin_user_create(request):
    generated_password = None
    created_or_updated_user = None

    if request.method == "POST":
        form = SystemAdminAccountForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            role = data["role"]
            user = User.objects.filter(email__iexact=data["email"]).first()
            created = user is None

            if created:
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

            _assign_role(user, role)

            if role in ["coordinator", "university_supervisor"]:
                StaffProfile.objects.update_or_create(
                    user=user,
                    defaults={
                        "staff_no": data["staff_no"],
                        "department": data.get("department", ""),
                        "phone": data.get("phone", ""),
                    },
                )

            if role == "industry_supervisor":
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

            created_or_updated_user = user
            action = "created account" if created else "updated account"
            _log_account_action(
                request.user,
                user,
                action,
                f"{ROLE_CONFIG[role]['label']} account via System Admin portal.",
            )
            messages.success(request, f"{ROLE_CONFIG[role]['label']} account saved for {user.email}.")
            if not generated_password:
                return redirect("system_admin_users")
    else:
        form = SystemAdminAccountForm()

    return render(request, "accounts/system_admin_user_form.html", {
        "form": form,
        "generated_password": generated_password,
        "created_or_updated_user": created_or_updated_user,
    })


@system_admin_required
def system_admin_user_password(request, user_id):
    user = get_object_or_404(User, id=user_id, is_superuser=False)
    generated_password = None

    if request.method == "POST":
        form = SystemAdminPasswordResetForm(request.POST)
        if form.is_valid():
            generated_password = form.cleaned_data["temporary_password"] or secrets.token_urlsafe(10)
            user.set_password(generated_password)
            update_fields = ["password"]
            if form.cleaned_data.get("force_active"):
                user.is_active = True
                update_fields.append("is_active")
            user.save(update_fields=update_fields)
            _log_account_action(request.user, user, "reset password", "Temporary password set by System Admin.")
            messages.success(request, f"Temporary password set for {user.email}.")
    else:
        form = SystemAdminPasswordResetForm()

    return render(request, "accounts/system_admin_password_form.html", {
        "target_user": user,
        "form": form,
        "generated_password": generated_password,
    })


@system_admin_required
def system_admin_user_toggle_active(request, user_id):
    if request.method != "POST":
        return redirect("system_admin_users")

    user = get_object_or_404(User, id=user_id, is_superuser=False)
    if user.id == request.user.id:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect("system_admin_users")

    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    action = "activated account" if user.is_active else "deactivated account"
    _log_account_action(request.user, user, action)
    messages.success(request, f"{user.email} has been {'activated' if user.is_active else 'deactivated'}.")
    return redirect("system_admin_users")


@system_admin_required
def system_admin_settings(request):
    return render(request, "accounts/system_admin_settings.html")


@login_required
def dashboard_redirect(request):
    u = request.user

    if is_system_admin(u):
        return redirect("system_admin_dashboard")

    if is_coordinator(u):
        return redirect("coordinator_dashboard")

    if is_university_supervisor(u):
        return redirect("supervisor_dashboard")

    if is_industry_supervisor(u):
        return redirect("industry_dashboard")

    return redirect("student_dashboard")
