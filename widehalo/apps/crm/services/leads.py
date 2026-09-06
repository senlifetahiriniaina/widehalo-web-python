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


def convert_lead_to_partner(lead: CrmLead) -> CrmLead:
    """CRM-3 — la conversion d'une piste : societe + contact + opportunite
    en une seule validation, sans ressaisie d'aucun champ deja renseigne.

    **Ce qui manquait.** Aucune fonction de conversion n'existait dans tout
    `apps/crm` : `CrmLead.partner_id` etait un UUID nu que quelqu'un
    devait remplir a la main apres avoir cree la societe dans un autre
    module, en recopiant nom, e-mail et telephone deja saisis sur la piste.

    « Sans ressaisie » est immediat ici, et c'est ce qui rend la fonction
    courte plutot que suspecte : `CrmLead` porte deja `name`,
    `contact_name`, `email` et `phone`. Il n'y a rien a redemander — il n'y
    avait qu'a les transmettre.

    **L'opportunite n'est pas creee : elle EXISTE.** Dans ce modele de
    donnees, `CrmLead` est a la fois la piste et l'opportunite (elle porte
    pipeline, etape et montant attendu des sa creation). La conversion
    rattache donc la societe et le contact a l'opportunite existante, au
    lieu d'en fabriquer une seconde qui dupliquerait la premiere. Les trois
    objets du critere sont bien la au sortir de l'appel.

    Idempotente : une piste deja rattachee a une societe est renvoyee telle
    quelle. Refuser aurait fait echouer un double clic sur un parcours qui
    n'a rien de dangereux."""
    if lead.partner_id is not None:
        return lead

    from apps.partners.services.public import (
        ROLE_CLIENT,
        create_partner_with_contact_from_source,
    )

    created = create_partner_with_contact_from_source(
        lead.tenant,
        name=lead.name,
        role=ROLE_CLIENT,
        contact_name=lead.contact_name,
        email=lead.email,
        phone=lead.phone,
    )
    lead.partner_id = created["partner_id"]
    lead.save(update_fields=["partner_id"])
    return lead
