from django.urls import path

from apps.purchase import views, views_config, views_reports

app_name = "purchase"

urlpatterns = [
    path("", views.requisition_list, name="requisition_list"),
    path("requisitions/new/", views.requisition_create, name="requisition_create"),
    path(
        "requisitions/<uuid:requisition_id>/",
        views.requisition_detail,
        name="requisition_detail",
    ),
    path("rfqs/", views.rfq_list, name="rfq_list"),
    path("rfqs/new/", views.rfq_create, name="rfq_create"),
    path("rfqs/<uuid:rfq_id>/", views.rfq_detail, name="rfq_detail"),
    path("orders/", views.order_list, name="order_list"),
    path("orders/new/", views.order_create, name="order_create"),
    path("orders/<uuid:order_id>/", views.order_detail, name="order_detail"),
    path("cra/", views.cra_list, name="cra_list"),
    path("cri/", views.cri_list, name="cri_list"),
    path("price-watch/", views.price_watch_list, name="price_watch_list"),
    path(
        "price-watch/<uuid:target_id>/history/",
        views.price_watch_history,
        name="price_watch_history",
    ),
    path("config/", views_config.config_index, name="config_index"),
    path(
        "config/reordering-rules/",
        views_config.config_reordering_rules,
        name="config_reordering_rules",
    ),
    path("config/substitutes/", views_config.substitute_list, name="substitute_list"),
    path("reports/", views_reports.reports_index, name="reports_index"),
    path(
        "reports/orders/<uuid:order_id>/bc.pdf",
        views_reports.report_order_pdf,
        name="report_order_pdf",
    ),
    path("reports/rfqs/<uuid:rfq_id>/", views_reports.report_rfq, name="report_rfq"),
    path(
        "reports/rfqs/<uuid:rfq_id>/comparison/",
        views_reports.report_rfq_comparison,
        name="report_rfq_comparison",
    ),
    path(
        "reports/orders/<uuid:order_id>/reception/",
        views_reports.report_reception,
        name="report_reception",
    ),
    path("reports/engagements/", views_reports.report_engagements, name="report_engagements"),
    path(
        "reports/supplier-evaluations/",
        views_reports.report_supplier_evaluations,
        name="report_supplier_evaluations",
    ),
    path("reports/late-orders/", views_reports.report_late_orders, name="report_late_orders"),
    path("reports/cri/", views_reports.report_cri, name="report_cri"),
]
