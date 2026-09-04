"""Ecrans HTMX du module `payroll`. Meme patron que `apps.presence.views` :
session-authentifie (`@login_required`), appel direct aux `services/*`,
jamais l'API JWT interne.

Cahier des charges Phase 3 (§6.1, decision D1) : aucun portail salarie
self-service n'est expose ici -- "le salarie n'a pas de compte... le
bulletin est remis par le gestionnaire". Les ecrans `my_payslips`/
`payslip_detail`/`payslip_download` qui existaient ici (libre-service d'un
employe sur ses propres bulletins) ont ete retires en consequence ; seul le
tableau de bord RH (`hr_dashboard`) subsiste."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.core.services.permissions import user_role_codes
from apps.core.views.tenant_web import resolve_tenant
from apps.payroll.models import PayPeriod

_STAFF_ROLES = {"rh", "admin", "direction"}


@login_required
def hr_dashboard(request: HttpRequest) -> HttpResponse:
    """Tableau de bord RH : liste des periodes de paie et leur etat — les
    montants agreges (`SENSITIVE_FIELDS`) restent masques a tout role hors
    `rh`/`direction`/`admin` (cahier Phase 3 §6.1 : plus aucun role
    "collaborateur" n'a d'acces self-service a la paie, cf. decision D1)."""
    tenant = resolve_tenant(request)
    role_codes = user_role_codes(request.user)  # type: ignore[arg-type]
    periods = PayPeriod.objects.filter(tenant=tenant, is_active=True).order_by("-date_from")
    return render(
        request,
        "payroll/hr_dashboard.html",
        {
            "periods": periods,
            "can_see_amounts": bool(role_codes & _STAFF_ROLES),
        },
    )
