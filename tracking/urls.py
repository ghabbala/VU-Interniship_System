from django.urls import path

from tracking.views import coordinator_views as coord
from tracking.views import university_supervisor_views as uni
from tracking.views import industry_supervisor_views as ind
from tracking.views import student_views as stu
from tracking.views import notification_views as notif


urlpatterns = [
    # =========================
    # STUDENT
    # =========================
    path("student/logs/", stu.student_logs, name="student_logs"),
    path("student/logs/new/", stu.student_log_new, name="student_log_new"),
    path("student/logs/<int:log_id>/", stu.student_log_edit, name="student_log_edit"),
    path("student/logs/<int:log_id>/delete/", stu.student_log_delete, name="student_log_delete"),

    path("student/evaluation/", stu.student_evaluation_form, name="student_evaluation_form"),
    path("student/internship-report/", stu.student_internship_report, name="student_internship_report"),
    path("student/internship-report/<int:report_id>/download/", stu.student_internship_report_download, name="student_internship_report_download"),
    path("student/dashboard/", stu.student_dashboard, name="student_dashboard"),

    path("student/site-visits/", stu.student_site_visits, name="student_site_visits"),
    path("student/site-visits/<int:visit_id>/confirm/", stu.student_confirm_site_visit, name="student_confirm_site_visit"),
    path("student/site-visits/<int:visit_id>/ack/", stu.student_ack_site_visit, name="student_ack_site_visit"),
    path("student/logs/<int:log_id>/view/", stu.student_log_detail, name="student_log_detail"),
    path("notifications/<int:pk>/read/", notif.notification_mark_read, name="notification_mark_read"),
    path("notifications/read-all/", notif.notification_mark_all_read, name="notification_mark_all_read"),
    #path("student/recommendation-letter/", stu.recommendation_letter_page, name="recommendation_letter_page"),
    #path("student/recommendation-letter/<int:request_id>/download/", stu.download_recommendation_letter, name="download_recommendation_letter"),
    

    # =========================
    # INDUSTRY SUPERVISOR / COMPANY
    # =========================
    path("company/pending/", ind.company_pending_logs, name="company_pending_logs"),
    path("company/log/<int:log_id>/action/", ind.company_action_log, name="company_action_log"),
    path("company/approved/", ind.company_approved_logs, name="company_approved_logs"),

    path("company/placement/<int:placement_id>/evaluate/", ind.company_evaluate_student, name="company_evaluate_student"),
    path("company/evaluations/approved/", ind.company_approved_evaluations, name="company_approved_evaluations"),
    path("company/results/report/", ind.industry_results_report, name="industry_results_report"),
    path("company/results/report/pdf/", ind.industry_results_report_pdf, name="industry_results_report_pdf"),
    path("company/results/report/refresh/", ind.industry_refresh_results_report, name="industry_refresh_results_report"),
    path("company/results/report/submit/", ind.industry_submit_results_report, name="industry_submit_results_report"),

    path("industry/dashboard/", ind.industry_dashboard, name="industry_dashboard"),


    # =========================
    # UNIVERSITY SUPERVISOR
    # =========================
    path("supervisor/students/", uni.supervisor_students, name="supervisor_students"),
    path("supervisor/approved-logs/", uni.supervisor_approved_logs, name="supervisor_approved_logs"),

    path("supervisor/placement/<int:placement_id>/visit/new/", uni.supervisor_add_site_visit, name="supervisor_add_site_visit"),

    path("supervisor/evaluations/submitted/", uni.supervisor_submitted_evaluations, name="supervisor_submitted_evaluations"),
    path("supervisor/industry-reports/", uni.supervisor_industry_reports, name="supervisor_industry_reports"),
    path("supervisor/industry-reports/<int:report_id>/", uni.supervisor_industry_report_detail, name="supervisor_industry_report_detail"),

    path("supervisor/placement/<int:placement_id>/academic-evaluation/", uni.supervisor_evaluate_student, name="supervisor_evaluate_student"),
    path("supervisor/evaluations/academic/submitted/", uni.supervisor_submitted_academic_evaluations, name="supervisor_submitted_academic_evaluations"),

    path("supervisor/results/report/", uni.supervisor_results_report, name="supervisor_results_report"),
    path("supervisor/results/report/pdf/", uni.supervisor_results_report_pdf, name="supervisor_results_report_pdf"),
    path("supervisor/results/report/refresh/", uni.supervisor_refresh_results_report, name="supervisor_refresh_results_report"),
    path("supervisor/results/report/submit/", uni.supervisor_submit_results_report, name="supervisor_submit_results_report"),
    path("supervisor/results-report/refresh/", uni.supervisor_refresh_results_report),

    path("supervisor/student-evaluations/", uni.supervisor_student_evaluations, name="supervisor_student_evaluations"),
    path("supervisor/student-evaluations/<int:evaluation_id>/", uni.supervisor_student_evaluation_detail, name="supervisor_student_evaluation_detail"),

    path("supervisor/dashboard/", uni.supervisor_dashboard, name="supervisor_dashboard"),

    path("supervisor/site-visits/", uni.supervisor_site_visits, name="supervisor_site_visits"),
    path("supervisor/site-visits/new/<int:placement_id>/", uni.schedule_site_visit, name="schedule_site_visit"),
    path("supervisor/site-visits/<int:visit_id>/report/", uni.submit_site_visit_report, name="submit_site_visit_report"),


    # =========================
    # COORDINATOR
    # =========================
    path("coordinator/missing-logs/", coord.coordinator_missing_logs, name="coordinator_missing_logs"),

    path("coordinator/results-reports/", coord.coordinator_results_reports, name="coordinator_results_reports"),
    path("coordinator/results-reports/<int:report_id>/", coord.coordinator_results_report_detail, name="coordinator_results_report_detail"),
    path("coordinator/results-reports/<int:report_id>/pdf/", coord.coordinator_results_report_pdf, name="coordinator_results_report_pdf"),

    path("coordinator/results-reports/<int:report_id>/approve/", coord.coordinator_approve_report, name="coordinator_approve_report"),
    path("coordinator/results-reports/<int:report_id>/request-changes/", coord.coordinator_request_changes_report, name="coordinator_request_changes_report"),
    path("coordinator/results-reports/<int:report_id>/reject/", coord.coordinator_reject_report, name="coordinator_reject_report"),

    path("coordinator/student-evaluations/", coord.coordinator_student_evaluations, name="coordinator_student_evaluations"),
    path("coordinator/student-evaluations/<int:evaluation_id>/", coord.coordinator_student_evaluation_detail, name="coordinator_student_evaluation_detail"),

    path("coordinator/dashboard/", coord.coordinator_dashboard, name="coordinator_dashboard"),
    path("coordinator/active-interns/", coord.coordinator_active_interns, name="coordinator_active_interns"),

    path("coordinator/performance/", coord.coordinator_student_performance, name="coordinator_student_performance"),
    path("coordinator/performance/<int:placement_id>/", coord.coordinator_student_performance_detail, name="coordinator_student_performance_detail"),

    path("coordinator/site-visits/", coord.coordinator_site_visits, name="coordinator_site_visits"),
    path("coordinator/site-visits/<int:visit_id>/report/", coord.coordinator_site_visit_report_detail, name="coordinator_site_visit_report_detail"),

    path("coordinator/notifications/<int:pk>/read/", notif.notification_mark_read, name="coordinator_notifications_mark_read"),
    path("coordinator/notifications/read-all/", notif.notification_mark_all_read, name="coordinator_notifications_mark_all"),
]
