from django.urls import path

from apps.simulation import views

app_name = "simulation"

urlpatterns = [
    path("", views.library, name="index"),
    path("baseline/refresh/", views.baseline_refresh, name="baseline_refresh"),
    path("workbench/", views.workbench, name="workbench_new"),
    path("workbench/<uuid:scenario_id>/", views.workbench, name="workbench"),
    path("workbench/<uuid:scenario_id>/archive/", views.archive, name="archive"),
    path(
        "workbench/<uuid:scenario_id>/sensitivity/",
        views.sensitivity_data,
        name="sensitivity_data",
    ),
    path("compare/", views.compare, name="compare"),
]
