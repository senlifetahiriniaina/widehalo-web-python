from django.urls import path

from apps.helpdesk import views, views_config

app_name = "helpdesk"

urlpatterns = [
    path("", views.ticket_list, name="list"),
    path("new/", views.ticket_create, name="create"),
    path("<uuid:ticket_id>/", views.ticket_detail, name="detail"),
    path("config/", views_config.config_index, name="config_index"),
    path("config/sla-policies/", views_config.config_sla_policies, name="config_sla_policies"),
    path(
        "config/escalation-rules/",
        views_config.config_escalation_rules,
        name="config_escalation_rules",
    ),
]
