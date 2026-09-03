from django.urls import path

from apps.mrp import views, views_config, views_reports

app_name = "mrp"

urlpatterns = [
    path("", views.order_list, name="list"),
    path("new/", views.order_create, name="create"),
    path("kanban/", views.work_order_kanban, name="kanban"),
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
    path("reports/", views_reports.reports_index, name="reports_index"),
    path(
        "reports/<uuid:order_id>/order.pdf", views_reports.report_order_pdf, name="report_order_pdf"
    ),
    path("reports/<uuid:order_id>/cost/", views_reports.report_cost, name="report_cost"),
    path("reports/cra/", views_reports.report_cra, name="report_cra"),
    path("reports/cri/", views_reports.report_cri, name="report_cri"),
    path("reports/efficiency/", views_reports.report_efficiency, name="report_efficiency"),
    path("reports/scrap/", views_reports.report_scrap, name="report_scrap"),
    path(
        "reports/workload/<uuid:workshop_id>/",
        views_reports.report_workload,
        name="report_workload",
    ),
]
