"""Achats (§5.6, PU1 du sous-sequencement `purchase` — cf. plan) : demande
d'achat (`PurRequisition`/`PurRequisitionLine`), premiere brique du
module. Workflow simple `draft -> submitted -> approved/rejected` (pas de
FSM `django-fsm` a ce stade : deux transitions terminales triviales, meme
discipline que `AccBudget`/`AccLandedCostBatch` — la FSM complete
§5.6.4 n'arrive qu'en PU4 sur `PurOrder`). La resolution de prix indicative
par ligne (`estimated_price_mga`) passe par
`apps.catalog.services.public.get_variant_price`, meme patron que
`sales.services.quotations.add_quotation_line` (S1).

Regle de couplage n1 (identique a `sales`/`crm`/`mrp`) : `purchase` ne fait
jamais de FK Django vers `apps.catalog`/`apps.partners` (ni, plus tard,
`apps.mrp`/`apps.accounting`) — ces entites sont referencees par UUID nu,
resolues via `services.public` de chaque app quand une information
affichable est necessaire. Le seul FK "reel" est vers `core.User`
(demandeur), qui appartient au socle et n'est pas une autre app metier."""

from __future__ import annotations

from django.db import models

from apps.core.models.base import BaseModel, ReferenceMixin


class PurRequisition(BaseModel, ReferenceMixin):
    STATE_DRAFT = "draft"
    STATE_SUBMITTED = "submitted"
    STATE_APPROVED = "approved"
    STATE_REJECTED = "rejected"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_SUBMITTED, "Soumise"),
        (STATE_APPROVED, "Approuvee"),
        (STATE_REJECTED, "Rejetee"),
    ]

    requester = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    department = models.CharField(max_length=100, blank=True)
    date_needed = models.DateField()
    justification = models.TextField(blank=True)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_DRAFT)
    # Reference libre vers un document d'origine (ex. un devis, un besoin de
    # production) — pas de generic FK a ce stade, hors perimetre PU1.
    source_document = models.CharField(max_length=255, blank=True)
    rejection_reason = models.TextField(blank=True)

    class Meta:
        db_table = "pur_requisition"

    def __str__(self) -> str:
        return self.reference or str(self.id)


class PurRequisitionLine(BaseModel):
    requisition = models.ForeignKey(PurRequisition, on_delete=models.CASCADE, related_name="lines")
    # Jamais de FK Django vers `apps.catalog.models.ProductVariant` — un
    # article est reference par son UUID, resolu via `catalog.services.public`.
    variant_id = models.UUIDField()
    description = models.CharField(max_length=255)
    qty = models.DecimalField(max_digits=18, decimal_places=4, default=1)
    uom = models.CharField(max_length=16, blank=True)
    estimated_price_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    # Jamais de FK Django vers `apps.partners.models.Partner` — un tiers est
    # reference par son UUID uniquement (choix indicatif, RG-PUR-1/PU2
    # affinera la selection reelle multi-fournisseurs).
    preferred_supplier_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "pur_requisition_line"

    def __str__(self) -> str:
        return f"{self.requisition_id} - {self.description}"
