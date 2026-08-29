from django.urls import path

from apps.projects import views

app_name = "projects"

urlpatterns = [
    path("", views.project_list, name="list"),
    path("new/", views.project_create, name="create"),
    path("<uuid:project_id>/", views.project_detail, name="detail"),
    path("<uuid:project_id>/gantt/", views.project_gantt, name="gantt"),
    path("<uuid:project_id>/budget/", views.project_budget, name="budget"),
]
