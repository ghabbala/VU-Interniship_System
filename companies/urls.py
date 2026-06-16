from django.urls import path

from . import views


urlpatterns = [
    path("coordinator/companies/", views.coordinator_companies, name="coordinator_companies"),
    path("coordinator/companies/new/", views.coordinator_company_create, name="coordinator_company_create"),
]
