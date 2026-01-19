from django.urls import path
from .views import EmailLoginView, EmailLogoutView, RegisterStudentView, dashboard_redirect

urlpatterns = [
    path("login/", EmailLoginView.as_view(), name="login"),
    path("logout/", EmailLogoutView.as_view(), name="logout"),
    path("register/student/", RegisterStudentView.as_view(), name="register_student"),
    path("dashboard/", dashboard_redirect, name="dashboard"),
]
