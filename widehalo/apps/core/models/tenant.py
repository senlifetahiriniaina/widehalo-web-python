from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.db.uuid7 import uuid7


class Tenant(models.Model):
    """Une societe/tenant. Racine de l'isolation multi-tenant (discriminant
    + Row-Level Security PostgreSQL, cf. apps/core/models/base.py)."""

    FISCAL_REGIME_SYNTHETIC = "synthetique"
    FISCAL_REGIME_REAL_NO_VAT = "reel_sans_tva"
    FISCAL_REGIME_REAL_WITH_VAT = "reel_avec_tva"
    FISCAL_REGIME_CHOICES = [
        (FISCAL_REGIME_SYNTHETIC, _("Synthétique (impôt forfaitaire)")),
        (FISCAL_REGIME_REAL_NO_VAT, _("Réel, sans assujettissement TVA")),
        (FISCAL_REGIME_REAL_WITH_VAT, _("Réel, avec assujettissement TVA")),
    ]

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(_("raison sociale"), max_length=255)
    nif = models.CharField(_("NIF"), max_length=32, blank=True)
    country_code = models.CharField(max_length=2, default="MG")
    base_currency = models.CharField(max_length=3, default="MGA")
    default_language = models.CharField(max_length=5, default="fr")
    timezone = models.CharField(max_length=64, default="Indian/Antananarivo")
    retention_policy = models.JSONField(default=dict, blank=True)
    fiscal_regime = models.CharField(
        max_length=16, choices=FISCAL_REGIME_CHOICES, default=FISCAL_REGIME_REAL_WITH_VAT
    )
    # ACC-SMT1/A8 (§1.6 du document annexe) : depuis la Loi de Finances 2026,
    # un tenant dont le chiffre d'affaires annuel reel se situe dans la
    # tranche 200-400 M Ar peut OPTER pour l'assujettissement a la TVA
    # (jusque-la automatiquement non assujetti dans cette tranche). Ce champ
    # est INDEPENDANT de `fiscal_regime` : il n'a de sens que pour un tenant
    # dont le CA reel tombe dans cette tranche precise, mais `core` ne
    # calcule volontairement pas ce CA lui-meme (cela supposerait une
    # dependance de `core` vers `accounting`, qu'aucune regle de couplage du
    # projet n'autorise) — c'est au tenant/comptable de positionner ce
    # booleen a bon escient, et a un futur ecran de configuration fiscale
    # (module accounting) de guider ce choix une fois le CA reel connu
    # (cf. ACC-CR, phase 2 A9). Valeur par defaut `False` (non assujetti,
    # comportement historique) tant que l'option n'a pas ete exercee.
    # Reserve OECFM/DGI (§0.5, §3.5 du document annexe) : la tranche 200-
    # 400 M Ar et le caractere optionnel de la TVA qui s'y attache sont
    # repris d'un document non primaire — a confirmer aupres d'un expert-
    # comptable OECFM ou de la DGI avant tout usage en production reelle.
    vat_opted_in = models.BooleanField(default=False)

    # Chantier "profil de l'entreprise" (marque sur le PDF devis/commande,
    # cf. plan) : aucun de ces 4 champs n'existait avant ce lot, seuls
    # `name`/`nif` etaient presents. `logo` est un vrai `ImageField` DEDIE
    # — pas une reutilisation du magasin polymorphe `core.Document` (qui,
    # lui, rattache deja des archives de sauvegarde a ce meme `Tenant` via
    # `content_object`, cf. `apps.core.services.tenant_backup`; resoudre
    # "le dernier Document rattache au tenant" entrerait directement en
    # collision avec ces archives) — deviation volontaire du patron
    # `PrsEmployee`/photo (`apps.presence.models`, qui reutilise `Document`
    # car aucune collision n'y est possible). Tous blank/null : additif,
    # aucune donnee existante affectee.
    logo = models.ImageField(upload_to="tenant_logos/", null=True, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    email = models.CharField(max_length=254, blank=True)

    # Gouvernance WhatsApp (WA-5, cahier Phase 2 §13.4) : plafond de cout
    # mensuel PAR TENANT — champs ajoutes ici plutot qu'un modele
    # `WaUsageLimit` dedie dans `apps.whatsapp` (budget d'architecture
    # `tests/architecture/test_budget.py` deja a 288/290 avant ce chantier,
    # « jamais releve sans decision explicite du commanditaire » —
    # cf. docstring `apps.whatsapp.models`). `None` = aucun plafond
    # configure (jamais un plafond implicite a 0 qui bloquerait tout envoi
    # par defaut).
    whatsapp_monthly_cost_cap_ariary = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    whatsapp_cost_cap_hard_stop = models.BooleanField(default=True)
    whatsapp_cost_alert_threshold_pct = models.PositiveSmallIntegerField(default=80)

    is_sandbox = models.BooleanField(default=False)
    sandbox_source = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="sandboxes"
    )
    sandbox_expires_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_tenant"
        verbose_name = _("société")
        verbose_name_plural = _("sociétés")

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"

    def soft_delete(self) -> None:
        from django.utils import timezone as tz

        self.is_active = False
        self.archived_at = tz.now()
        self.save(update_fields=["is_active", "archived_at"])
