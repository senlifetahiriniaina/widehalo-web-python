from django.urls import path

from apps.core.views import dashboard, pages, risk

urlpatterns = [
    path("dashboard/", dashboard.dashboard, name="dashboard"),
    path("search/", pages.search_page, name="search"),
    path("search/instant/", pages.instant_search_fragment, name="instant_search"),
    path("documents/", pages.documents_list, name="documents"),
    path("settings/", pages.settings_page, name="settings"),
    path("risks/", risk.risk_list, name="risk_list"),
    path("risks/new/", risk.risk_create, name="risk_create"),
    path("risks/<uuid:risk_id>/", risk.risk_detail, name="risk_detail"),
]
