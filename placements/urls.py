from django.urls import path
from . import views

urlpatterns = [
    path("my-request/", views.my_request, name="my_request"),
    path("my-request/submit/", views.submit_request, name="submit_request"),

    path("coordinator/queue/", views.coordinator_queue, name="coordinator_queue"),
    path("coordinator/review/<int:request_id>/", views.coordinator_review, name="coordinator_review"),
    path("coordinator/recommendation/<int:request_id>/", views.coordinator_issue_recommendation, name="coordinator_issue_recommendation"),
    path("student/acceptance/upload/", views.student_upload_acceptance, name="student_upload_acceptance"),

    path("coordinator/acceptance-queue/", views.coordinator_acceptance_queue, name="coordinator_acceptance_queue"),
    path("coordinator/acceptance-verify/<int:request_id>/", views.coordinator_verify_acceptance_and_assign, name="coordinator_verify_acceptance_and_assign"),
    path(
    "my-request/<int:request_id>/recommendation/download/",
    views.download_recommendation_letter,
    name="download_recommendation_letter",
),
    path("coordinator/waiting-acceptance/", views.coordinator_waiting_acceptance_queue, name="coordinator_waiting_acceptance_queue"),
    path("coordinator/request/<int:request_id>/return-for-acceptance/", views.coordinator_return_for_acceptance, name="coordinator_return_for_acceptance"),
    
]
