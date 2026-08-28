from django.urls import path

from apps.logistics import views, views_config, views_reports

app_name = "logistics"

urlpatterns = [
    path("", views.vehicle_list, name="vehicle_list"),
    path("vehicles/new/", views.vehicle_create, name="vehicle_create"),
    path("vehicles/<uuid:vehicle_id>/", views.vehicle_detail, name="vehicle_detail"),
    path("drivers/", views.driver_list, name="driver_list"),
    path("trips/", views.trip_list, name="trip_list"),
    path("trips/new/", views.trip_create, name="trip_create"),
    path("trips/<uuid:trip_id>/", views.trip_detail, name="trip_detail"),
    path("trip-templates/", views.trip_template_list, name="trip_template_list"),
    path("shipments/", views.shipment_list, name="shipment_list"),
    path("shipments/new/", views.shipment_create, name="shipment_create"),
    path("shipments/<uuid:shipment_id>/", views.shipment_detail, name="shipment_detail"),
    path(
        "customs-files/<uuid:customs_file_id>/",
        views.customs_file_detail,
        name="customs_file_detail",
    ),
    path("config/", views_config.config_index, name="config_index"),
    path(
        "config/packaging-types/",
        views_config.config_packaging_types,
        name="config_packaging_types",
    ),
    path(
        "config/service-providers/",
        views_config.config_service_providers,
        name="config_service_providers",
    ),
    path("config/hs-codes/", views_config.config_hs_codes, name="config_hs_codes"),
    path("reports/", views_reports.reports_index, name="reports_index"),
    path("reports/vehicle-costs/", views_reports.report_vehicle_costs, name="report_vehicle_costs"),
    path("reports/shipments/", views_reports.report_shipments, name="report_shipments"),
    path("reports/customs/", views_reports.report_customs, name="report_customs"),
]
