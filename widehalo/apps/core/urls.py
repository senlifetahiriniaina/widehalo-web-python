from django.urls import path

from apps.core.views import dashboard, pages, quality, risk

urlpatterns = [
    path("dashboard/", dashboard.dashboard, name="dashboard"),
    path("search/", pages.search_page, name="search"),
    path("search/instant/", pages.instant_search_fragment, name="instant_search"),
    path("documents/", pages.documents_list, name="documents"),
    path("settings/", pages.settings_page, name="settings"),
    path("risks/", risk.risk_list, name="risk_list"),
    path("risks/new/", risk.risk_create, name="risk_create"),
    path("risks/<uuid:risk_id>/", risk.risk_detail, name="risk_detail"),
    path("quality/templates/", quality.template_list, name="qlt_template_list"),
    path("quality/templates/new/", quality.template_create, name="qlt_template_create"),
    path(
        "quality/templates/<uuid:template_id>/",
        quality.template_detail,
        name="qlt_template_detail",
    ),
    path("quality/inspections/", quality.inspection_list, name="qlt_inspection_list"),
    path("quality/inspections/new/", quality.inspection_create, name="qlt_inspection_create"),
    path(
        "quality/inspections/<uuid:inspection_id>/",
        quality.inspection_detail,
        name="qlt_inspection_detail",
    ),
]
