from django.urls import path

from apps.crm import views, views_config, views_reports

app_name = "crm"

urlpatterns = [
    path("", views.lead_list, name="list"),
    path("new/", views.lead_create, name="create"),
    path("reports/", views_reports.reports_index, name="reports_index"),
    path("reports/pipeline/", views_reports.pipeline_report_download, name="report_pipeline"),
    path("reports/conversion/", views_reports.conversion_report_download, name="report_conversion"),
    path("reports/activities/", views_reports.activities_report_download, name="report_activities"),
    path("reports/lost/", views_reports.lost_report_download, name="report_lost"),
    path("<uuid:lead_id>/", views.lead_detail, name="detail"),
    path("config/", views_config.config_index, name="config_index"),
    path("config/pipelines/", views_config.config_pipelines, name="config_pipelines"),
    path(
        "config/pipelines/<uuid:pipeline_id>/",
        views_config.config_pipeline_detail,
        name="config_pipeline_detail",
    ),
    path("config/teams/", views_config.config_teams, name="config_teams"),
    path("config/lost-reasons/", views_config.config_lost_reasons, name="config_lost_reasons"),
]
