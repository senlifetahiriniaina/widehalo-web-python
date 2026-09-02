"""Référentiel partenaires : une entité tiers unique peut cumuler plusieurs
rôles (client, fournisseur, transporteur, sous-traitant) — pas une table par
rôle — pour éviter de dupliquer la même entreprise plusieurs fois selon la
relation commerciale."""

from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.models.base import BaseModel, ReferenceMixin


class Partner(BaseModel, ReferenceMixin):
    ROLE_CLIENT = "client"
    ROLE_SUPPLIER = "supplier"
    ROLE_CARRIER = "carrier"
    ROLE_SUBCONTRACTOR = "subcontractor"
    ROLE_ASSOCIATE = "associate"
    ROLE_COLLABORATOR = "collaborator"
    ROLE_BANK = "bank"
    ROLE_CHOICES = [
        (ROLE_CLIENT, "Client"),
        (ROLE_SUPPLIER, "Fournisseur"),
        (ROLE_CARRIER, "Transporteur"),
        (ROLE_SUBCONTRACTOR, "Sous-traitant"),
        (ROLE_ASSOCIATE, "Associé"),
        (ROLE_COLLABORATOR, "Collaborateur"),
        (ROLE_BANK, "Banque"),
    ]

    name = models.CharField(max_length=200)
    roles = ArrayField(models.CharField(max_length=20, choices=ROLE_CHOICES), default=list)
    nif = models.CharField(max_length=32, blank=True, db_index=True)

    credit_limit_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)

    @property
    def roles_display(self) -> str:
        labels = dict(self.ROLE_CHOICES)
        return ", ".join(labels.get(role, role) for role in self.roles) or "—"

    # Partenaire generique cree par
    # `apps.partners.services.defaults.ensure_default_partner` quand un
    # import n'a pas identifie avec certitude le partenaire reel (chantier
    # RG-QUALIF) — une ligne qui l'utilise reste `needs_qualification`
    # jusqu'a remplacement par le vrai partenaire.
    is_placeholder = models.BooleanField(default=False)

    # Fusion de doublons : conserve une trace du partenaire absorbe (soft-delete
    # applique dessus) plutot que de le supprimer physiquement — l'audit du
    # rattachement des FK reste dans core_audit_log via les save() individuels.
    merged_into = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="absorbed"
    )

    class Meta:
        db_table = "partners_partner"
        indexes = [models.Index(fields=["nif"])]

    def __str__(self) -> str:
        return f"{self.reference} — {self.name}"


class DuplicateAlert(BaseModel):
    """Alerte non bloquante levee quand deux partenaires du meme tenant
    partagent le meme NIF — l'utilisateur reste libre de creer volontairement
    plusieurs fiches (succursales distinctes, erreur de saisie a corriger
    plus tard...), on ne bloque jamais silencieusement la creation."""

    partner = models.ForeignKey(Partner, on_delete=models.CASCADE, related_name="+")
    duplicate_of = models.ForeignKey(Partner, on_delete=models.CASCADE, related_name="+")
    matched_field = models.CharField(max_length=32, default="nif")
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "partners_duplicate_alert"


class PartnerContact(BaseModel):
    """Personne de contact rattachee a un partenaire (chantier fiche
    partenaire a onglets) — sous-enregistrement simple, pas `ReferenceMixin`
    (meme categorie que `PrjTeamMember`/`HlpTicketComment`, aucun besoin de
    numero de document). `role` vide = contact general, visible sur TOUS
    les onglets du partenaire ; `role` renseigne (une valeur de
    `Partner.ROLE_CHOICES`) = contact scope au seul onglet correspondant."""

    partner = models.ForeignKey(Partner, on_delete=models.CASCADE, related_name="contacts")
    full_name = models.CharField(max_length=200)
    role = models.CharField(max_length=20, choices=Partner.ROLE_CHOICES, blank=True)
    title = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        db_table = "partners_contact"

    def __str__(self) -> str:
        return self.full_name
