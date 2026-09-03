from django.urls import path

from apps.bi import views

app_name = "bi"

urlpatterns = [
    path("", views.dashboard, name="index"),
    path("reports/new/", views.report_new, name="report_new"),
    path("reports/<uuid:report_id>/", views.report_detail, name="report_detail"),
    path("reports/<uuid:report_id>/drill-down/", views.report_drill_down, name="report_drill_down"),
    path("reports/<uuid:report_id>/export/", views.report_export, name="report_export"),
    path("metrics/<str:code>/history/", views.metric_history, name="metric_history"),
]
