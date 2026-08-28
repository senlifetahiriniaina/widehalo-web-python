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
    # reference par son UUID uniquement (resolu automatiquement via
    # `catalog.services.public.select_preferred_supplier` quand non fourni
    # explicitement, cf. `services/requisitions.py`, RG-PUR-1/PU2).
    preferred_supplier_id = models.UUIDField(null=True, blank=True)
    # RG-PUR-2 (substitution) : `PurSubstitute` appartient au meme app
    # `purchase` — une vraie FK Django est donc autorisee ici (la regle de
    # couplage n1 n'interdit que les FK VERS D'AUTRES apps metier).
    substitute = models.ForeignKey(
        "PurSubstitute", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "pur_requisition_line"

    def __str__(self) -> str:
        return f"{self.requisition_id} - {self.description}"


class PurSubstitute(BaseModel):
    """RG-PUR-2 (substitution, PU2 du sous-sequencement `purchase`, cf.
    plan) : proposition de remplacement d'un article par un autre, classee
    par niveau de compatibilite. Donnee de reference/parametrage (pas un
    document sequence) — memes conventions que `AccTax`/`CrmLostReason` :
    `BaseModel` sans `ReferenceMixin`.

    `variant_id`/`substitute_variant_id` sont de simples UUID, JAMAIS une
    FK Django vers `apps.catalog.models.ProductVariant` (regle de couplage
    n°1). `is_active` (fourni par `BaseModel`, cf. sa docstring) porte a la
    fois le soft-delete standard et le sens metier "substitut actuellement
    propose" — un seul champ, pas de doublon, meme discipline que les
    autres modeles de reference du socle (ex. `PatGradingRule`).

    Une substitution `degrade` exige une validation avant d'etre utilisable
    (`ensure_substitute_usable`) — cf. `services/substitution.py`, meme
    patron `ApprovalRule`/`ApprovalRequest` qu'`crm.services.discounts`."""

    COMPATIBILITY_IDENTIQUE = "identique"
    COMPATIBILITY_EQUIVALENT = "equivalent"
    COMPATIBILITY_DEGRADE = "degrade"
    COMPATIBILITY_CHOICES = [
        (COMPATIBILITY_IDENTIQUE, "Identique"),
        (COMPATIBILITY_EQUIVALENT, "Equivalent"),
        (COMPATIBILITY_DEGRADE, "Degrade"),
    ]

    variant_id = models.UUIDField()
    substitute_variant_id = models.UUIDField()
    compatibility = models.CharField(max_length=16, choices=COMPATIBILITY_CHOICES)
    # Ratio de conversion si les quantites different (ex. 1.2 unite de
    # substitut pour 1 unite d'origine).
    ratio = models.DecimalField(max_digits=18, decimal_places=4, default=1)
    # Texte libre i18n-able (traduction geree au niveau presentation, pas
    # de machinerie i18n dediee — meme discipline que `justification`/
    # `comment` ailleurs dans ce depot).
    conditions = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "pur_substitute"

    def __str__(self) -> str:
        return f"{self.variant_id} -> {self.substitute_variant_id} ({self.compatibility})"
