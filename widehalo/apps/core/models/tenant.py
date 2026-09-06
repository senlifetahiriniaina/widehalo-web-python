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
    # SAL-8 (L5) : mentions legales obligatoires portees par les documents
    # legaux du tenant (facture en tete). Champ LIBRE et non pre-rempli : les
    # mentions varient par pays, par regime fiscal et par activite, et en
    # inventer un jeu par defaut ferait porter au produit une affirmation
    # juridique qu'il n'est pas en position de tenir. Le gabarit ne rend ce
    # bloc que s'il est renseigne.
    legal_mentions = models.TextField(_("mentions légales"), blank=True)
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
    # WA-5, seconde jambe (L10) : « limite de frequence PAR DESTINATAIRE ».
    # Le plafond mensuel ci-dessus protege la facture du tenant ; il ne
    # protege pas UNE personne. Un tenant au plafond large peut envoyer
    # cent messages au meme numero dans la journee sans qu'aucun compteur
    # ne s'y oppose — c'est le scenario anti-boucle que ce critere vise
    # (un automate qui se declenche en rafale, un import de campagne qui
    # contient dix fois le meme numero). Le plafond de cout ne l'attrape
    # pas : cent messages a un seul destinataire coutent autant que cent
    # messages a cent destinataires.
    #
    # `None` = aucune limite configuree, meme discipline que le plafond de
    # cout ci-dessus : l'absence de configuration ne bloque jamais, elle
    # n'autorise pas non plus implicitement l'illimite — elle attend une
    # decision. La valeur par defaut retenue (10/jour/destinataire) est une
    # decision de conception PRISE ICI, non specifiee au cadrage : assez
    # haute pour ne gener aucun usage legitime (relance, confirmation,
    # notification de livraison), assez basse pour arreter une boucle.
    whatsapp_max_messages_per_recipient_per_day = models.PositiveSmallIntegerField(
        null=True, blank=True, default=10
    )
    # WA-10 (L10) : le numero WhatsApp Business de CE tenant, tel que Meta
    # l'identifie (`phone_number_id`). C'est ce qui rend le routage
    # multi-societes reel.
    #
    # Ce qui existait avant : un `WHATSAPP_PHONE_NUMBER_ID` unique pour tout
    # le deploiement, plus un `WHATSAPP_DEFAULT_TENANT_ID` auquel TOUT
    # message entrant etait attribue. Le webhook n'inspectait jamais le
    # `phone_number_id` de l'entree Meta. Sur une instance multi-societes,
    # les messages des clients de la societe B atterrissaient donc dans le
    # fil de la societe A — et le lot precedent decrivait cela comme un
    # « routage par tenant », ce qu'il n'etait pas.
    #
    # Vide = ce tenant n'a pas de numero propre ; le webhook retombe alors
    # sur `WHATSAPP_DEFAULT_TENANT_ID`, comportement historique conserve
    # pour les deploiements mono-societe qui n'ont rien a router.
    whatsapp_phone_number_id = models.CharField(max_length=64, blank=True, default="")

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
        constraints = [
            # Deux societes ne peuvent pas revendiquer le meme numero Meta :
            # le webhook ne saurait pas a laquelle livrer, et choisirait en
            # silence. La condition exclut la chaine vide, qui signifie
            # « pas de numero propre » et vaut pour autant de tenants qu'on
            # veut (cf. commentaire du champ).
            models.UniqueConstraint(
                fields=["whatsapp_phone_number_id"],
                condition=~models.Q(whatsapp_phone_number_id=""),
                name="uniq_tenant_whatsapp_phone_number_id",
            )
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"

    def soft_delete(self) -> None:
        from django.utils import timezone as tz

        self.is_active = False
        self.archived_at = tz.now()
        self.save(update_fields=["is_active", "archived_at"])
