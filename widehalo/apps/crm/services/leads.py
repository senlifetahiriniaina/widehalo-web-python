"""Creation rapide d'opportunites (RG-CRM-1) : nom, client, grille de
lignes resolues sur le catalogue en un seul appel. RG-CRM-2 : une ligne
"hors catalogue" (`is_custom`) est acceptee sans bloquer la saisie."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from django.utils.translation import gettext as _

from apps.catalog.services.public import get_variant_price
from apps.core.models.tenant import Tenant
from apps.core.services.sequences import next_reference
from apps.crm.models import CrmLead, CrmLeadLine, CrmPipeline, CrmStage
from apps.crm.services.pipelines import resolve_default_pipeline


def _default_pipeline(tenant: Tenant) -> CrmPipeline:
    pipeline = resolve_default_pipeline(tenant)
    if pipeline is None:
        raise ValueError(_("Aucun pipeline configure pour ce tenant."))
    return pipeline


def _first_stage(pipeline: CrmPipeline) -> CrmStage:
    stage = pipeline.stages.order_by("sequence").first()
    if stage is None:
        raise ValueError(_("Le pipeline ne comporte aucune étape."))
    return stage


def create_lead_quick(
    *,
    tenant: Tenant,
    name: str,
    partner_id: UUID | None = None,
    pipeline: CrmPipeline | None = None,
    lines: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> CrmLead:
    """`lines` : liste de {"variant_id": UUID, "description": str, "qty":
    Decimal, "unit_price": Decimal (optionnel — resolu via le catalogue si
    absent), "discount_pct": Decimal, "is_custom": bool}."""
    from django.utils import timezone

    pipeline = pipeline or _default_pipeline(tenant)
    stage = _first_stage(pipeline)
    reference = next_reference(tenant, "LEAD", timezone.now().year)

    lead = CrmLead.objects.create(
        tenant=tenant,
        reference=reference,
        name=name,
        partner_id=partner_id,
        pipeline=pipeline,
        stage=stage,
        **extra,
    )

    for index, line in enumerate(lines or []):
        add_lead_line(lead, sequence=index, **line)

    return lead


def add_lead_line(
    lead: CrmLead,
    *,
    description: str = "",
    variant_id: UUID | None = None,
    qty: Decimal = Decimal(1),
    unit_price: Decimal | None = None,
    discount_pct: Decimal = Decimal(0),
    is_custom: bool = False,
    sequence: int = 0,
    note: str = "",
) -> CrmLeadLine:
    if not is_custom and variant_id is not None and unit_price is None:
        unit_price = get_variant_price(variant_id, partner_id=lead.partner_id)
    unit_price = unit_price or Decimal(0)

    subtotal = (qty * unit_price * (Decimal(100) - discount_pct) / Decimal(100)).quantize(
        Decimal("0.0001")
    )

    return CrmLeadLine.objects.create(
        tenant=lead.tenant,
        lead=lead,
        variant_id=variant_id,
        description=description,
        qty=qty,
        unit_price=unit_price,
        discount_pct=discount_pct,
        subtotal=subtotal,
        is_custom=is_custom,
        sequence=sequence,
        note=note,
    )
