"""Module `whatsapp` (gouvernance WhatsApp Business, cahier Phase 2
§13.4) — construit EXPLICITEMENT comme une couche de gouvernance
au-dessus de l'infrastructure d'envoi/reception deja existante dans
`core` (`apps.core.models.notification.WhatsAppMessage`, `apps.core.
services.whatsapp.get_whatsapp_client`), jamais une refonte : « adaptateur,
pas refonte » est une decision actee du cahier (§1), deja respectee par le
socle existant (audit 2026-09, §6) et reconduite ici.

**Budget d'architecture (2 modeles seulement)** : `WaMessageTemplate` et
`WaConversation` sont les 2 SEULS nouveaux modeles de ce chantier — un
plafond de 290 modeles est deja atteint a 288/290 avant ce chantier
(garde-fou `tests/architecture/test_budget.py`, « jamais releve sans
decision explicite du commanditaire »). Deux capacites du cahier qui
auraient naturellement appele leur propre modele sont donc deliberement
repliees ailleurs plutot que d'ajouter 2 modeles supplementaires :
- **Consentement (WA-1/WA-2)** : replie directement sur `WaConversation`
  (meme grain naturel qu'une conversation — 1 numero = 1 consentement),
  etat COURANT uniquement (pas de table d'historique dediee) : chaque
  ecrasement de `consent_granted_at`/`consent_revoked_at` est deja
  capture par le journal d'audit automatique (`apps.core.audit_signals`,
  `WaConversation` herite de `BaseModel`) — meme discipline que
  `StgRisk.last_reassessed_at` (module `strategy`, meme chantier de
  remediation).
- **Plafond de cout mensuel PAR TENANT (WA-5)** : replie sur 3 CHAMPS
  ajoutes directement a `core.Tenant` (migration dediee dans `apps/core/
  migrations/`), plutot qu'un modele `WaUsageLimit` dedie — un champ
  ajoute a un modele existant ne coute rien au budget de modeles
  (seules les classes de modele comptent), et `Tenant` porte deja des
  champs de configuration specifiques a un domaine metier (`fiscal_regime`,
  `retention_policy`) malgre son appartenance a `core` — precedent direct
  pour ce choix."""

from __future__ import annotations

import datetime
from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models.base import BaseModel

# Fenetre de service WhatsApp Business (regle imposee par la plateforme,
# pas par ce lot) : un message hors modele (« session message ») n'est
# autorisable que dans les 24h suivant le dernier message ENTRANT du
# client ; passe ce delai, seul un modele APPROUVE peut relancer la
# conversation (WA-3).
SERVICE_WINDOW = datetime.timedelta(hours=24)


class WaMessageTemplate(BaseModel):
    """Bibliotheque de modeles de message avec statut d'approbation (WA-3)
    — categories alignees sur celles reellement imposees par Meta
    (marketing/utility/authentication), jamais inventees. Un modele ne
    peut etre utilise pour un envoi (`services/messaging.py::
    send_governed_template_message`) que si `status == STATUS_APPROVED` —
    verifie systematiquement a l'envoi, jamais seulement a l'affichage.

    **Approbation : machine a etats dediee, pas `core.services.
    approvals.ApprovalRule`** (simplification assumee et disclosee) :
    l'approbation d'un modele est une decision a UNE seule etape par
    admin/direction, jamais une chaine sequentielle multi-role avec
    delegation/escalade — le mecanisme generique existe et reste
    disponible pour une extension future si un besoin reel de chaine
    d'approbation apparait, mais l'utiliser ici aurait importe une
    machinerie (delegation, escalade temporisee) sans aucun consommateur
    reel."""

    CATEGORY_MARKETING = "marketing"
    CATEGORY_UTILITY = "utility"
    CATEGORY_AUTHENTICATION = "authentication"
    CATEGORY_CHOICES = [
        (CATEGORY_MARKETING, _("Marketing")),
        (CATEGORY_UTILITY, _("Utilitaire")),
        (CATEGORY_AUTHENTICATION, _("Authentification")),
    ]

    STATUS_DRAFT = "draft"
    STATUS_PENDING_REVIEW = "pending_review"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_DRAFT, _("Brouillon")),
        (STATUS_PENDING_REVIEW, _("En attente de validation")),
        (STATUS_APPROVED, _("Approuvé")),
        (STATUS_REJECTED, _("Rejeté")),
    ]

    # Code stable reference par `services/messaging.py`/`services/inbound.py`
    # (jamais l'UUID `id`, plus lisible dans un formulaire d'envoi) — unique
    # PAR TENANT (contrainte ci-dessous), jamais globalement.
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES)
    language = models.CharField(max_length=8, default="fr")
    body_text = models.TextField()
    # Noms de variables attendues dans `body_text` (ex. ["nom_client",
    # "montant"]) — informatif uniquement, jamais interprete comme du code
    # executable (meme discipline que `AnMetricDefinition.formule`).
    variables = models.JSONField(default=list, blank=True)
    # Estimation du cout d'un envoi de ce modele — utilisee par WA-5 pour
    # projeter/plafonner le cout mensuel AVANT chaque envoi (le cout REEL
    # facture par Meta n'est connu qu'a posteriori, hors API de ce lot :
    # simplification assumee et disclosee, cf. docstring `services/usage.py`).
    estimated_cost_ariary = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal(0))
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    rejection_reason = models.TextField(blank=True)

    class Meta:
        db_table = "wa_message_template"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"], name="uniq_wa_message_template_code_per_tenant"
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class WaConversation(BaseModel):
    """Fil de conversation par numero de telephone (WA-6/WA-7/WA-8) —
    porte aussi l'etat de consentement courant (WA-1/WA-2, cf. docstring
    de module) et la fenetre de service WhatsApp (WA-3).

    `chat_channel_id` : identifiant (str) du `ChatChannel` generique ouvert
    via `apps.chat.services.public.get_or_create_document_channel` — jamais
    l'objet ORM (regle de couplage n°1), stocke ici plutot que resolu a
    chaque acces pour eviter un aller-retour supplementaire vers `chat` a
    chaque affichage de la liste des conversations."""

    INTENT_NONE = "none"
    INTENT_MENU_SENT = "menu_sent"
    INTENT_AWAITING_HUMAN = "awaiting_human"
    INTENT_RESOLVED = "resolved"
    INTENT_CHOICES = [
        (INTENT_NONE, _("Aucun")),
        (INTENT_MENU_SENT, _("Menu envoyé")),
        (INTENT_AWAITING_HUMAN, _("En attente d'un humain")),
        (INTENT_RESOLVED, _("Résolu")),
    ]

    phone_number = models.CharField(max_length=32)
    chat_channel_id = models.CharField(max_length=64, blank=True)
    # WA-8 : menu d'intentions BORNE (nombre fini d'etats explicites),
    # jamais un moteur NLU/dialogue ouvert.
    intent_state = models.CharField(max_length=16, choices=INTENT_CHOICES, default=INTENT_NONE)
    last_inbound_at = models.DateTimeField(null=True, blank=True)
    last_outbound_at = models.DateTimeField(null=True, blank=True)

    # Consentement courant (WA-1/WA-2) — cf. docstring de module pour la
    # justification du repli sur ce modele plutot qu'un `WaConsent` dedie.
    consent_granted_at = models.DateTimeField(null=True, blank=True)
    consent_revoked_at = models.DateTimeField(null=True, blank=True)
    consent_source = models.CharField(max_length=100, blank=True)
    consent_granted_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "wa_conversation"
        ordering = ["-last_inbound_at", "-last_outbound_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "phone_number"], name="uniq_wa_conversation_phone_per_tenant"
            )
        ]
        permissions = [
            (
                "run_message_retry",
                "Peut relancer l'envoi des messages WhatsApp en échec (WA-7)",
            )
        ]

    def __str__(self) -> str:
        return self.phone_number

    def has_active_consent(self) -> bool:
        """WA-1/WA-2 : consentement actif = accorde et jamais revoque
        DEPUIS ce dernier octroi (un octroi posterieur a une revocation
        reactive le consentement, cf. `services/consent.py::grant_consent`,
        qui efface toujours `consent_revoked_at` a un nouvel octroi)."""
        return self.consent_granted_at is not None and self.consent_revoked_at is None

    def is_service_window_open(self) -> bool:
        """WA-3 : fenetre de service de 24h suivant le dernier message
        ENTRANT — condition d'envoi d'un message HORS modele (« session
        message »), independante du consentement marketing (une reponse
        du service client dans la fenetre est une reponse au client, pas
        une sollicitation)."""
        if self.last_inbound_at is None:
            return False
        return timezone.now() - self.last_inbound_at < SERVICE_WINDOW
