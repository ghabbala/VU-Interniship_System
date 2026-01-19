from django.contrib import admin
from .models import WeeklyLog, SiteVisit

@admin.register(WeeklyLog)
class WeeklyLogAdmin(admin.ModelAdmin):
    list_display = ("placement", "week_no", "from_date", "to_date", "status", "submitted_at")
    list_filter = ("status",)
    search_fields = ("placement__company__name", "placement__request__student__reg_no")

@admin.register(SiteVisit)
class SiteVisitAdmin(admin.ModelAdmin):
    list_display = ("placement", "supervisor", "visit_date", "created_at")
    list_filter = ("visit_date",)
    search_fields = ("placement__company__name", "placement__request__student__reg_no", "supervisor__staff_no")
