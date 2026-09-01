from apps.core.views.admin_users import admin_user_edit, admin_user_list
from apps.core.views.auth_web import (
    change_password_view,
    confirm_email_view,
    login_view,
    logout_view,
    mfa_view,
    profile_view,
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
    path("profile/", profile_view, name="profile"),
    path("setup/", setup_company_view, name="setup_company"),
    path("mfa/", mfa_view, name="mfa"),
    # UXR1 : lien de confirmation d'e-mail (vue PUBLIQUE, cf. docstring de
    # `confirm_email_view`) — hors `apps.core.urls` (dont toutes les
    # entrees supposent une session), au meme niveau que `login/`.
    path("account/confirm-email/<str:token>/", confirm_email_view, name="confirm_email"),
    path("users/", admin_user_list, name="admin_user_list"),
    path("users/<uuid:user_id>/edit/", admin_user_edit, name="admin_user_edit"),
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
    path("presence/", include("apps.presence.urls")),
    path("payroll/", include("apps.payroll.urls")),
    path("reporting/", include("apps.reporting.urls")),
    path("strategy/", include("apps.strategy.urls")),
    path("financing/", include("apps.financing.urls")),
    path("automation/", include("apps.automation.urls")),
    path("feasibility/", include("apps.feasibility.urls")),
    path("projects/", include("apps.projects.urls")),
    path("ai/", include("apps.ai.urls")),
    path("helpdesk/", include("apps.helpdesk.urls")),
]

if settings.DEBUG:
    try:
        import debug_toolbar

        urlpatterns += [path("__debug__/", include(debug_toolbar.urls))]
    except ImportError:
        pass
