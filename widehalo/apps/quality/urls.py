from django.urls import path

from apps.quality import views

app_name = "quality"

urlpatterns = [
    path("", views.control_plan_list, name="control_plan_list"),
    path("plans/<uuid:plan_id>/", views.control_plan_detail, name="control_plan_detail"),
    path("non-conformities/", views.non_conformity_list, name="non_conformity_list"),
    path("recalls/", views.recall_list, name="recall_list"),
]
