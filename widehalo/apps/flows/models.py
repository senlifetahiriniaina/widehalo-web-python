"""Socle du hub de flux (Phase 4, bloc A, sprint S1).

**Ce que ce module modelise, et l'ordre dans lequel il faut le lire.** Le
cahier Phase 4 pose une seule realite nouvelle — l'ECHANGE — et la decline :
« tout echange entrant ou sortant [...] est une ligne de la meme table,
orientee, datee, empreintee, correlee a sa piece metier et rejouable. C'est
au flux ce que le mouvement est au stock en Phase 3 : la seule verite. Un
adaptateur qui n'ecrit pas dans le registre n'est pas un connecteur, c'est
une fuite. »

Les sept autres entites existent pour servir celle-la : ce qu'on appelle
(`FlwConnector`), avec quoi on s'authentifie (`FlwCredential`), pour quel
tenant et vers quelle destination (`FlwLink`), comment on traduit les champs
(`FlwMapping`), quand on part (`FlwSchedule`), sur quel evenement
(`FlwTrigger`), et ce qu'on a reellement transmis (`FlwPayload`).

**Pourquoi ce module n'importe aucun modele metier.** Le hub ne connait pas
`sales`, ni `accounting`, ni `whatsapp` : un echange designe sa piece metier
par un couple `(document_type, document_id)` OPAQUE, jamais par une cle
etrangere. Une FK vers `AccMove` obligerait `flows` a dependre de
`accounting`, puis de tous les modules qui emettent un echange — le socle
deviendrait un neuvieme module couple aux huit autres, ce que la decision
structurante n°2 du cahier interdit explicitement. C'est le meme choix que
`StgObjective.department_id` et `WhatsAppMessage.conversation_id`, deja
pratique ailleurs dans ce depot.

**Trois decisions de conception prises ici, et leur motif.**

1. *La charge utile est une table SEPAREE, pas un champ de l'echange.*
   FLX-5 exige qu'une purge de charge utile laisse « echange, empreinte,
   horodatage et verdict intacts ». Si le corps transmis vivait dans une
   colonne de `FlwExchange`, le purger reviendrait a ECRIRE dans la ligne de
   preuve — donc a rendre l'immuabilite du registre invérifiable. Table a
   part, suppression franche, l'echange conserve son empreinte : on peut
   toujours prouver CE QUI a ete envoye sans conserver les donnees
   personnelles qu'il contenait.

2. *L'empreinte est calculee sur la charge utile et stockee sur l'ECHANGE.*
   Consequence directe du point precedent : c'est ce qui survit a la purge.

3. *`FlwExchange` est concu POUR le partitionnement par mois, sans etre
   partitionne des maintenant.* Le partitionnement declaratif PostgreSQL
   impose que la cle de partition fasse partie de la cle primaire, ce que
   Django ne sait pas exprimer avec un `UUIDField` seul. Le champ
   `partition_month` est donc pose des la conception, indexe et rempli a
   l'ecriture, de sorte que la bascule en table partitionnee soit une
   migration de structure et jamais une reprise de donnees. Ecrire le
   contraire — « partitionne » — alors que la table ne l'est pas serait
   precisement le genre d'affirmation que ce projet corrige depuis le
   debut.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.db.fields import EncryptedCharField
from apps.core.models.base import BaseModel

if TYPE_CHECKING:
    from datetime import date


class FlwConnector(BaseModel):
    """Un adaptateur de protocole — jamais un module (decision structurante
    n°2 du cahier).

    Le catalogue est PLAFONNE a `settings.BUDGET_MAX_ADAPTERS` (12),
    verifie en CI : « un catalogue de connecteurs derive exactement comme un
    catalogue de rapports [...] au bout de deux ans l'entretien consomme
    toute la capacite ». Au-dela, la reponse est l'API publique, y compris
    pour un client important.

    `code` identifie l'adaptateur DANS LE CODE (le registre d'adaptateurs
    s'y adosse) ; il n'est pas libre : un connecteur sans implementation
    correspondante serait une entree de catalogue sans connecteur derriere,
    exactement le « rapport fantome » que `register_report` refuse deja."""

    FAMILY_FISCAL = "fiscal"
    FAMILY_PAYMENT = "paiement"
    FAMILY_BANK = "banque"
    FAMILY_OFFICE = "bureautique"
    FAMILY_COMMERCE = "commerce"
    FAMILY_MESSAGING = "messagerie"
    FAMILY_CHOICES = [
        (FAMILY_FISCAL, _("Conformité fiscale")),
        (FAMILY_PAYMENT, _("Encaissement")),
        (FAMILY_BANK, _("Flux bancaires")),
        (FAMILY_OFFICE, _("Bureautique et stockage")),
        (FAMILY_COMMERCE, _("Commerce")),
        (FAMILY_MESSAGING, _("Messagerie")),
    ]

    code = models.CharField(max_length=64)
    name = models.CharField(max_length=150)
    family = models.CharField(max_length=16, choices=FAMILY_CHOICES)
    # Les huit operations canoniques (OP1-OP8) que CET adaptateur sait
    # rendre. Liste declarative, jamais du code : l'executeur y lit ce
    # qu'il a le droit de demander. Un adaptateur qui n'annonce pas une
    # operation ne se la verra jamais confier.
    supported_operations = models.JSONField(default=list, blank=True)
    is_enabled = models.BooleanField(default=False)

    class Meta:
        db_table = "flw_connector"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"], name="uniq_flw_connector_code_per_tenant"
            )
        ]
        ordering = ["family", "code"]

    def __str__(self) -> str:
        return f"{self.code} ({self.family})"


class FlwCredential(BaseModel):
    """Identifiant d'acces a un tiers — TABLE A PART, CHIFFREE.

    Le cahier l'exige mot pour mot (§13.2) : « table a part, chiffree,
    jamais exportee, jamais lue par le copilote ». Les trois exigences sont
    distinctes et aucune ne se deduit des autres :

    - *table a part*, pour que le droit de lire une liaison ne donne pas le
      droit de lire son secret, et pour qu'un export de configuration
      n'emporte pas les identifiants ;
    - *chiffree*, via `EncryptedCharField` (Fernet), deja employe pour
      `PrsEmployee.cin` et `PrsAbsence.reason` — l'audit relevait justement
      que `LogServiceProvider.webhook_secret` et `PrjGuestAccess.token`
      s'en passent alors que le champ existe (§3.6, ecart aggravant de
      FLX-8) ;
    - *jamais lue par le copilote* : aucun outil de `data_query` ne sera
      enregistre sur ce modele, et la garde de redaction des secrets (S6,
      FLX-8) le verifiera au niveau des journaux.

    `secret_hint` existe pour que l'ecran puisse dire QUELQUE CHOSE d'un
    identifiant sans le reveler (« se termine par 4f2a »). Sans lui, un
    exploitant ne peut pas distinguer deux identifiants a l'ecran et finit
    par les afficher en clair « juste pour verifier »."""

    # `noqa: S105` sur deux constantes : l'analyseur y voit un mot de passe
    # code en dur. Ce sont des VALEURS DE CHOIX — ce qui est stocke dans la
    # colonne `kind` pour dire de quelle NATURE est l'identifiant, jamais
    # l'identifiant lui-meme. Celui-ci vit dans `secret`, chiffre. Un
    # renommage qui ferait disparaitre le mot « secret » ferait taire
    # l'analyseur sans rien changer a la securite, et rendrait le champ
    # moins lisible : le motif est ecrit plutot que contourne.
    KIND_API_KEY = "cle_api"
    KIND_OAUTH_TOKEN = "jeton_oauth"  # noqa: S105
    KIND_BASIC = "identifiant_mot_de_passe"
    KIND_CERTIFICATE = "certificat"
    KIND_WEBHOOK_SECRET = "secret_webhook"  # noqa: S105
    KIND_CHOICES = [
        (KIND_API_KEY, _("Clé d'API")),
        (KIND_OAUTH_TOKEN, _("Jeton OAuth")),
        (KIND_BASIC, _("Identifiant et mot de passe")),
        (KIND_CERTIFICATE, _("Certificat")),
        (KIND_WEBHOOK_SECRET, _("Secret de webhook")),
    ]

    connector = models.ForeignKey(
        FlwConnector, on_delete=models.CASCADE, related_name="credentials"
    )
    label = models.CharField(max_length=150)
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    secret = EncryptedCharField(max_length=4096)
    # Indice NON secret, affichable : les quatre derniers caracteres, ou une
    # date d'emission. Jamais une portion exploitable du secret lui-meme.
    secret_hint = models.CharField(max_length=64, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    rotated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "flw_credential"
        ordering = ["connector", "label"]

    def __str__(self) -> str:
        return f"{self.label} ({self.kind})"


class FlwLink(BaseModel):
    """Liaison : un connecteur, un tenant, une destination concrete.

    C'est la liaison qui est activee ou suspendue, pas le connecteur : sur
    une instance multi-societes, deux tenants branches sur le meme
    adaptateur ont deux enrolements, deux identifiants et deux etats
    independants. Suspendre le connecteur les couperait tous les deux."""

    STATE_DRAFT = "brouillon"
    STATE_ACTIVE = "active"
    STATE_SUSPENDED = "suspendue"
    STATE_CHOICES = [
        (STATE_DRAFT, _("Brouillon")),
        (STATE_ACTIVE, _("Active")),
        (STATE_SUSPENDED, _("Suspendue")),
    ]

    connector = models.ForeignKey(FlwConnector, on_delete=models.PROTECT, related_name="links")
    credential = models.ForeignKey(
        FlwCredential, null=True, blank=True, on_delete=models.SET_NULL, related_name="links"
    )
    name = models.CharField(max_length=150)
    endpoint_url = models.URLField(blank=True)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_DRAFT)
    # Motif de suspension : une liaison coupee sans raison ecrite est une
    # panne dont personne ne retrouve la cause trois semaines plus tard.
    suspended_reason = models.TextField(blank=True)
    settings = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "flw_link"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "connector", "name"], name="uniq_flw_link_name_per_connector"
            )
        ]
        ordering = ["connector", "name"]

    def __str__(self) -> str:
        return self.name


class FlwMapping(BaseModel):
    """Correspondance de champs entre une piece du produit et le schema du
    tiers.

    FLX-6 exige qu'une correspondance INCOMPLETE soit refusee A
    L'ENREGISTREMENT, « champ manquant designe ». La validation vit donc
    dans le service (S5), jamais dans le gabarit : accepter une
    correspondance incomplete et echouer plus tard, au premier echange
    reel, transformerait une erreur de configuration en incident de
    production chez le tiers.

    `target_schema` est le schema DECLARE du tiers, contre lequel
    `field_map` est verifiee. Le stocker ici plutot que de le coder en dur
    dans l'adaptateur est ce qui permet a un tiers de faire evoluer son
    schema sans livraison."""

    link = models.ForeignKey(FlwLink, on_delete=models.CASCADE, related_name="mappings")
    document_type = models.CharField(max_length=64)
    field_map = models.JSONField(default=dict, blank=True)
    target_schema = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "flw_mapping"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "link", "document_type"],
                name="uniq_flw_mapping_per_link_and_document",
            )
        ]
        ordering = ["link", "document_type"]

    def __str__(self) -> str:
        return f"{self.link} / {self.document_type}"


class FlwSchedule(BaseModel):
    """Planification d'un echange recurrent.

    Adossee au registre d'ordonnancement de L0 (`apps.core.services.
    scheduled_commands`) et au calendrier malgache de la Phase 2 : une
    echeance qui tombe un jour ferie local doit se decaler, pas echouer.
    `next_run_at` est ecrit par le repartiteur, jamais saisi a la main."""

    FREQUENCY_HOURLY = "horaire"
    FREQUENCY_DAILY = "quotidien"
    FREQUENCY_WEEKLY = "hebdomadaire"
    FREQUENCY_MONTHLY = "mensuel"
    FREQUENCY_CHOICES = [
        (FREQUENCY_HOURLY, _("Chaque heure")),
        (FREQUENCY_DAILY, _("Quotidien")),
        (FREQUENCY_WEEKLY, _("Hebdomadaire")),
        (FREQUENCY_MONTHLY, _("Mensuel")),
    ]

    link = models.ForeignKey(FlwLink, on_delete=models.CASCADE, related_name="schedules")
    operation = models.CharField(max_length=32)
    frequency = models.CharField(max_length=16, choices=FREQUENCY_CHOICES)
    hour = models.PositiveSmallIntegerField(default=2)
    # Report sur jour ouvre : le calendrier des jours feries malgaches vit
    # dans `apps.core` depuis la Phase 2 (L2-3) — jamais une liste de dates
    # recopiee ici.
    skip_public_holidays = models.BooleanField(default=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "flw_schedule"
        ordering = ["link", "operation"]

    def __str__(self) -> str:
        return f"{self.link} / {self.operation} ({self.frequency})"


class FlwTrigger(BaseModel):
    """Declencheur evenementiel : une transition metier fait naitre un
    echange.

    **L'invariant qui compte, et que FLX-2 verifie** : l'echec du tiers ne
    doit JAMAIS empecher la transition metier. Un declencheur est un effet
    de bord ASYNCHRONE branche sur `apps.core.events` — la commande est
    confirmee meme si l'administration fiscale est injoignable. L'inverse
    ferait dependre le fonctionnement de l'entreprise de la disponibilite
    d'un tiers, ce qui est exactement ce que le hub existe pour eviter."""

    link = models.ForeignKey(FlwLink, on_delete=models.CASCADE, related_name="triggers")
    event_name = models.CharField(max_length=128)
    operation = models.CharField(max_length=32)
    # Condition declarative evaluee sur la charge de l'evenement, jamais du
    # code : meme discipline que `AnMetricDefinition.formule`, descriptive
    # et non executable.
    condition = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "flw_trigger"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "link", "event_name", "operation"],
                name="uniq_flw_trigger_per_event_and_operation",
            )
        ]
        ordering = ["link", "event_name"]

    def __str__(self) -> str:
        return f"{self.event_name} -> {self.operation}"


class FlwExchange(BaseModel):
    """LE REGISTRE. Une ligne par echange, entrant ou sortant.

    « Un adaptateur qui n'ecrit pas dans le registre n'est pas un
    connecteur, c'est une fuite » (cahier, decision structurante n°1). La
    garde CI de S6 (FLX-1) fera echouer la construction si un appel reseau
    part hors de l'executeur, ou si un echange est ecrit sans empreinte.

    Les neuf etats sont poses ici mais la machine a etats vit dans
    `services/exchange.py` (S2), avec ses trois invariants : `ACCEPTED` et
    `REJECTED` terminaux ; `AWAITING_VERDICT` sans expiration mais avec
    echeance de relance ; `SUSPENDED` (plafond atteint) n'ouvrant PAS
    d'incident — un plafond volontaire n'est pas une panne.

    `document_type`/`document_id` : la piece metier, designee de facon
    OPAQUE (cf. docstring de module). `correlation_key` relie l'echange
    sortant, la notification entrante qui lui repond et la piece — c'est
    elle qui permet de repondre a « qu'est devenue cette facture ? » sans
    parcourir trois journaux.

    `payload_fingerprint` survit a la purge de la charge utile (FLX-5) :
    c'est ce qui permet de prouver CE QUI a ete transmis apres que les
    donnees personnelles ont ete effacees."""

    DIRECTION_OUTBOUND = "sortant"
    DIRECTION_INBOUND = "entrant"
    DIRECTION_CHOICES = [
        (DIRECTION_OUTBOUND, _("Sortant")),
        (DIRECTION_INBOUND, _("Entrant")),
    ]

    STATE_PREPARED = "prepare"
    STATE_QUEUED = "en_file"
    STATE_SENT = "emis"
    STATE_ACCEPTED = "accepte"
    STATE_REJECTED = "rejete"
    STATE_AWAITING_VERDICT = "attente_verdict"
    STATE_TO_RETRY = "a_reessayer"
    STATE_FAILED = "en_echec"
    STATE_SUSPENDED = "suspendu"
    STATE_CHOICES = [
        (STATE_PREPARED, _("Préparé")),
        (STATE_QUEUED, _("En file")),
        (STATE_SENT, _("Émis")),
        (STATE_ACCEPTED, _("Accepté")),
        (STATE_REJECTED, _("Rejeté")),
        (STATE_AWAITING_VERDICT, _("En attente de verdict")),
        (STATE_TO_RETRY, _("À réessayer")),
        (STATE_FAILED, _("En échec")),
        (STATE_SUSPENDED, _("Suspendu")),
    ]
    # Etats TERMINAUX : plus aucune transition n'en part. Declares ici
    # plutot que dans le service, parce qu'un invariant du modele qui ne
    # vit que dans un service se perd au premier appelant qui l'ignore.
    TERMINAL_STATES = frozenset({STATE_ACCEPTED, STATE_REJECTED})

    link = models.ForeignKey(FlwLink, on_delete=models.PROTECT, related_name="exchanges")
    direction = models.CharField(max_length=8, choices=DIRECTION_CHOICES)
    operation = models.CharField(max_length=32)
    state = models.CharField(max_length=24, choices=STATE_CHOICES, default=STATE_PREPARED)

    # Piece metier, designee sans cle etrangere (cf. docstring de module).
    document_type = models.CharField(max_length=64, blank=True)
    document_id = models.UUIDField(null=True, blank=True)
    correlation_key = models.CharField(max_length=128, blank=True, db_index=True)
    # Clef d'idempotence SORTANTE, calculee en S4 sur (piece, liaison, rang
    # de tentative). Unique par tenant : rejouer transmet la meme clef, donc
    # ne cree pas de doublon chez le tiers (FLX-4).
    idempotency_key = models.CharField(max_length=128, blank=True)

    payload_fingerprint = models.CharField(max_length=64, blank=True)
    attempt = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    # Reponse du tiers, en clair et bornee : un code et un message, jamais
    # le corps complet (qui vit dans `FlwPayload` et se purge).
    result_code = models.CharField(max_length=64, blank=True)
    result_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    # Cle de partition, cf. decision 3 de la docstring de module : posee des
    # la conception pour que la bascule en table partitionnee soit une
    # migration de structure, jamais une reprise de donnees.
    partition_month = models.DateField(db_index=True)

    class Meta:
        db_table = "flw_exchange"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "state"], name="idx_flw_exchange_state"),
            models.Index(
                fields=["tenant", "document_type", "document_id"],
                name="idx_flw_exchange_document",
            ),
            models.Index(fields=["partition_month", "link"], name="idx_flw_exch_part_link"),
        ]
        constraints = [
            # L'idempotence est une promesse faite au TIERS : deux echanges
            # ne peuvent pas porter la meme clef chez le meme tenant, sans
            # quoi « rejouer sans doublon » (FLX-4) ne serait qu'une
            # intention. La condition exclut la chaine vide, qui signifie
            # « pas encore calculee » et vaut pour autant de lignes qu'on
            # veut.
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="uniq_flw_exchange_idempotency_key",
            )
        ]

    def __str__(self) -> str:
        return f"{self.direction} {self.operation} [{self.state}]"

    @staticmethod
    def month_of(value: date) -> date:
        """Cle de partition d'une date : le premier jour de son mois."""
        return value.replace(day=1)

    @staticmethod
    def fingerprint_of(body: str) -> str:
        """Empreinte SHA-256 d'une charge utile.

        Sur le CORPS TRANSMIS, jamais sur la piece metier d'origine : ce
        qu'on doit pouvoir prouver apres purge, c'est ce qui est REELLEMENT
        parti chez le tiers, pas ce qu'on croyait envoyer."""
        return hashlib.sha256(body.encode("utf-8")).hexdigest()


class FlwPayload(BaseModel):
    """Charge utile d'un echange — TABLE SEPAREE, retention propre.

    FLX-5 : « purge de la charge utile laissant echange, empreinte,
    horodatage et verdict intacts ». C'est la raison d'etre de cette table,
    et c'est pourquoi elle n'est pas une colonne de `FlwExchange` : purger
    une colonne reviendrait a ECRIRE dans la ligne de preuve. Ici, la purge
    est une SUPPRESSION franche, et le registre n'est pas touche.

    Relation `OneToOne` et non `ForeignKey` : un echange a exactement zero
    ou une charge utile. Zero apres purge — et c'est un etat NORMAL, pas
    une donnee manquante, ce que `purged_at` sur l'echange... n'exprime
    pas : l'absence de ligne suffit, et ajouter un drapeau qui pourrait
    contredire la realite de la table serait une seconde source de verite.

    `body` n'est PAS chiffre : il porte des donnees metier deja presentes en
    clair ailleurs dans la base (une facture, un catalogue), et le chiffrer
    donnerait l'illusion d'une protection que le reste du schema n'offre
    pas. Les SECRETS, eux, ne transitent jamais par ici — ils vivent dans
    `FlwCredential`, chiffres, et la garde de redaction de S6 (FLX-8)
    verifiera qu'aucun motif ressemblant a un secret n'atterrit dans une
    charge utile ou un journal."""

    exchange = models.OneToOneField(FlwExchange, on_delete=models.CASCADE, related_name="payload")
    content_type = models.CharField(max_length=64, default="application/json")
    body = models.TextField()
    byte_size = models.PositiveIntegerField(default=0)
    # Date au-dela de laquelle la purge est autorisee. Portee par la charge
    # utile et non par le connecteur : deux liaisons du meme adaptateur
    # peuvent relever de politiques de retention differentes (une soumission
    # fiscale se conserve plus longtemps qu'un catalogue publie).
    retain_until = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "flw_payload"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"charge utile de {self.exchange_id} ({self.byte_size} o)"
