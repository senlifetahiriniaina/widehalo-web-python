from django.urls import path

from apps.mrp import views, views_config

app_name = "mrp"

urlpatterns = [
    path("", views.order_list, name="list"),
    path("new/", views.order_create, name="create"),
    path("<uuid:order_id>/", views.order_detail, name="detail"),
    path("config/", views_config.config_index, name="config_index"),
    path("config/workshops/", views_config.config_workshops, name="config_workshops"),
    path("config/workcenters/", views_config.config_workcenters, name="config_workcenters"),
    path("config/operations/", views_config.config_operations, name="config_operations"),
    path("config/routings/", views_config.config_routings, name="config_routings"),
    path(
        "config/routings/<uuid:routing_id>/",
        views_config.config_routing_detail,
        name="config_routing_detail",
    ),
    path("config/boms/", views_config.config_boms, name="config_boms"),
    path("config/boms/<uuid:bom_id>/", views_config.config_bom_detail, name="config_bom_detail"),
]
