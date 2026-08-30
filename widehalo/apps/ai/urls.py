from django.urls import path

from apps.ai import views

app_name = "ai"

urlpatterns = [
    path("usage/", views.usage_budget, name="usage_budget"),
    path("assist/", views.assist_widget, name="assist_widget"),
    path("assist/fragment/", views.assist_fragment, name="assist_fragment"),
]
