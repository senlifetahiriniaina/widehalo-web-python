"""§5.11 reporting : enregistrement des rapports `sales` dans le registre
partage `core.services.reports_registry`, appele depuis `apps.py::ready()`.
REP4 a enregistre SAL-BL (RPT-10, archivage legal) ; REP5 ajoute le reste
des rapports tabulaires/PDF deja construits par ce module — tous appellent
la fonction deja existante de `services/reports.py`, aucune
reimplementation. SAL-FAC ("cf. Accounting", cf. docstring `services/
reports.py`) n'a pas d'entree ici : ce n'est qu'un lien vers ACC-FAC, deja
enregistre par `accounting`."""

from __future__ import annotations

from typing import Any

from apps.core.models.user import User
from apps.core.services.reports_registry import register_report


def _adapter_delivery_note_pdf(params: dict[str, Any], actor: User | None) -> bytes:
    from apps.reporting.services.public import render_and_archive
    from apps.sales.models import SalesOrder
    from apps.sales.services.reports import delivery_note_pdf

    order = SalesOrder.objects.get(id=params["object_id"])
    return render_and_archive(
        content_object=order, actor=actor, generate_fn=lambda: delivery_note_pdf(order)
    )


def _adapter_quotation_pdf(params: dict[str, Any], actor: User | None) -> bytes:
    from apps.sales.models import SalesQuotation
    from apps.sales.services.reports import quotation_pdf

    quotation = SalesQuotation.objects.get(id=params["object_id"])
    return quotation_pdf(quotation)


def _adapter_order_confirmation_pdf(params: dict[str, Any], actor: User | None) -> bytes:
    from apps.sales.models import SalesOrder
    from apps.sales.services.reports import order_confirmation_pdf

    order = SalesOrder.objects.get(id=params["object_id"])
    return order_confirmation_pdf(order)


def _adapter_revenue_report(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.sales.services.reports import revenue_report

    return revenue_report(
        date_from=params["date_from"],
        date_to=params["date_to"],
        group_by=params.get("group_by", "partner_id"),
    )


def _adapter_margin_report(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.core.services.permissions import user_role_codes
    from apps.sales.services.reports import margin_report

    role_codes = user_role_codes(actor) if actor is not None else set()
    return margin_report(role_codes=role_codes)


def _adapter_late_orders_report(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.sales.services.reports import late_orders_report

    return late_orders_report()


def _adapter_target_achievement_report(
    params: dict[str, Any], actor: User | None
) -> list[dict[str, Any]]:
    from apps.sales.services.reports import target_achievement_report

    return target_achievement_report(period=params["period"])


def _adapter_forecast_rows(params: dict[str, Any], actor: User | None) -> list[dict[str, Any]]:
    from apps.sales.services.reports import forecast_rows

    return forecast_rows(date_from=params["date_from"], date_to=params["date_to"])


def register_reports() -> None:
    register_report(
        code="SAL-BL",
        owner_role="magasinier",
        description="Bon de livraison accompagnant la marchandise, archivé comme pièce légale.",
        module="sales",
        label="Bon de livraison",
        permission="sales.view_salesorder",
        render_pdf=_adapter_delivery_note_pdf,
        is_legal_document=True,
    )
    register_report(
        code="SAL-DEVIS",
        owner_role="commercial",
        description="Devis à adresser au client, avec sa durée de validité.",
        module="sales",
        label="Devis",
        permission="sales.view_salesquotation",
        render_pdf=_adapter_quotation_pdf,
    )
    register_report(
        code="SAL-BC",
        owner_role="commercial",
        description="Confirmation de commande à adresser au client.",
        module="sales",
        label="Confirmation de commande",
        permission="sales.view_salesorder",
        render_pdf=_adapter_order_confirmation_pdf,
    )
    register_report(
        code="SAL-CA",
        owner_role="resp_commercial",
        description="Chiffre d'affaires sur une période, ventilé selon l'axe demandé.",
        module="sales",
        label="Chiffre d'affaires",
        permission="sales.view_salesorder",
        render_rows=_adapter_revenue_report,
    )
    register_report(
        code="SAL-MARGE",
        owner_role="resp_commercial",
        description="Marge commerciale par commande ou par article, prix de revient déduit.",
        module="sales",
        label="Marge commerciale",
        permission="sales.view_salesorder",
        render_rows=_adapter_margin_report,
    )
    register_report(
        code="SAL-RET",
        owner_role="resp_commercial",
        description="Commandes clients dont la date de livraison promise est dépassée.",
        module="sales",
        label="Commandes en retard",
        permission="sales.view_salesorder",
        render_rows=_adapter_late_orders_report,
        fields=("reference", "partner_id", "commitment_date", "state", "days_late"),
    )
    register_report(
        code="SAL-OBJ",
        owner_role="resp_commercial",
        description="Objectifs commerciaux face au réalisé, par commercial et par période.",
        module="sales",
        label="Objectifs commerciaux",
        permission="sales.view_salestarget",
        render_rows=_adapter_target_achievement_report,
        fields=("scope", "scope_ref", "target_mga", "realized_mga", "achievement_pct"),
    )
    register_report(
        code="SAL-PREV",
        owner_role="resp_commercial",
        description="Prévisions de vente publiées, avec la version et la date de leur publication.",
        module="sales",
        label="Previsions commerciales",
        permission="sales.view_salesforecast",
        render_rows=_adapter_forecast_rows,
        fields=(
            "period",
            "variant_id",
            "partner_id",
            "qty_forecast",
            "qty_actual",
            "confidence",
            "method",
        ),
    )
