from django.contrib import admin
from .models import Faculty, Department, Program

@admin.register(Faculty)
class FacultyAdmin(admin.ModelAdmin):
    search_fields = ("name",)

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "faculty")
    list_filter = ("faculty",)
    search_fields = ("name", "faculty__name")

@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("name", "award_level", "department", "get_faculty")
    list_filter = ("award_level", "department__faculty", "department")
    search_fields = ("name", "department__name", "department__faculty__name")

    def get_faculty(self, obj):
        return obj.department.faculty.name
    get_faculty.short_description = "Faculty"
