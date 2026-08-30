from django.urls import path

from apps.ai import views

app_name = "ai"

urlpatterns = [
    path("usage/", views.usage_budget, name="usage_budget"),
    path("assist/", views.assist_widget, name="assist_widget"),
    path("assist/fragment/", views.assist_fragment, name="assist_fragment"),
    path("search/", views.search_widget, name="search_widget"),
    path("anomalies/", views.anomalies_list, name="anomalies_list"),
    path("insights/", views.insights_list, name="insights_list"),
    path("recommendations/", views.recommendations_screen, name="recommendations_screen"),
    path("data-query/", views.data_query_screen, name="data_query_screen"),
]
