from django.urls import path

from apps.sales import views, views_config, views_reports

app_name = "sales"

urlpatterns = [
    path("", views.quotation_list, name="quotation_list"),
    path("new/", views.quotation_create, name="quotation_create"),
    path("<uuid:quotation_id>/", views.quotation_detail, name="quotation_detail"),
    path("orders/", views.order_list, name="order_list"),
    path("orders/new/", views.order_create, name="order_create"),
    path("orders/<uuid:order_id>/", views.order_detail, name="order_detail"),
    path("config/recurrences/", views_config.config_recurrences, name="config_recurrences"),
    path("reports/", views_reports.reports_index, name="reports_index"),
    path(
        "reports/<uuid:quotation_id>/quotation.pdf",
        views_reports.report_quotation_pdf,
        name="report_quotation_pdf",
    ),
    path(
        "reports/orders/<uuid:order_id>/confirmation.pdf",
        views_reports.report_order_confirmation_pdf,
        name="report_order_confirmation_pdf",
    ),
    path(
        "reports/orders/<uuid:order_id>/delivery-note/",
        views_reports.report_delivery_note,
        name="report_delivery_note",
    ),
    path("reports/revenue/", views_reports.report_revenue, name="report_revenue"),
    path("reports/margin/", views_reports.report_margin, name="report_margin"),
    path("reports/late-orders/", views_reports.report_late_orders, name="report_late_orders"),
    path("reports/targets/", views_reports.report_targets, name="report_targets"),
    path("reports/forecast/", views_reports.report_forecast, name="report_forecast"),
]
