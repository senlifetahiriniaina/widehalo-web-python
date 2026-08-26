from django.urls import path

from apps.core.views import dashboard, pages

urlpatterns = [
    path("dashboard/", dashboard.dashboard, name="dashboard"),
    path("search/", pages.search_page, name="search"),
    path("search/instant/", pages.instant_search_fragment, name="instant_search"),
    path("documents/", pages.documents_list, name="documents"),
    path("settings/", pages.settings_page, name="settings"),
]
