from django.urls import path

from apps.forecast import views

app_name = "forecast"

urlpatterns = [
    path("", views.dashboard, name="index"),
    path("workbench/", views.workbench, name="workbench"),
    path("publish/", views.publish_now, name="publish"),
]
