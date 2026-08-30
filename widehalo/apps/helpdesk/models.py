"""Module `helpdesk` (HD1, cf. plan section « Module `helpdesk` — suivi des
demandes et incidents operationnels ») : suivi interne des demandes et
incidents rattaches aux operations, avec une trace ecrite explicite des
dependances vers n'importe quel enregistrement de n'importe quel autre
module (lien generique `content_type`/`object_id`, meme patron exact que
`core.models.risk.RiskItem`/`core.models.quality.QltInspection`).

**Simplifications actees et disclosed pour HD1** (cf. plan, sous-
sequencement HD0-HD6) :
- `HlpTicketTypeCatalog.default_sla_policy` et `HlpTicket.sla_policy` sont
  DELIBEREMENT ABSENTS de ce premier lot : ils pointeraient vers
  `HlpSlaPolicy`, qui n'existe pas avant HD2. **HD2 les ajoutera par une
  migration additive** (`AddField`), jamais une modification retroactive de
  ce fichier avant coup.
- `HlpTicket.first_response_due_at`/`resolution_due_at` sont egalement
  DIFFERES a HD2 (leur calcul depend d'`HlpSlaPolicy`, qui n'existe pas
  encore). En revanche `first_responded_at`/`resolved_at`/`closed_at` sont
  ajoutes des HD1 : ils sont deja pleinement significatifs sans aucune
  politique SLA (poses par le simple fait qu'un premier commentaire non
  interne existe, ou qu'une transition FSM a eu lieu).
- `HlpTicket.risk_score` est ajoute des HD1 (`PositiveSmallIntegerField`,
  defaut 0) mais reste a 0 jusqu'a HD2 : sa fonction de calcul
  deterministe (`escalation.compute_risk_score`, facteurs bases sur les
  brèches SLA) n'existe pas encore — jamais une valeur inventee en
  attendant.
- Le rattachement generique de `HlpTicket` (`content_type`/`object_id`)
  peut etre pre-filtre par `HlpTicketTypeCatalog.related_content_type`
  quand le type de ticket choisi en porte un — le widget de selection reste
  une simple saisie d'UUID/liste deroulante en HD1 (cf. `views.py`), un
  picker de recherche riche n'est pas requis a ce stade (disclosed comme
  simplification V1)."""

from __future__ import annotations

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_fsm import FSMField, transition

from apps.core.models.base import BaseModel, ReferenceMixin

# Memes 5 codes secteur que `apps.strategy.models.SECTOR_CHOICES`/
# `apps.catalog.models.CatalogSectorSpec.SECTOR_CHOICES` (chantier
# « Extension sectorielle Madagascar ») — constantes Python distinctes
# plutot qu'un import (regle de couplage n°1 : jamais d'import de modele
# cross-app, meme pour une simple liste de choix), les chaines doivent
# rester identiques par convention documentee.
SECTOR_TEXTILE = "textile"
SECTOR_LEATHER = "cuir"
SECTOR_AGRIFOOD = "agroalimentaire"
SECTOR_IMPORT_EXPORT = "import_export"
SECTOR_CRAFT = "artisanat"
SECTOR_CHOICES = [
    (SECTOR_TEXTILE, _("Textile")),
    (SECTOR_LEATHER, _("Cuir et maroquinerie")),
    (SECTOR_AGRIFOOD, _("Agroalimentaire")),
    (SECTOR_IMPORT_EXPORT, _("Import-export generaliste")),
    (SECTOR_CRAFT, _("Artisanat")),
]

KIND_DEMANDE = "demande"
KIND_INCIDENT = "incident"
KIND_CHOICES = [
    (KIND_DEMANDE, _("Demande")),
    (KIND_INCIDENT, _("Incident")),
]

PRIORITY_LOW = "low"
PRIORITY_NORMAL = "normal"
PRIORITY_HIGH = "high"
PRIORITY_URGENT = "urgent"
PRIORITY_CHOICES = [
    (PRIORITY_LOW, _("Basse")),
    (PRIORITY_NORMAL, _("Normale")),
    (PRIORITY_HIGH, _("Haute")),
    (PRIORITY_URGENT, _("Urgente")),
]


class HlpTeam(BaseModel):
    """Equipe de traitement des tickets (support, informatique, qualite...).
    `BaseModel` sans `ReferenceMixin` — donnee de configuration/referentiel,
    pas un document numerote, meme categorie que `CrmPipeline`.

    `members` : simple `ManyToManyField` direct, pas de modele
    d'appartenance dedie (aucun attribut supplementaire par membre n'est
    necessaire) — meme choix deja fait pour `CatalogCertification.
    compatible_materials`."""

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    members = models.ManyToManyField("core.User", blank=True, related_name="helpdesk_teams")

    class Meta:
        db_table = "hlp_team"

    def __str__(self) -> str:
        return self.name


class HlpTicketTypeCatalog(BaseModel):
    """Catalogue de types et sous-types de demandes/incidents, connecte
    nativement aux operations (extension actee en cours de route, cf.
    docstring de tete de module et section dediee du plan).

    Un seul modele flexible plutot que deux rigides (`HlpRequestType`/
    `HlpIncidentType`) : le discriminant `kind` + la hierarchie `parent`
    auto-referencee (type de tete si `None`, sous-type sinon) suffisent —
    meme discipline d'economie que `CatalogSectorSpec`/`MrpBomLineState`.

    `label` : texte libre, JAMAIS `gettext` — donnee de catalogue editable
    par tenant (chaque tenant peut renommer/ajouter ses propres entrees),
    pas une chaine d'interface figee. Meme raisonnement que
    `CrmPipeline.name`/`AccTax.name`.

    `related_content_type` : LE mecanisme concret de « connexion native aux
    operations » — quand renseigne (ex. le type « Rupture de stock matiere
    premiere » pointe vers `stocks.StkQuant`), l'ecran/API de creation de
    ticket l'utilise pour pre-filtrer le selecteur d'enregistrement du champ
    generique `content_type`/`object_id` de `HlpTicket`. `ContentType` est
    une table Django generique/agnostique (meme mecanisme deja utilise par
    `RiskItem`/`QltInspection`/`Document`) : la referencer par FK ne
    declare AUCUNE dependance vers l'app proprietaire du modele cible.

    `related_module` : simple `CharField` PUREMENT DOCUMENTAIRE/INDICATIF
    (ex. `"stocks"`/`"purchase"`/`"mrp"`) — `helpdesk` ne depend et
    n'importera jamais un modele de ces modules (regle de couplage n°1).

    `is_active` : reutilise le champ deja porte par `BaseModel`, pas de
    second champ dedie — meme discipline que `PurReorderingRule` (le
    soft-delete standard ET le sens metier "entree actuellement proposee a
    la creation d'un ticket" partagent le meme booleen).

    **Champ differe a HD2** : `default_sla_policy` (FK `HlpSlaPolicy`, qui
    n'existe pas encore) — cf. docstring de tete de module."""

    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )
    code = models.CharField(max_length=100)
    label = models.CharField(max_length=200)
    sector_code = models.CharField(max_length=32, choices=SECTOR_CHOICES, blank=True)
    related_module = models.CharField(max_length=32, blank=True)
    related_content_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    default_team = models.ForeignKey(
        HlpTeam, null=True, blank=True, on_delete=models.SET_NULL, related_name="default_for_types"
    )
    default_priority = models.CharField(max_length=16, choices=PRIORITY_CHOICES, blank=True)

    class Meta:
        db_table = "hlp_ticket_type_catalog"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_hlp_ticket_type_code")
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.label}"


class HlpTicket(BaseModel, ReferenceMixin):
    """Ticket de suivi operationnel (demande ou incident), sequence
    (`HLP-<annee>-<numero>`, cf. `apps.core.services.sequences.
    next_reference`). Machine a etats complete (`django-fsm-2`,
    `attempt_transition()` du socle — jamais un appel direct a une methode
    `@transition`, meme discipline que `PurOrder`/`SalesOrder`/
    `LogShipment`).

    Cycle : `new -> in_progress -> pending <-> in_progress -> resolved ->
    closed`, branches `escalated`/`cancelled` accessibles depuis
    `new`/`in_progress`/`pending`, et `reopen` ramene un ticket
    `resolved`/`closed` a `in_progress`.

    **`escalate()` en HD1** : la transition et sa garde d'usage
    (declenchement manuel par un utilisateur) sont pleinement operantes des
    ce premier lot — seule l'integration automatique avec des regles
    d'escalade/SLA (`HlpEscalationRule`, HD2) reste a cabler ensuite. Une
    escalade manuelle est deja une action metier significative sans cette
    automatisation.

    **Champs differes a HD2** (cf. docstring de tete de module) :
    `sla_policy`, `first_response_due_at`, `resolution_due_at`.
    `first_responded_at`/`resolved_at`/`closed_at`/`risk_score` sont en
    revanche ajoutes des HD1 (cf. meme docstring pour le detail)."""

    SEQUENCE_CODE = "HLP"

    STATE_NEW = "new"
    STATE_IN_PROGRESS = "in_progress"
    STATE_PENDING = "pending"
    STATE_RESOLVED = "resolved"
    STATE_CLOSED = "closed"
    STATE_ESCALATED = "escalated"
    STATE_CANCELLED = "cancelled"
    STATE_CHOICES = [
        (STATE_NEW, _("Nouveau")),
        (STATE_IN_PROGRESS, _("En cours")),
        (STATE_PENDING, _("En attente")),
        (STATE_RESOLVED, _("Resolu")),
        (STATE_CLOSED, _("Cloture")),
        (STATE_ESCALATED, _("Escalade")),
        (STATE_CANCELLED, _("Annule")),
    ]

    subject = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    ticket_type = models.ForeignKey(
        HlpTicketTypeCatalog,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="tickets",
    )
    priority = models.CharField(max_length=16, choices=PRIORITY_CHOICES, default=PRIORITY_NORMAL)
    state = FSMField(default=STATE_NEW, choices=STATE_CHOICES)

    requester = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="helpdesk_tickets_requested"
    )
    assignee = models.ForeignKey(
        "core.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="helpdesk_tickets_assigned",
    )
    team = models.ForeignKey(
        HlpTeam, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets"
    )

    content_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    object_id = models.CharField(max_length=64, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")

    blocks_operations = models.BooleanField(default=False)

    first_responded_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # Remplace la "prediction d'escalade" par ML du document source
    # (decision de perimetre n°2, cf. plan) : reste a 0 jusqu'a HD2, ou
    # `escalation.compute_risk_score(ticket)` (fonction deterministe) le
    # recalcule periodiquement. Jamais une valeur inventee entre-temps.
    risk_score = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "hlp_ticket"
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self) -> str:
        return self.reference or str(self.id)

    @transition(field=state, source=STATE_NEW, target=STATE_IN_PROGRESS)
    def assign(self) -> None:
        pass

    @transition(field=state, source=STATE_IN_PROGRESS, target=STATE_PENDING)
    def request_more_info(self) -> None:
        pass

    @transition(field=state, source=STATE_PENDING, target=STATE_IN_PROGRESS)
    def resume(self) -> None:
        pass

    @transition(field=state, source=[STATE_IN_PROGRESS, STATE_PENDING], target=STATE_RESOLVED)
    def resolve(self) -> None:
        pass

    # Simplification assumee (meme discipline que `PurOrder.resolve_
    # dispute`) : quel que soit l'etat d'origine (resolu ou deja cloture),
    # la reouverture ramene toujours le ticket a `in_progress` — pas de
    # machine "retour a l'etat precedent" generique dans ce socle.
    @transition(field=state, source=[STATE_RESOLVED, STATE_CLOSED], target=STATE_IN_PROGRESS)
    def reopen(self) -> None:
        pass

    @transition(field=state, source=STATE_RESOLVED, target=STATE_CLOSED)
    def close(self) -> None:
        pass

    @transition(
        field=state,
        source=[STATE_NEW, STATE_IN_PROGRESS, STATE_PENDING],
        target=STATE_ESCALATED,
    )
    def escalate(self) -> None:
        pass

    @transition(
        field=state,
        source=[STATE_NEW, STATE_IN_PROGRESS, STATE_PENDING],
        target=STATE_CANCELLED,
    )
    def cancel(self) -> None:
        pass


class HlpTicketComment(BaseModel):
    """Message du fil de suivi d'un ticket (mise a jour visible ou note
    interne). `BaseModel` sans `ReferenceMixin` — un evenement rattache a un
    ticket deja sequence, pas lui-meme un document a numeroter.

    `attachment` : meme patron exact que `ChatMessage.attachment`."""

    ticket = models.ForeignKey(HlpTicket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    body = models.TextField()
    is_internal_note = models.BooleanField(default=False)
    attachment = models.ForeignKey(
        "core.Document", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "hlp_ticket_comment"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.ticket_id}: {self.body[:30]}"
