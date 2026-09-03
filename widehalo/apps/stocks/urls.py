from django.urls import path

from apps.stocks import views, views_config, views_imports, views_reports

app_name = "stocks"

urlpatterns = [
    path("", views.stock_view, name="index"),
    path("imports/", views_imports.imports_index, name="imports_index"),
    path(
        "imports/template.xlsx",
        views_imports.download_stock_import_template,
        name="imports_template",
    ),
    path(
        "imports/<uuid:batch_id>/",
        views_imports.imports_batch_detail,
        name="imports_batch_detail",
    ),
    path(
        "imports/rows/<uuid:row_id>/resolve/",
        views_imports.imports_row_resolve,
        name="imports_row_resolve",
    ),
    path(
        "imports/rows/<uuid:row_id>/qualify/",
        views_imports.imports_row_qualify,
        name="imports_row_qualify",
    ),
    path("stock-view/", views.stock_view, name="stock_view"),
    path("moves/", views.move_list, name="move_list"),
    path("moves/<uuid:move_id>/", views.move_detail, name="move_detail"),
    path("pickings/", views.picking_list, name="picking_list"),
    path("pickings/<uuid:picking_id>/", views.picking_detail, name="picking_detail"),
    path(
        "pickings/<uuid:picking_id>/fefo-suggestion/",
        views.fefo_suggestion,
        name="fefo_suggestion",
    ),
    path("measurements/", views.measurement_create, name="measurement_create"),
    path("quality/", views.quality_list, name="quality_list"),
    path("reservations/", views.reservation_list, name="reservation_list"),
    path("inventories/", views.inventory_list, name="inventory_list"),
    path("inventories/<uuid:inventory_id>/", views.inventory_detail, name="inventory_detail"),
    path("returns/", views.return_list, name="return_list"),
    path("returns/<uuid:return_id>/", views.return_detail, name="return_detail"),
    path("traceability/", views.traceability_lookup, name="traceability_lookup"),
    path("traceability/<uuid:lot_id>/recall/", views.recall_declare, name="recall_declare"),
    path("recalls/", views.recall_list, name="recall_list"),
    path("redistribution/", views.redistribution_view, name="redistribution_view"),
    path("obsolescence/", views.obsolescence_view, name="obsolescence_view"),
    path("abc/", views.abc_view, name="abc_view"),
    path("config/", views_config.config_index, name="config_index"),
    path("config/warehouses/", views_config.config_warehouses, name="config_warehouses"),
    path("config/defect-types/", views_config.config_defect_types, name="config_defect_types"),
    path(
        "config/negative-stock/",
        views_config.config_negative_stock,
        name="config_negative_stock",
    ),
    path("reports/", views_reports.reports_index, name="reports_index"),
    path("reports/state/", views_reports.report_state, name="report_state"),
    path("reports/moves/", views_reports.report_moves, name="report_moves"),
    path(
        "reports/traceability/<uuid:lot_id>/",
        views_reports.report_traceability,
        name="report_traceability",
    ),
    path(
        "reports/inventory/<uuid:inventory_id>/",
        views_reports.report_inventory,
        name="report_inventory",
    ),
    path("reports/defects/", views_reports.report_defects, name="report_defects"),
    path("reports/dormant/", views_reports.report_dormant, name="report_dormant"),
    path("reports/consistency/", views_reports.report_consistency, name="report_consistency"),
    path("reports/measurements/", views_reports.report_measurements, name="report_measurements"),
    path("reports/valuation/", views_reports.report_valuation, name="report_valuation"),
]
