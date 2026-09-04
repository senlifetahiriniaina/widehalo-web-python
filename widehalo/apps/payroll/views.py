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
`test_no_employee_self_service_portal_routes` (P1).

**Bloc E, E7 (PAY-9)** : `regularization_screen` consomme la DERNIERE
place du budget d'ecrans (240/240 apres ce sprint — cf.
`tests/architecture/test_budget.py`, `BUDGET_MAX_SCREENS=240`) — marge
explicitement reservee depuis E3 (paragraphe ci-dessus) pour ce sprint
precis. Toute marge d'ecran est desormais epuisee : un futur sprint qui
ajouterait un gabarit (Bloc F notamment) devra soit reutiliser un ecran
existant, soit obtenir une decision explicite du commanditaire pour
relever `BUDGET_MAX_SCREENS` (jamais silencieusement, cf. docstring du
test lui-meme)."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext as _

from apps.core.services.audit import log_pii_access
from apps.core.services.permissions import user_role_codes
from apps.core.views.tenant_web import resolve_tenant
from apps.payroll.models import PayContract, PayPayslip, PayPeriod
from apps.payroll.services.payslip import simulate_payslip
from apps.payroll.services.regularization import create_regularization

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


@login_required
def rubric_simulation(request: HttpRequest) -> HttpResponse:
    """Bloc E, E4 (PAY-5) : simulation de rubrique sur salarié témoin —
    calcule un aperçu de bulletin via EXACTEMENT le même moteur que
    `compute_payslip` (`apps.payroll.services.payslip.simulate_payslip`),
    contre un CONTRAT REEL choisi par l'utilisateur (« salarié témoin »)
    et une période réelle, mais SANS JAMAIS créer/persister de
    `PayPayslip`/`PayPayslipLine` — un simple GET (action sans effet de
    bord, jamais un POST). Réservé aux mêmes rôles que `hr_dashboard`
    (données salariales individuelles d'un vrai employé) ; chaque
    simulation effectivement calculée déclenche `log_pii_access` (même
    discipline que `hr_dashboard`/`apps.payroll.api._serialize_payslip`,
    P5)."""
    tenant = resolve_tenant(request)
    role_codes = user_role_codes(request.user)  # type: ignore[arg-type]
    if not bool(role_codes & _STAFF_ROLES):
        return HttpResponse(status=403)

    contracts = list(
        PayContract.objects.filter(tenant=tenant, is_active=True, state=PayContract.STATE_ACTIVE)
        .select_related("salary_structure")
        .order_by("reference")
    )
    periods = list(PayPeriod.objects.filter(tenant=tenant, is_active=True).order_by("-date_from"))

    context: dict[str, Any] = {
        "contracts": contracts,
        "periods": periods,
        "selected_contract_id": request.GET.get("contract_id", ""),
        "selected_period_id": request.GET.get("period_id", ""),
        "dependents": request.GET.get("dependents", "0"),
    }

    contract_id = request.GET.get("contract_id")
    period_id = request.GET.get("period_id")
    if contract_id and period_id:
        contract = next((c for c in contracts if str(c.id) == contract_id), None)
        period = next((p for p in periods if str(p.id) == period_id), None)
        if contract is None or period is None:
            context["error"] = _("Contrat ou période introuvable.")
        else:
            try:
                dependents = int(request.GET.get("dependents") or 0)
            except ValueError:
                dependents = 0
            simulation = simulate_payslip(
                tenant,
                contract,
                employee_id=contract.employee_id,
                date_from=period.date_from,
                date_to=period.date_to,
                dependents=dependents,
            )
            context["simulation_results"] = simulation.results
            log_pii_access(
                request.user,  # type: ignore[arg-type]
                contract,
                ["wage_base", "simulation_results"],
            )

    return render(request, "payroll/rubric_simulation.html", context)


@login_required
def regularization_screen(request: HttpRequest) -> HttpResponse:
    """Bloc E, E7 (PAY-9) : point d'entree HTML reel de
    `create_regularization` (jusqu'ici jamais appele en dehors des
    tests) — reserve au meme staff RH que `hr_dashboard`/
    `rubric_simulation` (aucune notion d'employe proprietaire habilite en
    libre-service, decision D1). Les bulletins d'origine proposes sont
    ceux dont la periode est deja verrouillee (RG-PAY-10) ; les periodes
    cibles proposees sont celles encore ouvertes au calcul. Chaque
    rectificatif effectivement cree declenche `log_pii_access` (meme
    discipline que `hr_dashboard`/`rubric_simulation`, P5)."""
    tenant = resolve_tenant(request)
    role_codes = user_role_codes(request.user)  # type: ignore[arg-type]
    if not bool(role_codes & _STAFF_ROLES):
        return HttpResponse(status=403)

    originals = list(
        PayPayslip.objects.filter(
            tenant=tenant,
            is_active=True,
            period__state__in=(
                PayPeriod.STATE_VALIDATED,
                PayPeriod.STATE_PAID,
                PayPeriod.STATE_CLOSED,
            ),
        )
        .exclude(state=PayPayslip.STATE_CANCELLED)
        .select_related("period", "contract")
        .order_by("-period__date_from", "employee_id")
    )
    target_periods = list(
        PayPeriod.objects.filter(
            tenant=tenant,
            is_active=True,
            state__in=(PayPeriod.STATE_OPEN, PayPeriod.STATE_COMPUTING, PayPeriod.STATE_VERIFIED),
        ).order_by("-date_from")
    )

    context: dict[str, Any] = {
        "originals": originals,
        "target_periods": target_periods,
        "selected_original_id": request.POST.get("original_id", ""),
        "selected_target_period_id": request.POST.get("target_period_id", ""),
        "reason": request.POST.get("reason", ""),
        "error": None,
        "regularization": None,
    }

    if request.method == "POST":
        original = next(
            (p for p in originals if str(p.id) == request.POST.get("original_id")), None
        )
        target_period = next(
            (p for p in target_periods if str(p.id) == request.POST.get("target_period_id")),
            None,
        )
        if original is None or target_period is None:
            context["error"] = _("Bulletin d'origine ou période cible introuvable.")
        else:
            try:
                regularization = create_regularization(
                    original,
                    target_period=target_period,
                    reason=request.POST.get("reason", "").strip(),
                    user=request.user,  # type: ignore[arg-type]
                )
            except ValidationError as exc:
                context["error"] = "; ".join(exc.messages)
            else:
                log_pii_access(
                    request.user,  # type: ignore[arg-type]
                    regularization,
                    ["gross", "net_to_pay"],
                )
                context["regularization"] = regularization

    return render(request, "payroll/regularization.html", context)
