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
    path(
        "<uuid:project_id>/sprints/<uuid:sprint_id>/burndown/",
        views.project_sprint_burndown,
        name="sprint_burndown",
    ),
]
