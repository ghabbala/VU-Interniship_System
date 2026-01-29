# accounts/views.py
from django.contrib.auth import login
from django.contrib.auth.models import Group
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.contrib.auth.decorators import login_required

from .forms import EmailAuthenticationForm, StudentRegistrationForm
from .models import StudentProfile


# ✅ Role checks (permission-based, safe even if you rename Groups in admin)
def is_university_supervisor(user):
    return user.is_authenticated and (
        user.is_superuser or user.has_perm("accounts.role_university_supervisor")
    )

def is_industry_supervisor(user):
    return user.is_authenticated and (
        user.is_superuser or user.has_perm("accounts.role_industry_supervisor")
    )

def is_coordinator(user):
    return user.is_authenticated and (
        user.is_superuser or user.has_perm("accounts.role_coordinator")
    )


class EmailLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm


class EmailLogoutView(LogoutView):
    next_page = reverse_lazy("login")


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

            # ✅ This is fine for student registration. (Staff/coordinator accounts should be created separately.)
            student_group, _ = Group.objects.get_or_create(name="Student")
            user.groups.add(student_group)

            login(request, user)
            return redirect("dashboard")

        return render(request, "accounts/register_student.html", {"form": form})


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
