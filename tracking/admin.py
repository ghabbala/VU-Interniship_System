from django.contrib import admin
from .models import WeeklyLog, SiteVisit
from .models import SiteVisit, SiteVisitReport, SiteVisitAcknowledgement

@admin.register(WeeklyLog)
class WeeklyLogAdmin(admin.ModelAdmin):
    list_display = ("placement", "week_no", "from_date", "to_date", "status", "submitted_at")
    list_filter = ("status",)
    search_fields = ("placement__company__name", "placement__request__student__reg_no")


@admin.register(SiteVisit)
class SiteVisitAdmin(admin.ModelAdmin):
    list_display = ("id", "placement", "supervisor", "scheduled_at", "visit_type", "status")
    list_filter = ("status", "visit_type", "scheduled_at")
    search_fields = (
        "placement__request__student__reg_no",
        "placement__request__student__user__email",
        "placement__company__name",
        "supervisor__user__email",
    )
    ordering = ("-scheduled_at",)

@admin.register(SiteVisitReport)
class SiteVisitReportAdmin(admin.ModelAdmin):
    list_display = ("id", "site_visit", "assessment", "submitted_at")
    list_filter = ("assessment", "submitted_at")
    ordering = ("-submitted_at",)

@admin.register(SiteVisitAcknowledgement)
class SiteVisitAcknowledgementAdmin(admin.ModelAdmin):
    list_display = ("id", "site_visit", "student", "acknowledged_at")
    list_filter = ("acknowledged_at",)
    ordering = ("-acknowledged_at",)


