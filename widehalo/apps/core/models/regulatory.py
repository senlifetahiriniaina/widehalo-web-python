from __future__ import annotations

from django.db import models

from apps.core.db.uuid7 import uuid7


class RegulatoryParameter(models.Model):
    """Parametre reglementaire versionne par date d'effet (taux, seuil,
    bareme...) — AUCUN taux/seuil/bareme ne doit jamais etre ecrit en dur
    dans le code applicatif des futurs modules (ex. bareme IRSA du futur
    module Paie). `tenant` nul = valeur globale (defaut) ; une valeur par
    tenant, si presente, prevaut (cf. services/regulatory.py::get_parameter).

    Contrainte d'exclusion Postgres (migration dediee, extension
    `btree_gist`) : deux plages de validite ne peuvent jamais se chevaucher
    pour un meme (tenant, code)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tenant = models.ForeignKey("core.Tenant", null=True, blank=True, on_delete=models.CASCADE)
    code = models.CharField(max_length=64)
    value = models.JSONField()
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    legal_reference = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "core_regulatory_parameter"

    def __str__(self) -> str:
        return f"{self.code} ({self.valid_from} → {self.valid_to or '...'})"


class CountryDefaultsProfile(models.Model):
    """SmartDefaults par pays — preconfigure un tenant a sa creation
    (devise, TVA, fuseau, moyens de paiement...). Le plan comptable
    lui-meme (ex. PCG2005) reste une simple metadonnee informative ici :
    son chargement effectif relevera du futur module Comptabilite."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    country_code = models.CharField(max_length=2, unique=True)
    base_currency = models.CharField(max_length=3)
    default_language = models.CharField(max_length=5)
    timezone = models.CharField(max_length=64)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    chart_of_accounts_code = models.CharField(max_length=32, blank=True)
    payment_methods = models.JSONField(default=list, blank=True)
    holidays = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "core_country_defaults_profile"

    def __str__(self) -> str:
        return self.country_code
