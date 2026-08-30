from django.urls import path

from apps.ai import views

app_name = "ai"

urlpatterns = [
    path("usage/", views.usage_budget, name="usage_budget"),
]
