from django.urls import path

from apps.projects import views, views_config

app_name = "projects"

urlpatterns = [
    path("", views.project_list, name="list"),
    path("new/", views.project_create, name="create"),
    path("config/custom-fields/", views_config.config_custom_fields, name="config_custom_fields"),
    path(
        "users/<uuid:user_id>/capacity-heatmap/",
        views.user_capacity_heatmap,
        name="user_capacity_heatmap",
    ),
    path("<uuid:project_id>/", views.project_detail, name="detail"),
    path("<uuid:project_id>/gantt/", views.project_gantt, name="gantt"),
    path("<uuid:project_id>/budget/", views.project_budget, name="budget"),
    path("<uuid:project_id>/billing/", views.project_billing, name="billing"),
    path("<uuid:project_id>/sprints/", views.project_sprints, name="sprints"),
    path("<uuid:project_id>/backlog/", views.project_backlog, name="backlog"),
    path("<uuid:project_id>/kanban/", views.project_kanban, name="kanban"),
    path("<uuid:project_id>/calendar/", views.project_calendar, name="calendar"),
    path("<uuid:project_id>/roadmap/", views.project_roadmap, name="roadmap"),
    path("<uuid:project_id>/team/", views.project_team, name="team"),
    path("<uuid:project_id>/time-report/", views.project_time_report, name="time_report"),
    path("<uuid:project_id>/risks/", views.project_risks, name="risks"),
    path("<uuid:project_id>/risks/new/", views.project_risk_create, name="risk_create"),
    path("<uuid:project_id>/wiki/", views.project_wiki, name="wiki"),
    path("<uuid:project_id>/wiki/<uuid:page_id>/", views.wiki_page_detail, name="wiki_detail"),
    path("<uuid:project_id>/documents/", views.project_documents, name="documents"),
    path(
        "<uuid:project_id>/sprints/<uuid:sprint_id>/burndown/",
        views.project_sprint_burndown,
        name="sprint_burndown",
    ),
]
