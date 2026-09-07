"""§5.11 reporting, REP5 : enregistrement des rapports `mrp` deja construits
dans le registre partage `core.services.reports_registry`, appele depuis
`apps.py::ready()` — aucune reimplementation."""

from __future__ import annotations

from typing import Any

from apps.core.models.user import User
from apps.core.services.reports_registry import register_report


def _adapter_order_pdf(params: dict[str, Any], actor: User | None) -> bytes:
    from apps.mrp.models import MrpOrder
    from apps.mrp.services.reports import order_pdf

    order = MrpOrder.objects.get(id=params["order_id"])
    return order_pdf(order)


def _adapter_cost_report(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.mrp.models import MrpOrder
    from apps.mrp.services.reports import cost_report

    order = MrpOrder.objects.get(id=params["order_id"])
    # `cost_report` renvoie un dict — enveloppe en une seule ligne, colonnes
    # derivees dynamiquement (cf. `engine.rows_to_bytes`, `fields=()`).
    return [cost_report(order)]


def _adapter_cra_summary(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.mrp.services.reports import cra_summary

    return cra_summary(date_from=params["date_from"], date_to=params["date_to"])


def _adapter_cri_summary(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.mrp.services.reports import cri_summary

    return cri_summary(date_from=params["date_from"], date_to=params["date_to"])


def _adapter_efficiency_report(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.mrp.services.reports import efficiency_report

    return efficiency_report(params.get("workcenter_code"))


def _adapter_scrap_report(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.mrp.services.reports import scrap_report

    return scrap_report(date_from=params["date_from"], date_to=params["date_to"])


def _adapter_workload_report(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.mrp.models import MrpWorkshop
    from apps.mrp.services.reports import workload_report

    workshop = MrpWorkshop.objects.get(id=params["workshop_id"])
    return workload_report(workshop)


def register_reports() -> None:
    register_report(
        code="MRP-OF",
        owner_role="chef_atelier",
        description=(
            "Ordre de fabrication à remettre à l'atelier : nomenclature, gamme et quantités."
        ),
        module="mrp",
        label="Ordre de fabrication",
        permission="mrp.view_mrporder",
        render_pdf=_adapter_order_pdf,
    )
    register_report(
        code="MRP-COUT",
        owner_role="controleur_gestion",
        description="Coût réel d'un ordre de fabrication, matière, main-d'œuvre et écarts compris.",
        module="mrp",
        label="Cout de production",
        permission="mrp.view_mrporder",
        render_rows=_adapter_cost_report,
    )
    register_report(
        code="MRP-CRA",
        owner_role="chef_atelier",
        description="Compte-rendu d'activité d'un atelier : temps passés et quantités produites.",
        module="mrp",
        label="Compte-rendu d'activite",
        permission="mrp.view_mrpcra",
        render_rows=_adapter_cra_summary,
        fields=("employee", "workshop", "state", "total_hours", "total_qty_done"),
    )
    register_report(
        code="MRP-CRI",
        owner_role="chef_atelier",
        description="Compte-rendu d'incident de production, avec sa cause et l'action engagée.",
        module="mrp",
        label="Compte-rendu d'incident",
        permission="mrp.view_mrpcri",
        render_rows=_adapter_cri_summary,
        fields=("workcenter", "type", "total_downtime_min", "count"),
    )
    register_report(
        code="MRP-EFF",
        owner_role="resp_production",
        description="Efficacité par poste de charge : temps utile rapporté au temps ouvert.",
        module="mrp",
        label="Efficacite",
        permission="mrp.view_mrpworkcenter",
        render_rows=_adapter_efficiency_report,
        fields=("workcenter", "qty_done", "qty_rejected", "efficiency_pct"),
    )
    register_report(
        code="MRP-REBUT",
        owner_role="resp_production",
        description="Rebuts par motif et par poste, pour situer où la matière se perd.",
        module="mrp",
        label="Rebuts",
        permission="mrp.view_mrpscrap",
        render_rows=_adapter_scrap_report,
        fields=("reason", "total_qty", "total_cost_mga"),
    )
    register_report(
        code="MRP-CHARGE",
        owner_role="resp_production",
        description="Charge planifiée par atelier face à sa capacité, pour repérer les goulets.",
        module="mrp",
        label="Charge atelier",
        permission="mrp.view_mrpworkshop",
        render_rows=_adapter_workload_report,
        fields=("workcenter", "total_planned_min"),
    )
