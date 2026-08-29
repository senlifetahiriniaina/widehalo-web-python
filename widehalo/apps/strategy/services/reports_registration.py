"""§5.11 reporting : enregistrement des rapports `strategy` dans le registre
partage `core.services.reports_registry`, appele depuis `apps.py::ready()` —
meme patron que `apps.accounting.services.reports_registration`/
`apps.payroll.services.reports_registration`.

`STRATEGY-BP` (rapport business plan, `services/business_plan.py`) est
`render_pdf`-only (pas de `render_rows` — document composite multi-sections,
pas un tableau, cf. docstring `business_plan.py`), meme patron que
ACC-FAC/PAY-BULL.

`CAP-90J` (rapport « capacite de charge a 90 jours », CAP1-2, cf. plan)
est `render_rows`-only, a l'inverse : c'est un veritable tableau croise
(une ligne par semaine), pas un document composite — meme patron que
les rapports tabulaires simples deja enregistres ailleurs (ex. PAY-PROJ1
cote `payroll`)."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext as _

from apps.core.context import get_current_tenant_id
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.reports_registry import register_report


def _adapter_business_plan_pdf(params: dict[str, Any], actor: User | None) -> bytes:
    del actor  # non utilise : agrege des donnees tenant, pas de scoping N3 par acteur
    from apps.strategy.services.business_plan import generate_business_plan_pdf

    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        raise ValueError(
            _("aucun tenant actif : STRATEGY-BP ne peut pas etre genere hors contexte tenant")
        )
    tenant = Tenant.objects.get(id=tenant_id)
    return generate_business_plan_pdf(tenant, params["period"], params.get("lang", "fr"))


def _adapter_capacity_outlook_rows(
    params: dict[str, Any], actor: User | None
) -> list[dict[str, Any]]:
    del actor  # non utilise : agrege des donnees tenant, pas de scoping N3 par acteur
    from apps.strategy.services.capacity_review import (
        DEFAULT_HORIZON_DAYS,
        DEFAULT_OVERLOAD_THRESHOLD_PCT,
        build_capacity_outlook,
    )

    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        raise ValueError(
            _("aucun tenant actif : CAP-90J ne peut pas etre genere hors contexte tenant")
        )
    tenant = Tenant.objects.get(id=tenant_id)
    horizon_days = int(params.get("horizon_days", DEFAULT_HORIZON_DAYS))
    # `notify=False` : la generation du rapport (consultation/export) ne
    # doit pas re-notifier `direction`/`resp_production` a chaque
    # generation/planification (RPT-7) — la notification a deja eu lieu au
    # moment du calcul initial (ex. depuis l'ecran de suivi de capacite),
    # jamais dupliquee a chaque export.
    outlook = build_capacity_outlook(
        tenant,
        horizon_days=horizon_days,
        overload_threshold_pct=DEFAULT_OVERLOAD_THRESHOLD_PCT,
        notify=False,
    )
    return [
        {
            "semaine": week["week_index"],
            "debut_semaine": week["week_start"],
            "fin_semaine": week["week_end"],
            "capacite_heures": week["capacity_hours"],
            "charge_planifiee_heures": week["planned_workload_hours"],
            "taux_charge_pct": week["workload_pct"],
            "nb_ordres": week["orders_count"],
            "absences_jours": week["absence_days"],
            "en_surcharge": week["is_overloaded"],
        }
        for week in outlook["weeks"]
    ]


def register_reports() -> None:
    register_report(
        code="STRATEGY-BP",
        module="strategy",
        label="Business plan",
        permission="strategy.view_stgobjective",
        render_pdf=_adapter_business_plan_pdf,
    )
    register_report(
        code="CAP-90J",
        module="strategy",
        label="Capacite de charge a 90 jours",
        permission="strategy.view_stgobjective",
        render_rows=_adapter_capacity_outlook_rows,
        fields=(
            "semaine",
            "debut_semaine",
            "fin_semaine",
            "capacite_heures",
            "charge_planifiee_heures",
            "taux_charge_pct",
            "nb_ordres",
            "absences_jours",
            "en_surcharge",
        ),
    )
