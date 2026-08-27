from django.urls import path

from apps.patronage import views, views_config

app_name = "patronage"

urlpatterns = [
    path("", views.pattern_list, name="list"),
    path("new/", views.pattern_create, name="create"),
    path("<uuid:pattern_id>/", views.pattern_detail, name="detail"),
    path("config/", views_config.config_index, name="config_index"),
    path("config/size-charts/", views_config.config_size_charts, name="config_size_charts"),
    path(
        "config/size-charts/<uuid:size_chart_id>/",
        views_config.config_size_chart_detail,
        name="config_size_chart_detail",
    ),
    path(
        "config/grading-rules/",
        views_config.config_grading_rules,
        name="config_grading_rules",
    ),
]
