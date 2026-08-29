from django.urls import path

from apps.feasibility import views

app_name = "feasibility"

urlpatterns = [
    path("", views.study_list, name="list"),
    path("new/", views.study_create, name="create"),
    path("<uuid:study_id>/", views.study_detail, name="detail"),
]
