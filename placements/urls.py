from django.urls import path
from . import views

urlpatterns = [
    path("my-request/", views.my_request, name="my_request"),
    path("my-request/submit/", views.submit_request, name="submit_request"),

    path("coordinator/queue/", views.coordinator_queue, name="coordinator_queue"),
    path("coordinator/periods/", views.coordinator_periods, name="coordinator_periods"),
    path("coordinator/periods/new/", views.coordinator_period_create, name="coordinator_period_create"),
    path("coordinator/periods/<int:period_id>/edit/", views.coordinator_period_edit, name="coordinator_period_edit"),
    path("coordinator/periods/<int:period_id>/activate/", views.coordinator_period_activate, name="coordinator_period_activate"),
    path("coordinator/recommendation-settings/", views.coordinator_recommendation_settings, name="coordinator_recommendation_settings"),
    path("coordinator/review/<int:request_id>/", views.coordinator_review, name="coordinator_review"),
    path("coordinator/recommendation/<int:request_id>/", views.coordinator_issue_recommendation, name="coordinator_issue_recommendation"),

    # ✅ NEW: student can open the recommendation letter page (the template you showed)
    path("student/recommendation-letter/", views.recommendation_letter_page, name="recommendation_letter_page"),

    path("student/acceptance/upload/", views.student_upload_acceptance, name="student_upload_acceptance"),

    path("coordinator/acceptance-queue/", views.coordinator_acceptance_queue, name="coordinator_acceptance_queue"),
    path("coordinator/acceptance-verify/<int:request_id>/", views.coordinator_verify_acceptance_and_assign, name="coordinator_verify_acceptance_and_assign"),

    # ✅ already exists (download endpoint)
    path(
        "my-request/<int:request_id>/recommendation/download/",
        views.download_recommendation_letter,
        name="download_recommendation_letter",
    ),
  


    path("coordinator/waiting-acceptance/", views.coordinator_waiting_acceptance_queue, name="coordinator_waiting_acceptance_queue"),
    path("coordinator/request/<int:request_id>/return-for-acceptance/", views.coordinator_return_for_acceptance, name="coordinator_return_for_acceptance"),
]
