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
from typing import TYPE_CHECKING, Any

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.cost_units import COST_UNIT_CHOICES
from apps.core.db.fields import EncryptedCharField
from apps.core.models.base import BaseModel
from apps.flows.operations import OPERATION_CHOICES, validate_supported_operations
from apps.flows.pricing_regimes import REGIME_CHOICES, validate_pricing_regime
from apps.flows.public_operations import validate_scopes

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
    # operation ne se la verra jamais confier — ce que `prepare_exchange`
    # applique depuis S6, apres l'avoir promis en commentaire depuis S1.
    #
    # Le validateur ne suffit PAS a lui seul : Django ne fait tourner les
    # validateurs de champ que dans `full_clean()`, jamais dans `save()`.
    # Il est donc pose ici pour les formulaires et les schemas, ET rappele
    # explicitement dans `save()` ci-dessous. Le supprimer d'un des deux
    # endroits laisserait passer la moitie des ecritures.
    supported_operations = models.JSONField(
        default=list, blank=True, validators=[validate_supported_operations]
    )
    is_enabled = models.BooleanField(default=False)
    # « Parallelisme borne par adaptateur pour ne pas declencher les
    # limitations de debit du tiers » (cahier §11). Le plafond vit sur le
    # CONNECTEUR et non sur la liaison : la limitation de debit est celle
    # du tiers, elle est donc la meme pour toutes les liaisons qui
    # l'appellent — deux liaisons d'un meme tenant vers la meme
    # plateforme partagent son quota, elles ne l'additionnent pas. C'est
    # exactement l'inverse du disjoncteur, qui est par liaison parce que
    # deux destinations peuvent tomber independamment.
    #
    # Ce que ce plafond borne AUJOURD'HUI, dit sans embellir : la vidange
    # est sequentielle (une boucle, un worker), il n'y a donc aucun
    # parallelisme a borner. Le plafond borne la TAILLE DE RAFALE d'une
    # passe — ce qui est la protection reellement utile contre la
    # limitation de debit d'un tiers, et ce qui restera le bon reglage le
    # jour ou la vidange deviendra parallele. Nommer le champ
    # « max_in_flight » plutot que « max_par_passe » est deliberé : c'est
    # la semantique cible, et elle n'oblige a rien renommer ensuite.
    max_in_flight = models.PositiveSmallIntegerField(default=20)

    # T9 — les trois declarations que le consentement de sortie (CON-2) et
    # le plafond (CON-5) exigent, et qui n'existaient pas.
    #
    # `country_code` : « vers quel tiers, DANS QUEL PAYS » (§9.1). Meme
    # forme que `Tenant.country_code` — deux lettres, aucun jeu ferme :
    # inventer une liste de pays serait une regle inventee, et le depot ne
    # le fait pas davantage ici qu'ailleurs. Vide = non declare, et
    # l'activation le refuse plutot que d'afficher un pays devine.
    country_code = models.CharField(max_length=2, blank=True)
    # `pricing_regime` : les trois regimes du §15.1. AUCUN defaut — mettre
    # « socle inclus » exempterait silencieusement du plafond un connecteur
    # qui coute a chaque appel, et « a l'usage » imposerait un plafond a un
    # connecteur gratuit. Vide tant que personne n'a tranche.
    pricing_regime = models.CharField(
        max_length=20, choices=REGIME_CHOICES, blank=True, validators=[validate_pricing_regime]
    )
    # `retention_days` : « pour quelle duree de conservation CONNUE »
    # (§9.1). `None` signifie « inconnue », et c'est un etat legitime que
    # l'ecran doit dire — le cahier ecrit « connue » precisement parce
    # qu'elle ne l'est pas toujours. Y mettre un chiffre par defaut ferait
    # affirmer au produit une duree que le tiers n'a jamais annoncee.
    retention_days = models.PositiveSmallIntegerField(null=True, blank=True)

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

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Refuse a L'ENREGISTREMENT une operation hors du jeu ferme.

        Meme discipline que FLX-6 pour les correspondances : accepter une
        declaration invalide et echouer plus tard, au premier echange,
        deplacerait la faute d'un ecran de configuration vers une passe de
        vidange nocturne — la ou personne ne la lit."""
        validate_supported_operations(self.supported_operations)
        # Meme raison que ci-dessus, et meme piege : Django ne fait tourner
        # les validateurs de champ que dans `full_clean()`, jamais dans
        # `save()`. Le laisser sur le seul `validators=[...]` protegerait
        # les formulaires et laisserait passer toute ecriture de service.
        validate_pricing_regime(self.pricing_regime)
        super().save(*args, **kwargs)


class FlwApiKey(BaseModel):
    """Cle publique d'acces — le jeton d'API d'un client tiers (§13.2).

    « Portees, debit, expiration, revocation. Portees exprimees en
    operations publiques declarees, JAMAIS EN TABLES. »

    **La cle porte un UTILISATEUR, et c'est ce qui tient API-1.** Le critere
    exige qu'« un jeton client ne puisse obtenir aucune donnee qu'un
    utilisateur du role correspondant ne pourrait consulter dans
    l'interface ». Deux facons de le tenir : recopier la matrice de droits
    dans un second mecanisme propre a l'API — et la voir diverger au premier
    role ajoute — ou faire porter au jeton un utilisateur reel, dont les
    groupes decident. La seconde est celle que le cahier demande
    explicitement : « le controle est celui de la Phase 1 pour le copilote,
    REUTILISE SANS MODIFICATION ». Tous les `require_permission` du depot
    s'appliquent alors sans qu'une seule ligne change.

    **Le secret n'est pas stocke.** `token_hash` porte l'empreinte SHA-256
    du jeton ; le clair n'existe qu'une fois, au moment de l'emission, et
    n'est jamais relu. Le nom du champ n'est pas libre : il doit finir par
    `_hash` pour que `test_secrets_are_never_stored_in_clear.py` le
    reconnaisse, et valoir `token_hash` pour que
    `object_remap.SECRET_TOKEN_FIELD_NAMES` le REGENERE quand un tenant est
    copie — sans quoi une sauvegarde restauree ressusciterait une cle
    valide chez quelqu'un d'autre.

    `prefix` est la partie AFFICHABLE, sans laquelle un exploitant qui a
    trois cles ne peut pas savoir laquelle revoquer, et finirait par les
    revoquer toutes. Meme raison d'etre que `FlwCredential.secret_hint`.

    **`revoked_at` plutot qu'un simple `is_active`.** La revocation est un
    FAIT DATE : savoir qu'une cle a ete revoquee le 12 a 14 h est ce qui
    permet de dire si un appel du 12 a 13 h etait legitime. Un booleen
    efface cette question."""

    label = models.CharField(max_length=150)
    # L'utilisateur dont les droits bornent la cle. PROTECT : supprimer le
    # compte de service sans revoquer ses cles laisserait des jetons dont
    # plus personne ne sait ce qu'ils ouvrent.
    user = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="api_keys")
    prefix = models.CharField(max_length=12)
    token_hash = models.CharField(max_length=64, unique=True)
    # Portees : des CODES d'operations publiques declarees. Le validateur
    # est pose ici pour les formulaires et les schemas, ET rappele dans
    # `save()` — Django ne fait tourner les validateurs de champ que dans
    # `full_clean()`, jamais dans `save()`.
    scopes = models.JSONField(default=list, blank=True, validators=[validate_scopes])
    # « Debit maximal » (§8.2). Par CLE, et c'est ce qu'exige API-7 : « le
    # depassement du debit d'une cle n'affecte ni les autres cles du tenant
    # ni les autres tenants ». Un plafond porte par le tenant ferait d'un
    # integrateur maladroit une panne pour tous les autres.
    rate_limit_per_hour = models.PositiveIntegerField(default=1000)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.TextField(blank=True)
    # Derniere utilisation, ecrite par l'authentification. Sert a repondre a
    # « cette cle sert-elle encore ? » avant de la revoquer — la question
    # que personne ne peut trancher sans elle, et qui fait qu'on ne revoque
    # jamais.
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "flw_api_key"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["tenant", "prefix"], name="idx_flw_api_key_prefix")]

    def __str__(self) -> str:
        return f"{self.label} ({self.prefix}…)"

    def save(self, *args: Any, **kwargs: Any) -> None:
        validate_scopes(self.scopes)
        super().save(*args, **kwargs)

    def is_usable(self, *, now: Any = None) -> bool:
        """Une cle utilisable : ni revoquee, ni expiree, ni desactivee.

        Les trois sont distinctes et aucune ne se deduit des autres. La
        revocation est un acte, l'expiration une echeance, la desactivation
        (`is_active`, de `BaseModel`) un archivage. Les confondre ferait
        d'une cle archivee par megarde une cle revoquee, donc une
        information fausse dans un journal d'acces."""
        from django.utils import timezone

        moment = now or timezone.now()
        if not self.is_active or self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > moment


class FlwCredential(BaseModel):
    """Identifiant d'acces a un tiers — TABLE A PART, CHIFFREE.

    Le cahier l'exige mot pour mot (§13.2) : « table a part, chiffree,
    jamais exportee, jamais lue par le copilote ». Les trois exigences sont
    distinctes et aucune ne se deduit des autres :

    - *table a part*, pour que le droit de lire une liaison ne donne pas le
      droit de lire son secret. **La table a part ne suffisait pas** a tenir
      la seconde moitie de la promesse : `tenant_export.
      export_tenant_archive` parcourt TOUTE sous-classe concrete de
      `BaseModel`, et `EncryptedCharField` dechiffre a la lecture — le clair
      partait donc dans l'archive de garantie de sortie (mesure du lot T8).
      C'est desormais `core.services.secret_redaction` qui tient
      « jamais exportee », avec sa garde ;
    - *chiffree*, via `EncryptedCharField` (Fernet), deja employe pour
      `PrsEmployee.cin` et `PrsAbsence.reason` — l'audit relevait justement
      que `LogServiceProvider.webhook_secret` et `PrjGuestAccess.token`
      s'en passent alors que le champ existe (§3.6, ecart aggravant de
      FLX-8) ;
    - *jamais lue par le copilote* : aucun outil de `data_query` n'est
      enregistre sur ce modele, et la redaction de S6 (FLX-8) couvre
      desormais les journaux — `apps.core.logging_filters.
      SecretRedactingFormatter`, pose sur chaque gestionnaire et verifie
      par `tests/architecture/test_secrets_are_never_written_to_a_log.py`.

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
    independants. Suspendre le connecteur les couperait tous les deux.

    **La liaison porte l'axe A5 du cahier — la politique d'echec — et
    l'etat du disjoncteur (S3).** Le cahier decrit le disjoncteur de deux
    manieres qui ne sont pas equivalentes : « par connecteur et par
    tenant » (§11 et §14.1, en prose d'option) et « sur une liaison »
    (critere FLX-3 et dictionnaire §13.2). La contrainte
    `uniq_flw_link_name_per_connector` porte sur `(tenant, connector,
    name)` : un tenant peut donc tenir PLUSIEURS liaisons sur un meme
    connecteur — un point d'essai et un point de production, deux comptes
    chez un agregateur. Les deux grains different donc reellement, et
    c'est le grain FIN qui est retenu : le critere fait foi, et l'axe A5
    le rend obligatoire puisqu'il place le SEUIL lui-meme sur la liaison.
    Un disjoncteur plus grossier que son propre seuil serait
    inapplicable — et couper la production parce que le point d'essai
    repond mal serait exactement la panne que ce mecanisme existe pour
    eviter.

    **Pourquoi des colonnes et non le `settings` JSON deja present.** Le
    cahier ecrit que les sept axes sont « limitatifs » et qu'« un filtre
    non declare est refuse a l'enregistrement ». Un JSON accepte
    n'importe quelle clef, ne se valide pas, ne s'indexe pas et ne se
    migre pas : y loger A5 rendrait la politique d'echec invisible a
    toute verification. Le `settings` reste pour ce qui appartient a
    l'adaptateur, jamais pour ce que le cahier a nomme.

    **La liaison doit etre lisible AVANT que la societe soit connue, et ce
    n'est pas `FORCE ROW LEVEL SECURITY` qu'on desarme pour autant.** Un
    operateur qui appelle `/api/v1/flows/webhooks/{link_id}` n'a ni
    session, ni jeton applicatif, ni en-tete de societe — lui en faire
    envoyer un reviendrait a laisser l'appelant choisir la societe dans
    laquelle il ecrit. Aucun `app.tenant_id` n'est donc pose, et la lecture
    de la liaison rend zero ligne : `all_objects` ne contourne que la RLS
    APPLICATIVE de `TenantManager`, jamais celle de PostgreSQL. Le point
    d'entree rendait 404 sur CHAQUE appel authentique.

    La reponse retenue n'est PAS la derogation `RLS_FORCE_FOR_OWNER =
    False` de `PrjGuestAccess` : elle rendrait la table lisible ET
    ECRIVABLE hors societe par le proprietaire, et FLX-7 — « l'isolation
    est refusee par PostgreSQL, pas seulement par l'application » — cesse
    d'etre vraie pour `flw_link`. Un critere ne se troque pas contre une
    commodite.

    Ce qui est pose a la place (migration `flows/0009`) est une seconde
    policy `webhook_lookup_policy`, **en LECTURE SEULE** (`FOR SELECT`) et
    conditionnee a un reglage de session que seul
    `services/inbound_routing.py` sait poser, pour la duree d'une seule
    requete. `FORCE` reste actif, la policy d'isolation reste la seule a
    gouverner les ECRITURES, et l'ouverture est exactement de la taille du
    besoin : retrouver une ligne par son identifiant pour savoir quelle
    societe activer.

    **Le defaut etait invisible en test**, et c'est ce qui le rend
    interessant : sous `pytest.mark.django_db` ordinaire, pytest-django
    tient une transaction englobante, le `SET LOCAL` pose par la fixture
    survit a la sortie du bloc, et la requete lit la liaison grace a un
    contexte qui n'existe QUE dans le harnais. Seul un test en
    `transaction=True` — donc sans transaction englobante, comme une vraie
    requete — le montre."""

    STATE_DRAFT = "brouillon"
    STATE_ACTIVE = "active"
    STATE_SUSPENDED = "suspendue"
    STATE_CHOICES = [
        (STATE_DRAFT, _("Brouillon")),
        (STATE_ACTIVE, _("Active")),
        (STATE_SUSPENDED, _("Suspendue")),
    ]

    #: Axe A5, dernier reglage : « comportement au-dela : mise en attente
    #: ou abandon trace ». Deux valeurs, parce que le cahier en nomme
    #: deux — et parce qu'elles repondent a deux situations opposees. Une
    #: soumission fiscale obligatoire doit ATTENDRE que la plateforme
    #: revienne ; une notification de confort n'a plus d'interet trois
    #: jours plus tard et doit etre abandonnee, en le disant.
    EXHAUSTED_HOLD = "mise_en_attente"
    EXHAUSTED_ABANDON = "abandon_trace"
    EXHAUSTED_CHOICES = [
        (EXHAUSTED_HOLD, _("Mise en attente")),
        (EXHAUSTED_ABANDON, _("Abandon tracé")),
    ]

    #: Trois etats, dont le troisieme est ce qui distingue un disjoncteur
    #: d'un simple interrupteur : apres la periode d'essai, on laisse
    #: passer UN appel pour savoir si le tiers est revenu.
    BREAKER_CLOSED = "ferme"
    BREAKER_OPEN = "ouvert"
    BREAKER_HALF_OPEN = "demi_ouvert"
    BREAKER_CHOICES = [
        (BREAKER_CLOSED, _("Fermé")),
        (BREAKER_OPEN, _("Ouvert")),
        (BREAKER_HALF_OPEN, _("Demi-ouvert")),
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

    # --- Axe A5 du cahier (§4.3) : la politique d'echec, reglee par le
    # client, dans les bornes que l'editeur pose. Cinq reglages, ni plus
    # ni moins : « nombre de tentatives, espacement, seuil de
    # disjoncteur, destinataire de l'alerte, comportement au-dela ».
    max_attempts = models.PositiveSmallIntegerField(default=3)
    # Espacement de BASE. Le cahier demande un « reessai avec espacement
    # croissant » (§6) : la croissance est geometrique et vit dans le
    # service, ce champ n'en porte que le premier terme. Le stocker sous
    # forme de table de delais aurait rendu le reglage client
    # ininterpretable — « 300, 900, 3600 » ne se saisit pas dans un
    # formulaire lu par un comptable.
    retry_backoff_seconds = models.PositiveIntegerField(default=300)
    breaker_threshold = models.PositiveSmallIntegerField(default=5)
    # Le glossaire du cahier definit le disjoncteur comme se refermant
    # « apres une periode d'essai ». Sans cette duree, un disjoncteur qui
    # s'ouvre une fois coupe la liaison pour toujours et il faut un
    # humain pour la rouvrir : ce serait une panne de plus, pas une
    # protection.
    breaker_cooldown_seconds = models.PositiveIntegerField(default=900)
    alert_recipient = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    on_attempts_exhausted = models.CharField(
        max_length=16, choices=EXHAUSTED_CHOICES, default=EXHAUSTED_HOLD
    )

    # --- Etat du disjoncteur (S3), ecrit par la machine, jamais par le
    # client. Il vit ici plutot que dans une table a part parce que le
    # dictionnaire du cahier en fait un attribut LU sur l'incident
    # (« etat du disjoncteur ») : une seule source de verite, affichee
    # ailleurs, plutot que deux qui divergent.
    # T9 (CON-5, §15.2) — le plafond opposable, et son alerte anticipee.
    #
    # `None` = aucun plafond configure, JAMAIS un plafond implicite a zero
    # qui bloquerait tout envoi par defaut — meme convention et meme motif
    # que `Tenant.whatsapp_monthly_cost_cap_ariary`, seul autre plafond de
    # cout du depot. Et c'est cette valeur `None` que l'activation refuse
    # sur un connecteur du regime a l'usage : « plafond obligatoire avant
    # activation ».
    monthly_cost_cap_ariary = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    # Le seuil d'alerte ANTICIPEE, en pourcentage du plafond. Le critere
    # CON-5 tient dans le mot « avant » : « une alerte est emise a
    # l'approche d'un plafond, AVANT SON ATTEINTE ». Alerter a 100 % serait
    # tenir la lettre du mot « alerte » et manquer le critere.
    cost_alert_threshold_pct = models.PositiveSmallIntegerField(default=80)
    # Le mois pour lequel l'alerte d'approche a deja ete emise. Sans lui,
    # chaque echange au-dela du seuil realerterait — et le §10.1 refuse
    # qu'un avertissement devienne du bruit : « un plafond atteint un 28 du
    # mois sans avertissement est vecu comme une panne », mais trente
    # avertissements le sont tout autant.
    cost_alerted_for_month = models.DateField(null=True, blank=True)
    breaker_state = models.CharField(max_length=12, choices=BREAKER_CHOICES, default=BREAKER_CLOSED)
    # « N echecs CONSECUTIFS » : un succes remet ce compteur a zero. Un
    # compteur cumulatif ouvrirait le disjoncteur sur une liaison qui
    # marche, au bout d'assez de mois.
    consecutive_failures = models.PositiveSmallIntegerField(default=0)
    breaker_opened_at = models.DateTimeField(null=True, blank=True)

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
    operation = models.CharField(max_length=32, choices=OPERATION_CHOICES)
    frequency = models.CharField(max_length=16, choices=FREQUENCY_CHOICES)
    hour = models.PositiveSmallIntegerField(default=2)
    # Report sur jour ouvre : jamais une liste de dates recopiee ici (une
    # garde CI l'interdit, `tests/architecture/test_no_hardcoded_holidays.py`).
    #
    # TRANCHE EN S5, et dans l'autre sens que ce commentaire ne l'annoncait :
    # le calendrier est REMONTE dans `core` (`core.Holiday`,
    # `core/services/calendar.py`) plutot qu'expose par le contrat public de
    # `forecast`. Un calendrier national est une donnee de reference, comme
    # `CountryDefaultsProfile` qui vit deja la ; et faire dependre le socle
    # de connectivite d'un module qui depend lui-meme de sept autres aurait
    # inverse la hierarchie que la regle de couplage n°1 protege.
    # `forecast` relit desormais le calendrier depuis `core`, ce qui allege
    # son couplage au lieu d'alourdir celui de `flows`.
    #
    # Le comptage des sources de feries, fait a cette occasion : il y en
    # avait TROIS, dont deux mortes. Les deux mortes sont desormais
    # SUPPRIMEES, sur decision du commanditaire :
    # `CountryDefaultsProfile.holidays` (aucun lecteur, aucun ecrivain) et
    # `presence/services/calendar.py`, qui annoncait en plus une majoration
    # de 150 % contredisant les 200 % reellement appliques par la paie.
    # `core.Holiday` est la source unique. Cf.
    # `docs/planning/2026-09-s5-trois-calendriers-feries.md`.
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
    operation = models.CharField(max_length=32, choices=OPERATION_CHOICES)
    # T0 (axe A1) : la piece source declaree, au format `app.Modele` —
    # exactement ce que `workflow.transitioned` porte sous la clef `model`.
    # C'est elle qui donne un SCHEMA aux filtres ci-dessous : sans piece
    # declaree, « champ declare du modele » n'a pas de referent, et le
    # filtre redeviendrait une expression libre.
    document_type = models.CharField(max_length=64, blank=True)
    # Condition declarative evaluee sur la PROJECTION de la piece, jamais du
    # code : meme discipline que `AnMetricDefinition.formule`, descriptive
    # et non executable. Depuis T0 la seule forme lue est
    # `{"filters": [{"field": ..., "op": ..., "value": ...}]}` ; toute autre
    # clef fait echouer la condition (deny-by-default, cf.
    # `services/triggers.py::declared_filters`).
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
    connecteur, c'est une fuite » (cahier, decision structurante n°1). Les
    deux moities de FLX-1 sont tenues depuis S6 :
    `tests/architecture/test_flows_network_only_in_the_executor.py` fait
    echouer la construction si un appel reseau part hors de l'executeur ou
    si un module resout un adaptateur lui-meme, et le passage a `emis`
    refuse un echange sans empreinte (`services/exchange.py`).

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
    operation = models.CharField(max_length=32, choices=OPERATION_CHOICES)
    state = models.CharField(max_length=24, choices=STATE_CHOICES, default=STATE_PREPARED)

    # Piece metier, designee sans cle etrangere (cf. docstring de module).
    document_type = models.CharField(max_length=64, blank=True)
    document_id = models.UUIDField(null=True, blank=True)
    correlation_key = models.CharField(max_length=128, blank=True, db_index=True)
    # Clef d'idempotence SORTANTE, calculee en S4.
    #
    # **Le mot « rejeu » recouvre DEUX choses, et les confondre rend FLX-4
    # inapplicable.** L'arbitrage est pose ici, une fois, parce que la
    # contrainte d'unicite ci-dessous en depend :
    #
    # - le REESSAI TECHNIQUE (S3) : le reseau a coupe, on renvoie LE MEME
    #   echange. Meme clef, obligatoirement — c'est exactement le cas que
    #   FLX-4 decrit (« un rejeu transmet la meme cle et ne cree aucun
    #   doublon chez un tiers qui la respecte »). La clef est donc calculee
    #   sur (piece, liaison) et NE CHANGE PAS d'une tentative a l'autre ;
    #   `attempt` compte les tentatives, il n'entre pas dans la clef.
    #
    # - le REJEU SUPERVISE (S4) : un humain, apres diagnostic, decide de
    #   resoumettre. C'est une SOUMISSION NOUVELLE, portee par un nouvel
    #   echange relie au precedent par `correlation_key`. Lui donner la
    #   meme clef ferait ignorer la resoumission par le tiers — l'inverse
    #   exact de ce que l'exploitant demande.
    #
    # La contrainte `uniq_flw_exchange_idempotency_key` est ce qui rend cet
    # arbitrage opposable : deux echanges ne peuvent pas partager une clef,
    # donc un successeur porte forcement la sienne. Une premiere redaction
    # de ce commentaire disait « rejouer transmet la meme clef » sans
    # distinguer les deux cas — elle contredisait la doctrine du successeur
    # posee dans `services/exchange.py`, et aucune des deux lectures
    # n'aurait pu etre implementee sans violer l'autre.
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

    # COUT IMPUTE — oublie par le sprint S1, ajoute ici.
    #
    # Le cahier ne le presente pas comme un detail : c'est sa decision
    # structurante n°6, « tout echange porte un cout impute et un plafond
    # opposable », et §13.2 le liste explicitement parmi les attributs de
    # l'echange. Sans ce champ, le plafond transverse annonce pour la
    # Phase 4 n'aurait rien a compter, et l'arbitrage H26 (bascule de
    # l'unite de cout de la messagerie, du au sprint S3) n'aurait aucun
    # endroit ou atterrir.
    #
    # `None` et non zero par defaut : « cout non encore impute » et « cout
    # nul » sont deux choses differentes. Une soumission fiscale gratuite
    # vaut zero ; un echange prepare dont le tarif n'est pas encore connu
    # vaut `None`. Les confondre ferait mentir tout total.
    #
    # Aucun tarif n'est ecrit ici ni ailleurs dans le code : « les grilles
    # rejoignent la table de parametres versionnes livree en Phase 1 »
    # (cahier, meme decision). Ce champ porte le montant IMPUTE, resultat
    # d'une grille, jamais la grille elle-meme.
    cost_ariary = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    # L'UNITE sous laquelle ce montant a ete tarife — et c'est ce qui rend
    # l'hypothese H26 du cahier SANS OBJET plutot que tranchee.
    #
    # H26 pose : « le passage de la messagerie professionnelle a une
    # facturation au message est correctement modelisable dans le compteur
    # existant sans reprise de l'historique », avec pour repli « deux unites
    # de cout coexistent, avec une date de bascule », au prix d'« un sprint
    # supplementaire au bloc H ». Le cahier demande de trancher au sprint 3,
    # « le prendre apres le sprint 6 signifierait reprendre le socle ».
    #
    # La branche optimiste est vraie a MOITIE. Vraie : le cout est fige sur
    # la ligne au moment de l'envoi, donc aucune reprise d'historique n'est
    # necessaire — les lignes passees gardent le tarif qui leur a ete
    # impute. Fausse : rien n'enregistre SOUS QUELLE UNITE. Un total sur une
    # periode a cheval sur une bascule melangerait donc les deux en silence,
    # et un plafond calcule sur ce total serait faux sans que rien ne le
    # signale.
    #
    # Plutot que de parier sur une branche, on rend l'unite DONNEE. Le cout
    # est alors un couple (montant, unite), jamais un montant seul. Si la
    # bascule n'a jamais lieu, l'unite reste constante et rien n'est perdu ;
    # si elle a lieu, chaque ligne dit deja sous quel regime elle a ete
    # tarifee et aucun total ne ment. L'arbitrage cesse de conditionner la
    # conception — c'est-a-dire qu'il cesse d'etre un risque de projet.
    #
    # `blank=True` sans `null=True` : la chaine vide accompagne un
    # `cost_ariary` a `None`, un cout non impute n'ayant pas d'unite. Deux
    # facons d'ecrire « rien » sur un champ texte rendraient toute requete
    # ambigue.
    cost_unit = models.CharField(max_length=16, choices=COST_UNIT_CHOICES, blank=True)

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

    @property
    def document_label(self) -> str:
        """Le nom LISIBLE de la piece designee, pour le journal (CON-1).

        `accounting.AccMove` n'est pas un mot de la langue d'un comptable, et
        le §10.3 refuse de remonter le vocabulaire technique tel quel. Le
        libelle vient du registre que le module metier alimente lui-meme
        (`core.services.document_screens`) : le hub ne connait toujours
        aucun module."""
        from apps.core.services.document_screens import document_label

        if not self.document_type:
            # Une publication planifiee — un jeu de donnees, une
            # disponibilite de boutique — ne designe aucune piece. Etat
            # normal, pas une anomalie : le dire vaut mieux qu'une cellule
            # vide, qu'un exploitant lirait comme une donnee manquante.
            return str(_("Aucune pièce rattachée"))
        return document_label(self.document_type)

    @property
    def connector_code(self) -> str:
        """A QUI cet echange est parti, pour la colonne « Destinataire » du
        journal.

        Sans cette propriete, le composant de liste rendait la cellule VIDE
        et sans rien dire : `core_extras.getattr` vaut
        `getattr(objet, cle, "")`, donc une colonne qui designe un attribut
        inexistant s'affiche vide plutot que de lever. Defaut trouve en
        relisant le diff, jamais par un test — celui-ci verifiait ce qu'il
        s'attendait a trouver, pas ce qui devait etre dans chaque cellule."""
        return self.link.connector.code

    @property
    def operation_label(self) -> str:
        """Le libelle de l'operation, jamais son code.

        §10.3 : le vocabulaire technique du tiers — ici le notre — n'est
        jamais remonte tel quel. « push_document » dans une colonne d'ecran
        est exactement ce que le cahier refuse."""
        return str(self.get_operation_display())

    @property
    def state_label(self) -> str:
        """Le libelle de l'etat, meme motif que `operation_label`."""
        return str(self.get_state_display())

    @property
    def smart_table_url(self) -> str:
        """L'ecran de la piece designee — le second sens de CON-1, « et
        reciproquement depuis toute ligne du journal ».

        Chaine vide quand il n'y a rien a atteindre : aucune piece designee,
        ou un module qui n'a pas declare d'ecran. Le data grid n'affiche
        alors pas de lien, plutot qu'un lien mort."""
        from apps.core.services.document_screens import resolve_document_url

        return resolve_document_url(self.document_type, self.document_id) or ""

    @property
    def payload_is_purged(self) -> bool:
        """FLX-5 : distingue « charge utile PURGEE » de « charge utile
        JAMAIS ECRITE », sans colonne supplementaire.

        La question se pose des qu'une purge existe, et le premier reflexe
        serait un `purged_at` sur l'echange. `FlwPayload` explique pourquoi
        c'est un mauvais reflexe : un drapeau peut contredire la table.
        La reponse etait deja dans le schema — `payload_fingerprint` n'est
        pose qu'a la creation, et seulement quand un corps existait. Une
        empreinte SANS ligne de charge utile est donc une purge ; pas
        d'empreinte est un echange qui n'a jamais rien porte.

        C'est une DERIVATION et non une seconde source de verite : elle
        lit la table, elle ne peut donc pas la contredire. Elle coute une
        requete par appel — a lire sur un queryset annote plutot qu'en
        boucle sur une console."""
        if not self.payload_fingerprint:
            return False
        return not FlwPayload.objects.filter(exchange_id=self.id).exists()

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
    `FlwCredential`, chiffres, et depuis S6 (FLX-8) `prepare_exchange`
    REDIGE le corps a l'ecriture, dans les termes memes du cahier (§13.2,
    « redaction des secrets a l'ecriture »). L'empreinte est calculee sur
    le corps REDIGE : elle prouve ce qui part reellement, et l'inverse
    prouverait un contenu que personne n'a jamais transmis."""

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
        indexes = [
            # La purge de FLX-5 balaye cette table tous les jours, sur deux
            # chemins : la date explicite, et son absence (politique par
            # defaut, filtree sur `created_at`). Les trois colonnes dans un
            # seul index couvrent les deux — sans lui, la purge fait un
            # parcours complet de la table la plus volumineuse du hub, ce
            # qui est exactement le « fenetre de purge depassee » que le
            # cahier redoute.
            models.Index(
                fields=["tenant", "retain_until", "created_at"],
                name="idx_flw_payload_retention",
            )
        ]

    def __str__(self) -> str:
        return f"charge utile de {self.exchange_id} ({self.byte_size} o)"


#: Les deux etats ou un incident est encore VIVANT. Definis au niveau
#: MODULE, et pas seulement sur la classe, pour une raison de langage
#: qu'il vaut mieux ecrire que redecouvrir : un corps de `class Meta`
#: imbrique ne voit PAS le namespace de la classe qui l'englobe (les
#: portees de classe ne sont pas des portees englobantes en Python), si
#: bien que `condition=Q(state__in=LIVE_STATES)` y leverait `NameError` a
#: l'import du modele. Une seule definition, referencee des deux cotes —
#: recopier le couple de chaines dans la contrainte reintroduirait
#: exactement la divergence que `LIVE_STATES` existe pour empecher.
_INCIDENT_STATE_OPEN = "ouvert"
_INCIDENT_STATE_ACKNOWLEDGED = "pris_en_charge"
_INCIDENT_LIVE_STATES = (_INCIDENT_STATE_OPEN, _INCIDENT_STATE_ACKNOWLEDGED)


class FlwIncident(BaseModel):
    """Incident : le REGROUPEMENT des echecs repetes sur une liaison (S3).

    Le dictionnaire du cahier (§13.2) le definit mot pour mot ainsi :
    « Regroupement d'echecs repetes sur une liaison : famille d'erreur,
    premiere et derniere occurrence, etat du disjoncteur, action de reprise
    proposee. » Et le critere FLX-3 en tire la seule chose qui compte
    vraiment : « un incident UNIQUE est cree — pas un incident par
    tentative ».

    **Le grain de regroupement est (liaison, famille), pas la liaison
    seule.** Le dictionnaire fait porter UNE famille a l'incident, et §10.3
    associe a chaque famille « une action de reprise unique et
    comprehensible ». Deux causes differentes sur la meme liaison — un
    jeton expire et une plateforme injoignable — n'ont pas la meme reprise
    : les fondre en un incident rendrait « action de reprise proposee »
    faux dans un cas sur deux. Le disjoncteur, lui, reste par LIAISON : il
    existe pour cesser de marteler un tiers, et le motif du martelage ne
    change rien a l'urgence de s'arreter.

    **Six familles, et c'est ferme.** §10.3 : « Chaque adaptateur doit
    traduire les erreurs du tiers dans un jeu ferme de six familles [...]
    Un adaptateur qui remonte une septieme famille ne passe pas la
    recette. » C'est verifie en integration continue
    (`tests/architecture/test_flows_error_families.py`), parce qu'une
    enumeration qu'on peut allonger sans que rien ne proteste redevient du
    texte libre en deux sprints — et le texte libre est precisement ce que
    §10.3 interdit, puisqu'il rendrait la console de flux illisible.

    **L'action de reprise n'est PAS une colonne.** Elle est derivee de la
    famille (`services.incidents.RECOVERY_ACTIONS`). Stockee, elle
    divergerait : une ligne ecrite en janvier garderait le libelle de
    janvier apres correction du texte, et deux incidents de la meme
    famille proposeraient deux reprises differentes. C'est la meme
    discipline que le cahier pose pour l'ecran de consentement — « le
    texte des categories est genere depuis la declaration de l'adaptateur,
    jamais redige a la main — sinon il devient faux a la premiere
    evolution ».

    **Pas de `ReferenceMixin`.** Meme motif ecrit que `AiAnomaly` : un
    incident est un enregistrement de suivi ouvert par un worker, pas un
    document numerote qu'un utilisateur cree. Lui attribuer une reference
    imposerait un `select_for_update` sur la sequence a l'interieur meme
    de la boucle de vidange — un point de contention sur le chemin le plus
    contendu. Si la console de flux (bloc H) a besoin d'un numero lisible
    par le support, c'est la qu'il faudra l'ajouter, et ce commentaire est
    l'endroit ou le relire."""

    #: Les six familles de §10.3, dans l'ordre du cahier. Le libelle est
    #: celui du cahier, pas une reformulation : c'est ce que l'utilisateur
    #: lira dans la console, et le cahier a choisi des mots comprehensibles
    #: par un comptable plutot que par un developpeur.
    FAMILY_CREDENTIALS = "identifiants"
    FAMILY_INVALID_DATA = "donnee_invalide"
    FAMILY_REJECTED = "refus_tiers"
    FAMILY_UNAVAILABLE = "tiers_indisponible"
    FAMILY_CAP_REACHED = "plafond_atteint"
    FAMILY_EDITOR = "anomalie_editeur"
    FAMILY_CHOICES = [
        (FAMILY_CREDENTIALS, _("Identifiants à renouveler")),
        (FAMILY_INVALID_DATA, _("Donnée manquante ou invalide dans la pièce")),
        (FAMILY_REJECTED, _("Refus motivé par le tiers")),
        (FAMILY_UNAVAILABLE, _("Tiers indisponible")),
        (FAMILY_CAP_REACHED, _("Plafond atteint")),
        (FAMILY_EDITOR, _("Anomalie à signaler à l'éditeur")),
    ]

    #: Deux etats ouverts et un ferme. « Pris en charge » existe parce que
    #: l'indicateur de pilotage du cahier mesure « la part des echanges en
    #: incident NON TRAITES sous 48 h » : sans etat intermediaire, un
    #: incident sur lequel quelqu'un travaille compterait comme non traite,
    #: et l'indicateur mesurerait la duree de la panne du tiers plutot que
    #: la reactivite du support.
    STATE_OPEN = _INCIDENT_STATE_OPEN
    STATE_ACKNOWLEDGED = _INCIDENT_STATE_ACKNOWLEDGED
    STATE_RESOLVED = "resolu"
    STATE_CHOICES = [
        (STATE_OPEN, _("Ouvert")),
        (STATE_ACKNOWLEDGED, _("Pris en charge")),
        (STATE_RESOLVED, _("Résolu")),
    ]
    #: Les etats ou l'incident est encore VIVANT — donc ceux ou un echec de
    #: plus incremente au lieu de creer. Une liste nommee plutot que deux
    #: `Q` recopies : c'est elle qui porte le critere FLX-3, et un critere
    #: recopie a deux endroits finit par ne plus l'etre qu'a un seul.
    LIVE_STATES = _INCIDENT_LIVE_STATES

    link = models.ForeignKey(FlwLink, on_delete=models.CASCADE, related_name="incidents")
    family = models.CharField(max_length=24, choices=FAMILY_CHOICES)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_OPEN)
    # « Premiere et derniere occurrence » du dictionnaire. `created_at`
    # d'un `BaseModel` donnerait deja la premiere ; le champ est explicite
    # quand meme, parce que la lecture qui compte est « depuis combien de
    # temps ca dure » et qu'elle ne doit pas dependre d'un champ technique
    # qu'une reprise de donnees pourrait reecrire.
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    # Le compteur qui rend FLX-3 verifiable : c'est LUI qui monte quand un
    # incident par tentative aurait cree une ligne. Patron
    # `Document.reference_count`, seul precedent de « une ligne, N
    # occurrences » du depot.
    occurrence_count = models.PositiveIntegerField(default=1)
    # « Le message d'origine reste consultable pour le diagnostic, replie »
    # (§10.3). Le DERNIER, pas tous : conserver l'historique complet des
    # messages ferait de l'incident un second journal a cote du registre
    # d'echange, qui est deja la trace ligne par ligne.
    last_result_code = models.CharField(max_length=64, blank=True)
    last_result_message = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "flw_incident"
        constraints = [
            # FLX-3, en BASE et pas seulement en service. Le critere dit
            # « un incident unique » : un service peut etre contourne par
            # une commande, un import ou un second worker, une contrainte
            # non. Contrainte PARTIELLE sur les etats vivants — une fois
            # resolu, un incident ne doit plus bloquer l'ouverture du
            # suivant, sans quoi une liaison reparee puis retombee en
            # panne resterait muette pour toujours.
            models.UniqueConstraint(
                fields=["tenant", "link", "family"],
                condition=models.Q(state__in=_INCIDENT_LIVE_STATES),
                name="uniq_flw_incident_vivant_par_liaison_famille",
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "state"], name="idx_flw_incident_state"),
        ]
        ordering = ["-last_seen_at"]

    def __str__(self) -> str:
        return f"{self.get_family_display()} sur {self.link_id} (×{self.occurrence_count})"
