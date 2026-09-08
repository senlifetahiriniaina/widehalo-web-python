"""Référentiel partenaires : une entité tiers unique peut cumuler plusieurs
rôles (client, fournisseur, transporteur, sous-traitant) — pas une table par
rôle — pour éviter de dupliquer la même entreprise plusieurs fois selon la
relation commerciale."""

from __future__ import annotations

from typing import Any

from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.models.base import BaseModel, ReferenceMixin
from apps.core.services.audit import compute_field_diff
from apps.core.services.fiscal_identifiers import (
    DEFAULT_COUNTRY_CODE,
    IDENTIFIER_NIF,
    IDENTIFIER_STAT,
    validate_identifier,
    validate_partner_nif,
    validate_partner_stat,
)

# Champs suivis pour le diff d'audit (PT11) — jamais les champs internes
# `is_active`/`archived_at`/`merged_into`, qui ont deja leur propre
# semantique/ecran dedie (soft-delete, fusion de doublons).
_AUDITED_FIELDS = ("name", "nif", "stat", "roles", "credit_limit_mga")


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

    # T3 — les deux états de vérification d'un identifiant auprès du
    # référentiel (OP8). `NON_VERIFIE` est l'état normal, pas un défaut :
    # tant que personne n'a interrogé le référentiel, la valeur saisie fait
    # foi. `INTROUVABLE` est le seul état qui contredit la saisie, et il ne
    # l'efface jamais — le cahier dit « dégradation en valeur saisie », pas
    # « effacement sur désaccord ».
    VERIFICATION_NON_VERIFIE = "non_verifie"
    VERIFICATION_CONFIRME = "confirme"
    VERIFICATION_INTROUVABLE = "introuvable"
    VERIFICATION_INDISPONIBLE = "referentiel_indisponible"
    VERIFICATION_CHOICES = [
        (VERIFICATION_NON_VERIFIE, "Non vérifié"),
        (VERIFICATION_CONFIRME, "Confirmé par le référentiel"),
        (VERIFICATION_INTROUVABLE, "Introuvable au référentiel"),
        (VERIFICATION_INDISPONIBLE, "Référentiel indisponible"),
    ]

    name = models.CharField(max_length=200)
    roles = ArrayField(models.CharField(max_length=20, choices=ROLE_CHOICES), default=list)
    # T3 — `nif` cesse d'être une chaîne libre. Le format est DÉCLARÉ par
    # pays (`apps.partners.fiscal_identifiers`) et appliqué dans `save()` :
    # Django ne fait tourner les validateurs de champ que dans
    # `full_clean()`, jamais dans `save()`, et six surfaces écrivent ce
    # champ sans passer par un formulaire. Le validateur reste néanmoins
    # déclaré ici pour que les formulaires et l'OpenAPI le voient.
    nif = models.CharField(
        max_length=32, blank=True, db_index=True, validators=[validate_partner_nif]
    )
    # T3 — le numéro statistique, que le référentiel n'avait pas du tout.
    # Une administration fiscale demande les deux ; en avoir un seul rend
    # la soumission incomplète au moment où elle devient bloquante (EFA-1).
    stat = models.CharField(
        max_length=32, blank=True, db_index=True, validators=[validate_partner_stat]
    )
    # T3 — le résultat de la vérification OP8, et sa date. Deux champs et
    # non un booléen : « confirmé le 3 mars » et « jamais vérifié » sont
    # deux informations que le comptable lit différemment, et une
    # confirmation vieille de deux ans n'en est plus une.
    fiscal_verification_state = models.CharField(
        max_length=32, choices=VERIFICATION_CHOICES, default=VERIFICATION_NON_VERIFIE
    )
    fiscal_verified_at = models.DateTimeField(null=True, blank=True)

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

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Calcule un diff avant/apres sur les champs metier suivis
        (`_AUDITED_FIELDS`) et le pose en `_audit_diff` — lu de facon
        additive par le signal d'audit global (`apps.core.audit_signals`,
        PT11), aucun appel a `log_action()` ici (le signal `post_save`
        s'en charge deja pour tout `BaseModel`). Sans effet a la creation
        (`self.pk` absent avant le premier `save()`)."""
        self.nif = validate_identifier(
            self.nif, identifier=IDENTIFIER_NIF, country_code=self._country_code()
        )
        self.stat = validate_identifier(
            self.stat, identifier=IDENTIFIER_STAT, country_code=self._country_code()
        )
        if self.pk:
            old_values = type(self).all_objects.filter(pk=self.pk).values(*_AUDITED_FIELDS).first()
            if old_values is not None:
                new_values = {field: getattr(self, field) for field in _AUDITED_FIELDS}
                self._audit_diff = compute_field_diff(old_values, new_values)
                kwargs = self._forget_verdict_if_identity_changed(old_values, kwargs)
        super().save(*args, **kwargs)

    def _forget_verdict_if_identity_changed(
        self, old_values: dict[str, Any], kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        """Un verdict ne survit pas à la valeur sur laquelle il portait.

        Sans cela, corriger un NIF déclaré « introuvable au référentiel »
        laissait la fiche marquée introuvable, à sa vieille date, pour
        toujours : la file de vérification ne reprend pas les verdicts, et
        c'est voulu — redemander chaque nuit un tiers que l'administration
        dit ne pas connaître est du bruit. C'est donc la correction qui
        doit rouvrir la question, et elle seule le peut : elle est le seul
        événement qui apprend quelque chose de neuf.

        `update_fields` est complété quand il est présent : un
        `save(update_fields=["nif"])` qui remettrait l'état en mémoire sans
        l'écrire laisserait la base et l'objet en désaccord — le pire des
        deux mondes."""
        if self.fiscal_verification_state == self.VERIFICATION_NON_VERIFIE:
            return kwargs
        if old_values.get("nif") == self.nif and old_values.get("stat") == self.stat:
            return kwargs

        self.fiscal_verification_state = self.VERIFICATION_NON_VERIFIE
        self.fiscal_verified_at = None
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs = dict(kwargs)
            kwargs["update_fields"] = [
                *update_fields,
                *(
                    champ
                    for champ in ("fiscal_verification_state", "fiscal_verified_at")
                    if champ not in update_fields
                ),
            ]
        return kwargs

    def _country_code(self) -> str:
        """Le pays qui décide du format, lu sur la société.

        `Tenant.country_code` existe depuis la Phase 1 et vaut « MG » par
        défaut. Le lire ici plutôt que de figer Madagascar est ce qui rend
        EFA-7 possible plus tard — « le changement de pays du paramétrage
        bascule format, contrôles, durée d'archivage et libellés, sans
        déploiement de code »."""
        return getattr(self.tenant, "country_code", "") or DEFAULT_COUNTRY_CODE


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
