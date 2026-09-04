"""Ecrans HTMX du module `payroll`. Meme patron que `apps.presence.views` :
session-authentifie (`@login_required`), appel direct aux `services/*`,
jamais l'API JWT interne.

Cahier des charges Phase 3 (§6.1, decision D1) : aucun portail salarie
self-service n'est expose ici -- "le salarie n'a pas de compte... le
bulletin est remis par le gestionnaire". Les ecrans `my_payslips`/
`payslip_detail`/`payslip_download` qui existaient ici (libre-service d'un
employe sur ses propres bulletins) ont ete retires en consequence ; seul le
tableau de bord RH (`hr_dashboard`) subsiste.

**Bloc E, E3 (PAY-4)** : le plan Phase 3 annonce l'edition de
`templates/payroll/payslip_detail.html` — ce fichier n'existe plus,
retire par P1 ci-dessus (self-service). Plutot que de recreer un ecran
dedie (budget d'ecrans a 238/240, cf. `tests/architecture/test_budget.py`
— tres peu de marge, deja reservee pour E4/E7), le detail par ligne de
bulletin (base/taux/montant + version du `RegulatoryParameter` applique,
PAY-4) est integre en disclosure progressive (`<details>` imbriques,
zero JS) dans `hr_dashboard.html` lui-meme, DEJA l'unique ecran paie
existant, DEJA gate par role (`can_see_amounts`) — pas un nouvel
ecran/URL, donc aucune collision avec le garde-fou
`test_no_employee_self_service_portal_routes` (P1)."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.core.services.audit import log_pii_access
from apps.core.services.permissions import user_role_codes
from apps.core.views.tenant_web import resolve_tenant
from apps.payroll.models import PayPayslip, PayPeriod

_STAFF_ROLES = {"rh", "admin", "direction"}


@login_required
def hr_dashboard(request: HttpRequest) -> HttpResponse:
    """Tableau de bord RH : liste des periodes de paie et leur etat — les
    montants agreges (`SENSITIVE_FIELDS`) restent masques a tout role hors
    `rh`/`direction`/`admin` (cahier Phase 3 §6.1 : plus aucun role
    "collaborateur" n'a d'acces self-service a la paie, cf. decision D1).

    Bloc E, E3 (PAY-4) : quand `can_see_amounts` est vrai, chaque periode
    porte en plus ses bulletins (`period.payslips_for_display`), chacun
    avec ses lignes deja prechargees (`prefetch_related`) et un instantane
    des versions de parametres reglementaires appliques
    (`payslip.parameter_versions_snapshot`, identique sur chaque ligne
    d'un meme bulletin — cf. `PayPayslipLine.regulatory_parameter_versions`
    — affiche UNE SEULE FOIS par bulletin cote ecran plutot que repete sur
    chaque ligne, pour ne pas suggerer une specificite par ligne qui
    n'existe pas). Chaque bulletin effectivement affiche a un role
    autorise a voir ses montants declenche `log_pii_access` (meme
    discipline que `apps.payroll.api._serialize_payslip`, P5)."""
    tenant = resolve_tenant(request)
    role_codes = user_role_codes(request.user)  # type: ignore[arg-type]
    can_see_amounts = bool(role_codes & _STAFF_ROLES)
    periods = list(PayPeriod.objects.filter(tenant=tenant, is_active=True).order_by("-date_from"))

    if can_see_amounts:
        payslips_by_period_id: dict[Any, list[PayPayslip]] = {}
        payslips = (
            PayPayslip.objects.filter(tenant=tenant, is_active=True, period__in=periods)
            .prefetch_related("lines")
            .order_by("employee_id")
        )
        for payslip in payslips:
            lines = list(payslip.lines.all())
            payslip.parameter_versions_snapshot = (  # type: ignore[attr-defined]
                lines[0].regulatory_parameter_versions if lines else {}
            )
            payslips_by_period_id.setdefault(payslip.period_id, []).append(payslip)
            log_pii_access(request.user, payslip, ["gross", "net_to_pay"])  # type: ignore[arg-type]
        for period in periods:
            period.payslips_for_display = payslips_by_period_id.get(period.id, [])  # type: ignore[attr-defined]

    return render(
        request,
        "payroll/hr_dashboard.html",
        {
            "periods": periods,
            "can_see_amounts": can_see_amounts,
        },
    )
