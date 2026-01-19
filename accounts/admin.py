from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django import forms
from django.utils.translation import gettext_lazy as _

from .models import User, StudentProfile, StaffProfile, IndustrySupervisorProfile


class AdminUserCreationForm(UserCreationForm):
    # ✅ Make names required when admin creates a user
    first_name = forms.CharField(required=True)
    last_name = forms.CharField(required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email", "first_name", "last_name")


class AdminUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = ("email", "first_name", "last_name", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    add_form = AdminUserCreationForm
    form = AdminUserChangeForm

    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "is_staff", "is_superuser", "is_active")
    search_fields = ("email", "first_name", "last_name")
    list_filter = ("is_staff", "is_superuser", "is_active", "groups")

    # ✅ Edit user page sections
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {"fields": ("first_name", "last_name")}),
        (_("Permissions"), {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )

    # ✅ Add user page sections
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "first_name", "last_name", "password1", "password2", "is_active", "is_staff", "is_superuser", "groups"),
        }),
    )

    # If your User model has username=None
    # DjangoUserAdmin uses `username` in some places; this helps avoid issues
    def get_fieldsets(self, request, obj=None):
        return super().get_fieldsets(request, obj)


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("reg_no", "user", "phone")
    search_fields = ("reg_no", "user__email", "user__first_name", "user__last_name")


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ("staff_no", "user", "department")
    search_fields = ("staff_no", "user__email", "user__first_name", "user__last_name", "department")


@admin.register(IndustrySupervisorProfile)
class IndustrySupervisorProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "company")
    search_fields = ("user__email", "user__first_name", "user__last_name", "company__name")
