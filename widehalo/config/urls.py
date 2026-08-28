from apps.core.views.auth_web import (
    change_password_view,
    login_view,
    logout_view,
    setup_company_view,
)
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
    path("change-password/", change_password_view, name="change_password"),
    path("setup/", setup_company_view, name="setup_company"),
    path("", include("apps.core.urls")),
    path("partners/", include("apps.partners.urls")),
    path("catalog/", include("apps.catalog.urls")),
    path("chat/", include("apps.chat.urls")),
    path("accounting/", include("apps.accounting.urls")),
    path("crm/", include("apps.crm.urls")),
    path("mrp/", include("apps.mrp.urls")),
    path("patronage/", include("apps.patronage.urls")),
    path("sales/", include("apps.sales.urls")),
    path("purchase/", include("apps.purchase.urls")),
    path("stocks/", include("apps.stocks.urls")),
    path("logistics/", include("apps.logistics.urls")),
]

if settings.DEBUG:
    try:
        import debug_toolbar

        urlpatterns += [path("__debug__/", debug_toolbar.urls)]
    except ImportError:
        pass
