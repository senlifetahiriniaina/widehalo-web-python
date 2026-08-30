from django.urls import path

from apps.helpdesk import views, views_config, views_reports

app_name = "helpdesk"

urlpatterns = [
    path("", views.ticket_list, name="list"),
    path("reports/", views_reports.reports_index, name="reports"),
    path("new/", views.ticket_create, name="create"),
    path("kb/", views.kb_list, name="kb_list"),
    path("kb/create/", views.kb_create, name="kb_create"),
    path("kb/<uuid:article_id>/", views.kb_detail, name="kb_detail"),
    path("<uuid:ticket_id>/", views.ticket_detail, name="detail"),
    path(
        "<uuid:ticket_id>/suggest-reply/",
        views.ticket_suggest_reply,
        name="ticket_suggest_reply",
    ),
    path("config/", views_config.config_index, name="config_index"),
    path("config/sla-policies/", views_config.config_sla_policies, name="config_sla_policies"),
    path(
        "config/escalation-rules/",
        views_config.config_escalation_rules,
        name="config_escalation_rules",
    ),
    path(
        "config/response-templates/",
        views_config.config_response_templates,
        name="config_response_templates",
    ),
]
