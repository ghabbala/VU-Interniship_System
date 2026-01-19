# accounts/views.py
from django.contrib.auth import login
from django.contrib.auth.models import Group
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.contrib.auth.decorators import login_required  # ✅ add

from .forms import EmailAuthenticationForm, StudentRegistrationForm
from .models import StudentProfile


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
            )

            student_group, _ = Group.objects.get_or_create(name="Student")
            user.groups.add(student_group)

            login(request, user)
            return redirect("dashboard")

        return render(request, "accounts/register_student.html", {"form": form})


@login_required
def dashboard_redirect(request):
    u = request.user

    if u.is_superuser or u.groups.filter(name__in=["Admin", "Coordinator"]).exists():
        return redirect("coordinator_dashboard")  # ✅ redirect to view with context

    if u.groups.filter(name="UniversitySupervisor").exists():
        return redirect("supervisor_dashboard")

    if u.groups.filter(name="IndustrySupervisor").exists():
        return redirect("industry_dashboard")

    return redirect("student_dashboard")
