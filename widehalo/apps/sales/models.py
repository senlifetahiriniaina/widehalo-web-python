"""Ventes (§5.5) : devis (`SalesQuotation`/`SalesQuotationLine`) — S1 du
sous-sequencement du module `sales` (cf. plan). La commande de vente
(`SalesOrder`, FSM complete §5.5.4) est differee a S2, la qualification
d'origine par ligne (RG-SAL-3) a S3, la facturation (RG-SAL-2) a S4.

Regle de couplage n1 : `sales` ne fait jamais de FK Django vers
`apps.partners`/`apps.catalog`/`apps.crm`/`apps.accounting` — ces entites
sont referencees par UUID nu, resolues via `services.public` de chaque
app quand une information affichable (reference, prix...) est necessaire."""

from __future__ import annotations

from django.db import models

from apps.core.models.base import BaseModel, ReferenceMixin


class SalesQuotation(BaseModel, ReferenceMixin):
    STATE_DRAFT = "draft"
    STATE_SENT = "sent"
    STATE_ACCEPTED = "accepted"
    STATE_DECLINED = "declined"
    STATE_EXPIRED = "expired"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_SENT, "Envoye"),
        (STATE_ACCEPTED, "Accepte"),
        (STATE_DECLINED, "Refuse"),
        (STATE_EXPIRED, "Expire"),
    ]

    INCOTERM_EXW = "EXW"
    INCOTERM_FOB = "FOB"
    INCOTERM_CIF = "CIF"
    INCOTERM_DAP = "DAP"
    INCOTERM_DDP = "DDP"
    INCOTERM_CHOICES = [
        (INCOTERM_EXW, "EXW — A l'usine"),
        (INCOTERM_FOB, "FOB — Franco a bord"),
        (INCOTERM_CIF, "CIF — Cout, assurance et fret"),
        (INCOTERM_DAP, "DAP — Rendu au lieu de destination"),
        (INCOTERM_DDP, "DDP — Rendu droits acquittes"),
    ]

    # Jamais de FK Django vers `apps.partners.models.Partner` (regle de
    # couplage n1) — un tiers est reference par son UUID uniquement.
    partner_id = models.UUIDField()
    contact = models.CharField(max_length=150, blank=True)
    # Lien de tracabilite en lecture seule vers `apps.crm.models.CrmLead`,
    # jamais une FK : `sales` n'importe et ne mute jamais l'etat d'un lead
    # CRM (cf. plan, decision de couplage minimal RG-CRM-4/RG-SAL).
    source_lead_id = models.UUIDField(null=True, blank=True)
    date = models.DateField()
    validity_date = models.DateField(null=True, blank=True)
    # Jamais de FK Django vers `apps.catalog.models.PriceList`.
    pricelist_id = models.UUIDField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="MGA")
    # Jamais de FK Django vers `apps.accounting.models.AccPaymentTerm` —
    # purement informatif en S1, pas encore applique/valide (S4).
    payment_term_id = models.UUIDField(null=True, blank=True)
    incoterm = models.CharField(max_length=8, choices=INCOTERM_CHOICES, blank=True)
    delivery_address = models.TextField(blank=True)
    salesperson = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_DRAFT)
    amount_untaxed = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    amount_tax = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    amount_total = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    amount_total_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    notes = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)

    class Meta:
        db_table = "sales_quotation"

    def __str__(self) -> str:
        return self.reference or str(self.id)


class SalesQuotationLine(BaseModel):
    SOURCE_STOCK = "stock"
    SOURCE_PRODUCTION = "production"
    SOURCE_ACHAT = "achat"
    SOURCE_CHOICES = [
        (SOURCE_STOCK, "Sur stock"),
        (SOURCE_PRODUCTION, "A produire"),
        (SOURCE_ACHAT, "A acheter"),
    ]

    quotation = models.ForeignKey(SalesQuotation, on_delete=models.CASCADE, related_name="lines")
    sequence = models.PositiveIntegerField(default=0)
    # Jamais de FK Django vers `apps.catalog.models.ProductVariant` — un
    # article est reference par son UUID, resolu via `catalog.services.public`.
    # Nullable pour autoriser les lignes hors catalogue (`is_custom`).
    variant_id = models.UUIDField(null=True, blank=True)
    is_custom = models.BooleanField(default=False)
    description = models.CharField(max_length=255)
    qty = models.DecimalField(max_digits=18, decimal_places=4, default=1)
    uom = models.CharField(max_length=16, blank=True)
    unit_price = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    # Jamais de FK Django vers `apps.accounting.models.AccTax` — purement
    # informatif en S1, aucun calcul de taxe n'est encore effectue.
    tax_id = models.UUIDField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    # Renseignes plus tard par `mrp.services.public.simulate_product_cost`
    # (gap identifie pour un lot ulterieur) — toujours nuls en S1.
    cost_estimate_mga = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    margin_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    lead_time_days = models.PositiveIntegerField(null=True, blank=True)
    # RG-SAL-3 (qualification d'origine par ligne) : le champ est ecrit des
    # S1 mais sa logique de traitement (declenchement OF/reservation stock/
    # demande d'achat) est differee a S3 (cf. plan).
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_STOCK)

    class Meta:
        db_table = "sales_quotation_line"
        ordering = ["sequence"]

    def __str__(self) -> str:
        return f"{self.description} x{self.qty}"
