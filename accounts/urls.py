from django.contrib.auth import views as auth_views
from django.urls import path
from .views import (
    EmailLoginView,
    EmailLogoutView,
    PasswordResetOTPConfirmView,
    PasswordResetRequestView,
    RegisterStudentView,
    dashboard_redirect,
    industry_supervisor_account_create,
    industry_supervisor_account_deactivate,
    industry_supervisor_accounts,
)

urlpatterns = [
    path("login/", EmailLoginView.as_view(), name="login"),
    path("logout/", EmailLogoutView.as_view(), name="logout"),
    path(
        "password-reset/",
        PasswordResetRequestView.as_view(),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "password-reset/verify/",
        PasswordResetOTPConfirmView.as_view(),
        name="password_reset_verify",
    ),
    path(
        "password-reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    path("register/student/", RegisterStudentView.as_view(), name="register_student"),
    path("coordinator/industry-supervisors/", industry_supervisor_accounts, name="industry_supervisor_accounts"),
    path("coordinator/industry-supervisors/new/", industry_supervisor_account_create, name="industry_supervisor_account_create"),
    path(
        "coordinator/industry-supervisors/<int:user_id>/deactivate/",
        industry_supervisor_account_deactivate,
        name="industry_supervisor_account_deactivate",
    ),
    path("dashboard/", dashboard_redirect, name="dashboard"),
]
