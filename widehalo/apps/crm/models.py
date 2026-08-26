"""Relation commerciale (§5.2) : pipelines/etapes, opportunites a saisie
rapide, activites, equipes. La conversion vers un devis/proforma/commande
reel (RG-CRM-4) et le controle de faisabilite MRP/Stocks (RG-CRM-7) sont
differes a quand les modules `sales`/`mrp`/`stocks` existeront (cf. plan) —
`crm` ne les importe donc jamais, meme via services.public."""

from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.models.base import BaseModel, ReferenceMixin


class CrmPipeline(BaseModel):
    name = models.CharField(max_length=100)
    is_default = models.BooleanField(default=False)

    class Meta:
        db_table = "crm_pipeline"

    def __str__(self) -> str:
        return self.name


class CrmStage(BaseModel):
    pipeline = models.ForeignKey(CrmPipeline, on_delete=models.CASCADE, related_name="stages")
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=100)
    sequence = models.PositiveSmallIntegerField(default=0)
    probability = models.PositiveSmallIntegerField(default=0, help_text="0-100")
    is_won = models.BooleanField(default=False)
    is_lost = models.BooleanField(default=False)
    requires_reason = models.BooleanField(default=False)

    class Meta:
        db_table = "crm_stage"
        ordering = ["sequence"]

    def __str__(self) -> str:
        return f"{self.pipeline.name}:{self.code}"


class CrmTeam(BaseModel):
    name = models.CharField(max_length=100)
    leader = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    members = models.ManyToManyField("core.User", blank=True, related_name="crm_teams")
    target_mga_month = models.DecimalField(max_digits=18, decimal_places=4, default=0)

    class Meta:
        db_table = "crm_team"

    def __str__(self) -> str:
        return self.name


class CrmLostReason(BaseModel):
    name = models.CharField(max_length=120)

    class Meta:
        db_table = "crm_lost_reason"

    def __str__(self) -> str:
        return self.name


class CrmLead(BaseModel, ReferenceMixin):
    PRIORITY_LOW = "low"
    PRIORITY_MEDIUM = "medium"
    PRIORITY_HIGH = "high"
    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Basse"),
        (PRIORITY_MEDIUM, "Moyenne"),
        (PRIORITY_HIGH, "Haute"),
    ]

    name = models.CharField(max_length=200)
    # Jamais de FK Django vers `apps.partners.models.Partner` (regle de
    # couplage n°1) — un tiers est reference par son UUID uniquement.
    partner_id = models.UUIDField(null=True, blank=True)
    contact_name = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    source = models.CharField(max_length=64, blank=True)
    campaign = models.CharField(max_length=64, blank=True)
    pipeline = models.ForeignKey(CrmPipeline, on_delete=models.PROTECT, related_name="leads")
    stage = models.ForeignKey(CrmStage, on_delete=models.PROTECT, related_name="leads")
    expected_revenue_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    probability = models.PositiveSmallIntegerField(default=0)
    expected_close_date = models.DateField(null=True, blank=True)
    salesperson = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    team = models.ForeignKey(
        CrmTeam, null=True, blank=True, on_delete=models.SET_NULL, related_name="leads"
    )
    priority = models.CharField(max_length=16, choices=PRIORITY_CHOICES, default=PRIORITY_MEDIUM)
    tags = ArrayField(models.CharField(max_length=32), default=list, blank=True)
    description = models.TextField(blank=True)
    lost_reason = models.ForeignKey(
        CrmLostReason, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    lost_comment = models.TextField(blank=True)
    won_at = models.DateTimeField(null=True, blank=True)
    lost_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "crm_lead"

    def __str__(self) -> str:
        return f"{self.reference or self.id} — {self.name}"


class CrmLeadLine(BaseModel):
    lead = models.ForeignKey(CrmLead, on_delete=models.CASCADE, related_name="lines")
    # Jamais de FK Django vers `apps.catalog.models.ProductVariant` — un
    # article est reference par son UUID, resolu via `catalog.services.public`.
    variant_id = models.UUIDField(null=True, blank=True)
    description = models.CharField(max_length=255)
    qty = models.DecimalField(max_digits=18, decimal_places=4, default=1)
    uom_code = models.CharField(max_length=16, blank=True)
    unit_price = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    subtotal = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    note = models.CharField(max_length=255, blank=True)
    sequence = models.PositiveSmallIntegerField(default=0)
    # RG-CRM-2 : ligne "hors catalogue" (designation libre + prix) — declenche
    # une demande de creation produit aupres du responsable produit si
    # l'opportunite est gagnee (cf. services/leads.py::win_lead()).
    is_custom = models.BooleanField(default=False)

    class Meta:
        db_table = "crm_lead_line"
        ordering = ["sequence"]

    def __str__(self) -> str:
        return f"{self.description} x{self.qty}"
