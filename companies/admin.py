from django.contrib import admin
from .models import Company, CompanyContact

class CompanyContactInline(admin.TabularInline):
    model = CompanyContact
    extra = 1

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "district", "industry", "created_at")
    list_filter = ("status", "district", "industry")
    search_fields = ("name", "district", "industry")
    inlines = [CompanyContactInline]

@admin.register(CompanyContact)
class CompanyContactAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "phone", "email", "title")
    search_fields = ("name", "company__name", "phone", "email")
