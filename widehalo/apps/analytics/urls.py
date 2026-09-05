from django.urls import path

from apps.analytics import views

app_name = "analytics"

urlpatterns = [
    path("", views.dashboard, name="index"),
    path("refresh/", views.refresh_now, name="refresh_now"),
    path("metrics/save/", views.metric_save, name="metric_save"),
]
