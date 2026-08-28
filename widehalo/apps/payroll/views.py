"""Ecrans HTMX du module `payroll` (§5.10.11, "Envoi multicanal du
bulletin" — mise a disposition en libre-service). Meme patron que
`apps.presence.views` : session-authentifie (`@login_required`), appel
direct aux `services/*`, jamais l'API JWT interne."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

import apps.presence.services.public as presence_public
from apps.core.services.permissions import user_role_codes
from apps.core.views.tenant_web import resolve_tenant
from apps.payroll.models import PayPayslip, PayPeriod

_STAFF_ROLES = {"rh", "admin", "direction"}


@login_required
def my_payslips(request: HttpRequest) -> HttpResponse:
    """Libre-service : un employe authentifie voit UNIQUEMENT ses propres
    bulletins (RG-PAY-9) — jamais un montant d'un collegue."""
    tenant = resolve_tenant(request)
    employee_id = presence_public.get_employee_id_for_user(tenant, request.user)  # type: ignore[arg-type]
    payslips = (
        PayPayslip.objects.filter(tenant=tenant, employee_id=employee_id, is_active=True).order_by(
            "-date_from"
        )
        if employee_id
        else PayPayslip.objects.none()
    )
    return render(request, "payroll/my_payslips.html", {"payslips": payslips})


@login_required
def hr_dashboard(request: HttpRequest) -> HttpResponse:
    """Tableau de bord RH : liste des periodes de paie et leur etat — les
    montants agreges (`SENSITIVE_FIELDS`) restent masques a tout role hors
    `rh`/`direction`/`admin`/`collaborateur` (RG-PAY-9), coherent avec le
    masquage deja applique cote API."""
    tenant = resolve_tenant(request)
    role_codes = user_role_codes(request.user)  # type: ignore[arg-type]
    periods = PayPeriod.objects.filter(tenant=tenant, is_active=True).order_by("-date_from")
    return render(
        request,
        "payroll/hr_dashboard.html",
        {
            "periods": periods,
            "can_see_amounts": bool(role_codes & (_STAFF_ROLES | {"collaborateur"})),
        },
    )
