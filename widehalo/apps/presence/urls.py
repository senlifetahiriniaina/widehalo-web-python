from django.urls import path

from apps.presence import views, views_reports

app_name = "presence"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("kiosk/", views.kiosk, name="kiosk"),
    path("team-calendar/", views.team_calendar, name="team_calendar"),
    path("absence-request/", views.absence_request, name="absence_request"),
    path("reports/", views_reports.reports_index, name="reports_index"),
    path(
        "reports/attendance-sheet/",
        views_reports.report_attendance_sheet,
        name="report_attendance_sheet",
    ),
    path("reports/absences/", views_reports.report_absences, name="report_absences"),
    path(
        "reports/leave-balances/", views_reports.report_leave_balances, name="report_leave_balances"
    ),
    path("reports/overtime/", views_reports.report_overtime, name="report_overtime"),
    path("reports/absenteeism/", views_reports.report_absenteeism, name="report_absenteeism"),
    path(
        "reports/reconciliation/", views_reports.report_reconciliation, name="report_reconciliation"
    ),
]
