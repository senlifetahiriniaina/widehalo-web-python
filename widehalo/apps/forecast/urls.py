from apps.forecast import views
from django.urls import path

app_name = "forecast"

urlpatterns = [
    path("", views.dashboard, name="index"),
    path("workbench/", views.workbench, name="workbench"),
    path("publish/", views.publish_now, name="publish"),
]
