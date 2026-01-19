from django.urls import path
from . import views

urlpatterns = [
    # STUDENT
    path("student/logs/", views.student_logs, name="student_logs"),
    path("student/logs/new/", views.student_log_new, name="student_log_new"),
    path("student/logs/<int:log_id>/", views.student_log_edit, name="student_log_edit"),
    path("student/logs/<int:log_id>/delete/", views.student_log_delete, name="student_log_delete"),
    path("student/evaluation/", views.student_evaluation_form, name="student_evaluation_form"),
    path("student/dashboard/", views.student_dashboard, name="student_dashboard"),
   


    # COMPANY
    path("company/pending/", views.company_pending_logs, name="company_pending_logs"),
    path("company/log/<int:log_id>/action/", views.company_action_log, name="company_action_log"),
    path("company/approved/", views.company_approved_logs, name="company_approved_logs"),

    # ✅ keep ONLY this one for evaluation
    path("company/placement/<int:placement_id>/evaluate/", views.company_evaluate_student,name="company_evaluate_student"),
    path("company/evaluations/approved/", views.company_approved_evaluations, name="company_approved_evaluations"),
    



    # UNIVERSITY SUPERVISOR
    path("supervisor/students/", views.supervisor_students, name="supervisor_students"),
    path("supervisor/approved-logs/", views.supervisor_approved_logs, name="supervisor_approved_logs"),
    path("supervisor/placement/<int:placement_id>/visit/new/", views.supervisor_add_site_visit, name="supervisor_add_site_visit"),
    path("supervisor/evaluations/submitted/", views.supervisor_submitted_evaluations, name="supervisor_submitted_evaluations"),
    # University (Academic) supervisor evaluation
    path("supervisor/placement/<int:placement_id>/academic-evaluation/", views.supervisor_evaluate_student, name="supervisor_evaluate_student"),
    path("supervisor/evaluations/academic/submitted/", views.supervisor_submitted_academic_evaluations, name="supervisor_submitted_academic_evaluations"),
    path("supervisor/evaluations/academic/submitted/", views.supervisor_submitted_academic_evaluations, name="supervisor_submitted_academic_evaluations"),
    path("supervisor/results/report/", views.supervisor_results_report, name="supervisor_results_report"),
    path("supervisor/results/report/pdf/", views.supervisor_results_report_pdf, name="supervisor_results_report_pdf"),
    path("supervisor/results/report/submit/", views.supervisor_submit_results_report, name="supervisor_submit_results_report"),
    path("supervisor/student-evaluations/", views.supervisor_student_evaluations, name="supervisor_student_evaluations"),
    path("supervisor/student-evaluations/<int:evaluation_id>/", views.supervisor_student_evaluation_detail, name="supervisor_student_evaluation_detail"),
    path("supervisor/dashboard/", views.supervisor_dashboard, name="supervisor_dashboard"),


    # COORDINATOR
    path("coordinator/missing-logs/", views.coordinator_missing_logs, name="coordinator_missing_logs"),
    path("coordinator/results-reports/", views.coordinator_results_reports, name="coordinator_results_reports"),
    path("coordinator/results-reports/<int:report_id>/", views.coordinator_results_report_detail, name="coordinator_results_report_detail"),
    path("coordinator/results-reports/<int:report_id>/pdf/", views.coordinator_results_report_pdf, name="coordinator_results_report_pdf"),
    path("coordinator/results-reports/<int:report_id>/received/", views.coordinator_mark_report_received, name="coordinator_mark_report_received"),
    path("coordinator/student-evaluations/", views.coordinator_student_evaluations, name="coordinator_student_evaluations"),
    path("coordinator/student-evaluations/<int:evaluation_id>/", views.coordinator_student_evaluation_detail, name="coordinator_student_evaluation_detail"),
    path("coordinator/dashboard/", views.coordinator_dashboard, name="coordinator_dashboard"),
]
