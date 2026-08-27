from apps.core.views.auth_web import login_view, logout_view
from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from .api import api

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="dashboard", permanent=False)),
    path("admin/", admin.site.urls),
    path("api/v1/", api.urls),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("", include("apps.core.urls")),
    path("partners/", include("apps.partners.urls")),
    path("catalog/", include("apps.catalog.urls")),
    path("chat/", include("apps.chat.urls")),
    path("accounting/", include("apps.accounting.urls")),
    path("crm/", include("apps.crm.urls")),
    path("mrp/", include("apps.mrp.urls")),
    path("patronage/", include("apps.patronage.urls")),
]

if settings.DEBUG:
    try:
        import debug_toolbar

        urlpatterns += [path("__debug__/", debug_toolbar.urls)]
    except ImportError:
        pass
