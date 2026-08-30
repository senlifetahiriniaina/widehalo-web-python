"""Module `helpdesk` (HD1+HD2, cf. plan section « Module `helpdesk` —
suivi des demandes et incidents operationnels ») : suivi interne des
demandes et incidents rattaches aux operations, avec une trace ecrite
explicite des dependances vers n'importe quel enregistrement de n'importe
quel autre module (lien generique `content_type`/`object_id`, meme patron
exact que `core.models.risk.RiskItem`/`core.models.quality.QltInspection`).

**HD2** (cf. plan section « SLA et escalade ») ajoute `HlpSlaPolicy`/
`HlpSlaBreach`/`HlpEscalationRule`/`HlpEscalationEvent`, ainsi que les
champs deliberement differes par HD1 : `HlpTicketTypeCatalog.
default_sla_policy`, `HlpTicket.sla_policy`/`first_response_due_at`/
`resolution_due_at` (migration additive `AddField`, jamais une
modification retroactive des champs HD1 deja livres) — cf. docstrings de
chaque modele pour le detail.

**HD3** (cf. plan, prochaine etape apres HD2 TERMINÉ) ajoute
`HlpKbCategory`/`HlpKbArticle` (base de connaissances interne) et
`HlpResponseTemplate` (gabarits de reponse) — aucun champ nouveau sur les
modeles HD1/HD2 existants.

**HD4** ajoute `HlpCsatResponse` (enquete CSAT post-resolution simple, cf.
sa docstring) — aucun champ nouveau sur les modeles HD1-HD3 existants, et
les rapports (CSAT/performance agents/benchmarking d'equipe/conformite
SLA) sont des fonctions calculees a la volee (`services/reports.py`),
JAMAIS de nouveau modele de reporting.

**Simplifications actees et disclosed restant de HD1** :
- Le rattachement generique de `HlpTicket` (`content_type`/`object_id`)
  peut etre pre-filtre par `HlpTicketTypeCatalog.related_content_type`
  quand le type de ticket choisi en porte un — le widget de selection reste
  une simple saisie d'UUID/liste deroulante en HD1 (cf. `views.py`), un
  picker de recherche riche n'est pas requis a ce stade (disclosed comme
  simplification V1)."""

from __future__ import annotations

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.validators import MaxValueValidator, MinValueValidator
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


class HlpSlaPolicy(BaseModel):
    """Politique de SLA (HD2, cf. plan section « SLA et escalade »).
    `BaseModel` sans `ReferenceMixin` — donnee de configuration/referentiel,
    meme categorie que `CrmPipeline`/`SalesRecurrence`.

    `priority` : la priorite de `HlpTicket` a laquelle cette politique
    s'applique (memes choix exacts que `HlpTicket.priority` — jamais une
    liste de choix dupliquee independamment).

    **Simplification actee et disclosed** : decompte CONTINU (24/7), aucun
    calendrier d'heures ouvrees par tenant en V1 — meme discipline que la
    granularite hebdomadaire d'`accounting.ACC-TRESO` (`AccCashForecastLine`)
    ou le calendrier calendaire simple du CPM `projects` (jours calendaires,
    pas de jours ouvres). `presence.PrsWorkCalendar` existe deja et pourrait
    etre integre dans un futur enrichissement (hors perimetre de ce lot,
    et de toute facon `helpdesk` ne peut pas importer un modele `presence`,
    regle de couplage n°1 — un tel enrichissement devrait passer par un
    contrat public `presence.services.public`)."""

    name = models.CharField(max_length=200)
    priority = models.CharField(max_length=16, choices=PRIORITY_CHOICES)
    first_response_minutes = models.PositiveIntegerField()
    resolution_minutes = models.PositiveIntegerField()

    class Meta:
        db_table = "hlp_sla_policy"
        # RBAC (cf. plan, section dediee) : `ROLE_APP_PERMISSIONS["helpdesk"]`
        # accorde {view, add} a TOUS les 9 roles non admin/direction (cf.
        # `rbac_policy.py`) — granularite app-level, pas par modele. Le plan
        # exige pourtant que la configuration SLA/escalade reste
        # `admin`/`direction` UNIQUEMENT : meme contournement par permission
        # personnalisee que `projects.manage_prjcustomfielddefinition`
        # (PJ7)/`purchase.run_price_watch_check` (PRC3) — `manage_hlpslapolicy`
        # gate a elle seule la lecture ET l'ecriture cote API/ecran (cf.
        # `apps.helpdesk.api`), les permissions auto-generees
        # `view/add/change_hlpslapolicy` restant certes techniquement
        # accordees plus largement par la matrice app-level mais jamais
        # verifiees par aucun endpoint de configuration.
        permissions = [
            ("manage_hlpslapolicy", "Peut consulter/gerer les politiques de SLA"),
            (
                "run_helpdesk_checks",
                "Peut declencher manuellement les verifications SLA/escalade helpdesk",
            ),
        ]

    def __str__(self) -> str:
        return self.name


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

    `default_sla_policy` : ajoute en HD2 (`HlpSlaPolicy` n'existait pas en
    HD1) — cf. docstring de tete de module. `services.tickets.create_ticket`
    l'utilise comme repli si aucune politique SLA explicite n'est fournie."""

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
    # Ajoute en HD2 (migration additive `AddField`, cf. docstring de tete de
    # module HD1) : `HlpSlaPolicy` existe desormais. Meme resolution que
    # `default_priority`/`default_team` — `services.tickets.create_ticket`
    # l'utilise comme repli si aucune politique explicite n'est fournie a la
    # creation.
    default_sla_policy = models.ForeignKey(
        HlpSlaPolicy,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="default_for_types",
    )

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

    **Champs ajoutes en HD2** (migration additive, cf. docstring de tete de
    module) : `sla_policy`/`first_response_due_at`/`resolution_due_at`,
    calcules a la creation par `services.tickets.create_ticket` SI une
    politique SLA est resolue (explicite, ou `ticket_type.
    default_sla_policy`, ou par correspondance `HlpSlaPolicy.priority ==
    ticket.priority` — meme chaine de resolution exacte que
    `priority`/`team` depuis `ticket_type.default_priority`/`default_team`,
    l'appelant garde toujours le dernier mot). `risk_score` (ajoute des
    HD1) est desormais recalcule par `escalation.compute_risk_score`,
    heuristique DETERMINISTE disclosed (cf. cette fonction) — jamais un
    modele entraine."""

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

    # HD2 : etats "actifs" au sens SLA/escalade — un ticket resolu/cloture/
    # annule n'est plus surveille par `sla.check_breaches`/`escalation.
    # run_escalation_checks` (aucun sens a breacher/escalader un dossier
    # deja clos). `escalated` reste actif : un ticket escalade peut encore
    # etre escalade a nouveau par une AUTRE regle, cf. plan.
    ACTIVE_STATES = [
        STATE_NEW,
        STATE_IN_PROGRESS,
        STATE_PENDING,
        STATE_ESCALATED,
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

    sla_policy = models.ForeignKey(
        HlpSlaPolicy, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets"
    )
    first_response_due_at = models.DateTimeField(null=True, blank=True)
    resolution_due_at = models.DateTimeField(null=True, blank=True)

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


class HlpSlaBreach(BaseModel):
    """Breche de SLA constatee (HD2, `services.sla.check_breaches`).
    `BaseModel` sans `ReferenceMixin` — un evenement rattache a un ticket
    deja sequence, meme categorie que `HlpTicketComment`.

    **Idempotence garantie au niveau base** (pas seulement applicatif) :
    `UniqueConstraint(ticket, breach_type)` — jamais deux breches
    enregistrees pour le meme couple (une premiere-reponse en retard et une
    resolution en retard sur le MEME ticket sont deux breches DISTINCTES,
    chacune enregistree au plus une fois)."""

    BREACH_FIRST_RESPONSE = "first_response"
    BREACH_RESOLUTION = "resolution"
    BREACH_TYPE_CHOICES = [
        (BREACH_FIRST_RESPONSE, _("Premiere reponse")),
        (BREACH_RESOLUTION, _("Resolution")),
    ]

    ticket = models.ForeignKey(HlpTicket, on_delete=models.CASCADE, related_name="sla_breaches")
    breach_type = models.CharField(max_length=16, choices=BREACH_TYPE_CHOICES)
    breached_at = models.DateTimeField()
    minutes_over = models.PositiveIntegerField()

    class Meta:
        db_table = "hlp_sla_breach"
        constraints = [
            models.UniqueConstraint(fields=["ticket", "breach_type"], name="uniq_hlp_sla_breach")
        ]

    def __str__(self) -> str:
        return f"{self.ticket_id}: {self.breach_type}"


# Ordonnancement total des priorites pour `HlpEscalationRule` (condition
# `min_priority`) — meme constante Python que `PRIORITY_CHOICES` ci-dessus,
# un simple dict d'ordre plutot qu'un mecanisme de comparaison generique,
# suffisant pour 4 valeurs fixes.
PRIORITY_ORDER: dict[str, int] = {
    PRIORITY_LOW: 0,
    PRIORITY_NORMAL: 1,
    PRIORITY_HIGH: 2,
    PRIORITY_URGENT: 3,
}


class HlpEscalationRule(BaseModel):
    """Regle d'escalade automatique (HD2, `services.escalation.
    run_escalation_checks`). `BaseModel` sans `ReferenceMixin` — donnee de
    configuration/referentiel, meme categorie que `HlpSlaPolicy`.

    `condition_type` : `time_since_created`/`time_since_last_activity`
    utilisent `threshold_minutes` ; `sla_breach` n'utilise ni
    `threshold_minutes` ni `min_priority` (matche des qu'au moins une
    `HlpSlaBreach` existe pour le ticket) ; `min_priority` est le
    discriminant PRINCIPAL pour le type `min_priority`, mais reste
    disponible comme filtre ADDITIONNEL combinable avec N'IMPORTE QUEL
    `condition_type` (ex. une regle `time_since_created` avec
    `threshold_minutes=120` ET `min_priority="high"` n'escalade que les
    tickets haute/urgente priorite restes plus de 2h sans prise en charge)
    — cf. `services.escalation.rule_matches` pour le detail exact de cette
    combinaison, disclosed ici pour eviter toute ambiguite de lecture du
    modele seul.

    `escalate_to_team`/`escalate_to_user` : appliques sur le ticket quand
    la regle matche (cf. `run_escalation_checks`), tous deux optionnels et
    independants (une regle peut n'en renseigner aucun, l'un, l'autre, ou
    les deux)."""

    CONDITION_TIME_SINCE_CREATED = "time_since_created"
    CONDITION_TIME_SINCE_LAST_ACTIVITY = "time_since_last_activity"
    CONDITION_SLA_BREACH = "sla_breach"
    CONDITION_MIN_PRIORITY = "min_priority"
    CONDITION_TYPE_CHOICES = [
        (CONDITION_TIME_SINCE_CREATED, _("Temps depuis creation")),
        (CONDITION_TIME_SINCE_LAST_ACTIVITY, _("Temps depuis derniere activite")),
        (CONDITION_SLA_BREACH, _("Breche de SLA")),
        (CONDITION_MIN_PRIORITY, _("Priorite minimale")),
    ]

    name = models.CharField(max_length=200)
    condition_type = models.CharField(max_length=32, choices=CONDITION_TYPE_CHOICES)
    threshold_minutes = models.PositiveIntegerField(null=True, blank=True)
    min_priority = models.CharField(max_length=16, choices=PRIORITY_CHOICES, blank=True)
    escalate_to_team = models.ForeignKey(
        HlpTeam, null=True, blank=True, on_delete=models.SET_NULL, related_name="escalation_rules"
    )
    escalate_to_user = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # `is_active` reutilise le champ deja porte par `BaseModel` (soft-delete
    # ET "regle actuellement evaluee" partagent le meme booleen, meme
    # discipline que `HlpTicketTypeCatalog.is_active`) — champ dedie
    # explicitement demande par le cadrage du chantier malgre cela, pour
    # que la regle puisse etre desactivee temporairement SANS etre
    # archivee (un simple bascule reversible, distincte d'un soft-delete
    # qui la retirerait aussi de tout ecran de configuration) : les deux
    # usages restent portes par le meme champ `is_active` de `BaseModel`,
    # `run_escalation_checks` filtre explicitement dessus.

    class Meta:
        db_table = "hlp_escalation_rule"
        # Meme contournement de la granularite app-level que `HlpSlaPolicy`
        # ci-dessus, cf. sa docstring `Meta.permissions`.
        permissions = [
            ("manage_hlpescalationrule", "Peut consulter/gerer les regles d'escalade"),
        ]

    def __str__(self) -> str:
        return self.name


class HlpKbCategory(BaseModel):
    """Categorie de la base de connaissances (HD3, cf. plan section
    « État d'avancement — HD2 TERMINÉ » -> prochaine etape HD3).
    `BaseModel` sans `ReferenceMixin` — donnee de configuration/referentiel,
    meme categorie que `HlpTeam`/`HlpSlaPolicy`.

    `parent` : hierarchie auto-referencee (categorie de tete si `None`,
    sous-categorie sinon), meme discipline que `HlpTicketTypeCatalog.parent`
    ci-dessus — `on_delete=SET_NULL` (meme convention EXACTE que ce champ
    dans CE MEME app pour une hierarchie parent qui ne doit jamais bloquer
    la suppression d'une categorie de tete : ses enfants remontent
    simplement au niveau racine plutot que d'empecher l'archivage)."""

    name = models.CharField(max_length=200)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )

    class Meta:
        db_table = "hlp_kb_category"

    def __str__(self) -> str:
        return self.name


class HlpKbArticle(BaseModel):
    """Article de la base de connaissances interne (HD3). `BaseModel` sans
    `ReferenceMixin` — contenu editorial, pas un document numerote.

    `title`/`body` : texte libre, JAMAIS `gettext` — contenu REDIGE PAR LE
    TENANT (agent/expert metier), pas une chaine d'interface figee. Meme
    raisonnement exact que `HlpTicketTypeCatalog.label`.

    `view_count`/`helpful_count`/`not_helpful_count` : compteurs agreges
    simples, incrementes de facon ATOMIQUE via `F(...)` (cf. `services.kb`)
    — **simplification actee et disclosed** : aucun modele `ArticleView`
    par lecture/feedback individuel en V1 (pas d'historique nominatif de
    qui a lu/vote quoi), meme discipline d'economie que `HlpCsatResponse`
    (une seule ligne agregee par ticket, pas une serie temporelle)."""

    category = models.ForeignKey(
        HlpKbCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name="articles"
    )
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    is_published = models.BooleanField(default=False)
    author = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    view_count = models.PositiveIntegerField(default=0)
    helpful_count = models.PositiveIntegerField(default=0)
    not_helpful_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "hlp_kb_article"

    def __str__(self) -> str:
        return self.title


class HlpResponseTemplate(BaseModel):
    """Gabarit de reponse reutilisable par un agent (HD3) — remplace le
    concept « suggestion de reponse IA A/B testee » du document source par
    un mecanisme simple et deterministe (cf. plan, section modeles). Une
    suggestion de PROSE generee par IA reste possible EN COMPLEMENT
    (`services.ai_assist.suggest_reply`), jamais persistee comme un
    gabarit.

    `category` : `CharField` texte LIBRE (jamais une FK vers
    `HlpKbCategory` — deux concepts distincts, une categorisation
    LEGERE/informelle de gabarit n'a pas besoin de la hierarchie complete
    de la base de connaissances). `body` : texte libre, JAMAIS `gettext` —
    contenu redige par le tenant, meme raisonnement que `HlpKbArticle.body`."""

    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, blank=True)
    body = models.TextField(blank=True)

    class Meta:
        db_table = "hlp_response_template"

    def __str__(self) -> str:
        return self.name


class HlpEscalationEvent(BaseModel):
    """Evenement d'escalade (HD2) — historique COMPLET des escalades d'un
    ticket, manuelles et automatiques confondues. `BaseModel` sans
    `ReferenceMixin` — un evenement rattache a un ticket deja sequence.

    **Fusionne a lui seul les 4 entites du document source** (`EscalationRule`
    separee ci-dessus mise a part, `EscalationWorkflow`/`EscalationEvent`/
    `EscalationHistory` du document source Laravel n'existent PAS ici : cet
    evenement EST l'historique, aucun modele separe necessaire — meme
    discipline d'economie que `MrpBomLineState` unique plutot que plusieurs
    modeles.

    `rule` = `None` -> escalade MANUELLE (`services.tickets.
    escalate_ticket`, `escalated_by` alors renseigne a l'utilisateur
    appelant). `rule` renseigne -> escalade AUTOMATIQUE (`services.
    escalation.run_escalation_checks`, `escalated_by` alors TOUJOURS
    `None` — cf. docstring de cette fonction pour la justification exacte
    de ce choix)."""

    ticket = models.ForeignKey(
        HlpTicket, on_delete=models.CASCADE, related_name="escalation_events"
    )
    rule = models.ForeignKey(
        HlpEscalationRule, null=True, blank=True, on_delete=models.SET_NULL, related_name="events"
    )
    escalated_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reason = models.TextField(blank=True)

    class Meta:
        db_table = "hlp_escalation_event"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.ticket_id}: {'manuel' if self.rule_id is None else self.rule_id}"


class HlpCsatResponse(BaseModel):
    """Enquete de satisfaction post-resolution (HD4, cf. plan section
    modeles). `BaseModel` sans `ReferenceMixin` — un evenement rattache a
    un ticket deja sequence, meme categorie que `HlpTicketComment`/
    `HlpSlaBreach`.

    `ticket` : `OneToOneField` — AU PLUS une reponse CSAT par ticket, une
    seule enquete post-resolution simple (pas une serie temporelle), meme
    discipline d'economie que les compteurs agreges de `HlpKbArticle`
    (cf. sa docstring). La contrainte d'unicite est garantie au niveau DB
    par le `OneToOneField` lui-meme (`IntegrityError` sur un INSERT brut en
    doublon) ; `services.csat.submit_csat_response` verifie neanmoins
    explicitement `HlpCsatResponse.objects.filter(ticket=ticket).exists()`
    EN AMONT pour renvoyer une `ValidationError` a message clair plutot que
    de laisser remonter une erreur d'integrite brute a l'appelant — meme
    patron exact que la garde anti-double-facturation de
    `apps.projects.services.billing` (PJ5, `PrjInvoicingRecord`).

    **Decision de perimetre actee au cadrage (n°2)** : JAMAIS de prediction
    CSAT/NPS, JAMAIS de campagnes CSAT planifiees en V1 — une simple
    enquete par ticket, rien de plus (cf. docstring de tete de module).

    `score` : `PositiveSmallIntegerField` borne `[1, 5]` par des
    `Validators` Django (`full_clean()`/formulaires) ; la borne METIER
    reelle est cependant appliquee au niveau SERVICE
    (`services.csat.submit_csat_response`, `1 <= score <= 5`) car les
    endpoints API/ecran de ce depot n'appellent jamais `full_clean()`
    (meme discipline que tout le reste du depot — la validation vit dans
    les fonctions de service, pas dans les validateurs de champ, qui ne
    servent ici que de documentation/garde-fou pour l'admin Django)."""

    ticket = models.OneToOneField(HlpTicket, on_delete=models.CASCADE, related_name="csat_response")
    score = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    comment = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "hlp_csat_response"

    def __str__(self) -> str:
        return f"{self.ticket_id}: {self.score}/5"
