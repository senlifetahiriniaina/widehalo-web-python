"""Module POS — distribution et services (cahier des charges WideHalo v3,
Phase 1, §13.5). Ecart confirme par l'audit (docs/audit/2026-09-cahier-des-charges-v3-audit.md,
POS-1 a POS-9) : ce module etait entierement absent du depot.

Regle de couplage n1 (identique a `sales`/`stocks`) : `pos` ne fait jamais
de FK Django vers `apps.catalog`/`apps.partners`/`apps.stocks`/
`apps.accounting` — ces entites sont referencees par UUID nu, resolues via
`services.public` de chaque app.

**Simplification assumee et disclosee** : l'"ecart" de caisse (cahier :
"tout ecart de caisse est enregistre, motive et journalise") n'est pas un
modele dedie (contrairement a l'estimation indicative du cahier, §10.1,
qui envisage ~10 modeles POS y compris un modele "ecart" separe) mais un
jeu de champs sur `PosSession` (`closing_cash_counted`/
`closing_cash_expected`/`cash_variance`/`cash_variance_reason`) : une
session n'a qu'un seul ecart, jamais plusieurs, un modele separe
n'ajouterait qu'une jointure 1-1 sans information supplementaire."""

from __future__ import annotations

from django.db import models

from apps.core.models.base import BaseModel


class PosPaymentMethod(BaseModel):
    """Moyen de paiement POS (cahier : "paiements multi-moyens dont le
    mobile money... Chaque moyen est relie a un compte du plan PCG 2005
    paramétré par tenant"). `account_id` resout ce compte ; laisse vide, la
    cloture de session (`services.sessions.close_session` ->
    `accounting.services.public.create_pos_session_closing_entry_from_source`)
    retombe sur le premier `AccAccount` du `default_account_type` — meme
    discipline "compte par defaut si non parametre explicitement" que
    `accounting.services.public.create_stock_adjustment_entry_from_source`."""

    TYPE_CASH = "cash"
    TYPE_MOBILE_MONEY = "mobile_money"
    TYPE_CARD = "card"
    TYPE_CHEQUE = "cheque"
    TYPE_CREDIT_NOTE = "credit_note"
    TYPE_CHOICES = [
        (TYPE_CASH, "Espèces"),
        (TYPE_MOBILE_MONEY, "Mobile money"),
        (TYPE_CARD, "Carte"),
        (TYPE_CHEQUE, "Chèque"),
        (TYPE_CREDIT_NOTE, "Avoir"),
    ]

    # Type de compte comptable par defaut resolu a la cloture quand
    # `account_id` n'est pas renseigne — `apps.accounting.models.AccAccount.
    # TYPE_CASH`/`TYPE_BANK` republies en primitives ici (jamais un import
    # de `apps.accounting.models`, regle de couplage n1).
    ACCOUNT_TYPE_CASH = "cash"
    ACCOUNT_TYPE_BANK = "bank"
    ACCOUNT_TYPE_CHOICES = [
        (ACCOUNT_TYPE_CASH, "Caisse"),
        (ACCOUNT_TYPE_BANK, "Banque / monnaie électronique"),
    ]

    code = models.CharField(max_length=32)
    name = models.CharField(max_length=120)
    type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    # RG POS-5 : "la référence de transaction du mobile money est
    # obligatoire" — generalise a tout moyen susceptible d'en exiger une
    # (mobile money par defaut a la creation, cf. `services.public`
    # eventuel enrichissement futur), verifie par
    # `services.orders.add_payment`.
    requires_reference = models.BooleanField(default=False)
    default_account_type = models.CharField(
        max_length=16, choices=ACCOUNT_TYPE_CHOICES, default=ACCOUNT_TYPE_CASH
    )
    account_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "pos_payment_method"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"], name="uniq_pos_payment_method_code_per_tenant"
            )
        ]
        ordering = ["code"]

    def __str__(self) -> str:
        return self.name


class PosRegister(BaseModel):
    """Point de caisse ("caisse" au sens du cahier). `code` sert de PREFIXE
    de numerotation des tickets (POS-4 : "numérotation... préfixe de
    caisse + séquence locale")."""

    code = models.CharField(max_length=16)
    name = models.CharField(max_length=120)
    # `apps.stocks.models.StkWarehouse` resolu par UUID nu (regle de
    # couplage n1) — entrepot dont le stock est decremente par les ventes
    # de cette caisse (POS distribution uniquement, cf. `PosOrderLine.
    # line_type`).
    warehouse_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "pos_register"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"], name="uniq_pos_register_code_per_tenant"
            )
        ]
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class PosSession(BaseModel):
    """Session de caisse (cahier : "unité de responsabilité du caissier" et
    "unité de génération de l'écriture comptable"). Aucune vente n'est
    possible en dehors d'une session `OPEN` (POS-2) ; une session `CLOSED`
    est immuable, y compris pour un administrateur (POS-9) — applique au
    niveau service (`services.sessions`/`services.orders`), jamais
    seulement cote interface."""

    STATE_OPEN = "open"
    STATE_CLOSED = "closed"
    STATE_CHOICES = [
        (STATE_OPEN, "Ouverte"),
        (STATE_CLOSED, "Clôturée"),
    ]

    register = models.ForeignKey(PosRegister, on_delete=models.PROTECT, related_name="sessions")
    cashier = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_OPEN)
    opened_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)
    opening_cash_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    # Renseignes uniquement a la cloture (`services.sessions.close_session`).
    closing_cash_counted = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    closing_cash_expected = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    cash_variance = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    cash_variance_reason = models.CharField(max_length=255, blank=True)
    # UUID nu de l'`AccMove` consolide (regle de couplage n1) cree par
    # `accounting.services.public.create_pos_session_closing_entry_from_source`
    # — `None` si la configuration comptable du tenant manquait a la
    # cloture (meme discipline "jamais d'exception, jamais de blocage
    # silencieux" que le reste du contrat `accounting.services.public` :
    # la session se cloture quand meme, l'absence d'ecriture est
    # signalee a l'ecran).
    closing_move_id = models.UUIDField(null=True, blank=True)

    # POS-4 : compteur de sequence locale de cette session, incremente a
    # chaque commande (en ligne ou hors ligne) creee sous cette session —
    # combine au prefixe `register.code` pour composer `PosOrder.number`.
    local_sequence_last = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "pos_session"
        ordering = ["-opened_at"]

    def __str__(self) -> str:
        return f"{self.register.code} — {self.opened_at:%Y-%m-%d %H:%M}"


class PosCashMovement(BaseModel):
    """Mouvement d'espèces entrant/sortant motivé (cahier, écran "Session
    de caisse" : "mouvements d'espèces entrants et sortants motivés") —
    hors vente (ex. dépôt en banque en cours de journée, appoint de
    monnaie). N'affecte JAMAIS le catalogue de vente ni un `PosOrder` :
    seulement `closing_cash_expected` au moment de la clôture (cf.
    `services.sessions.compute_expected_cash`)."""

    DIRECTION_IN = "in"
    DIRECTION_OUT = "out"
    DIRECTION_CHOICES = [
        (DIRECTION_IN, "Entrée"),
        (DIRECTION_OUT, "Sortie"),
    ]

    session = models.ForeignKey(PosSession, on_delete=models.CASCADE, related_name="cash_movements")
    direction = models.CharField(max_length=8, choices=DIRECTION_CHOICES)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    reason = models.CharField(max_length=255)

    class Meta:
        db_table = "pos_cash_movement"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.get_direction_display()} {self.amount}"


class PosOrder(BaseModel):
    """Ticket/facture POS (vente ou retour). `client_uuid` est la clef
    d'idempotence de la synchronisation hors ligne (POS-3) : genere PAR LE
    CLIENT (caisse) a la creation locale, jamais recalcule serveur —
    `services.orders.sync_order` s'appuie dessus pour ne JAMAIS creer deux
    fois la meme vente rejouee (perte de reseau + nouvelle tentative).

    `number` est la reference DEFINITIVE ("préfixe de caisse + séquence
    locale, réconciliée côté serveur" — POS-4) : composee du prefixe
    `register.code` et d'une sequence PAR REGISTRE assignee par le SERVEUR
    a la premiere synchronisation reussie, via
    `apps.core.services.sequences.next_reference` — le MEME mecanisme
    verrouille (`select_for_update`) deja prouve sans trou ni doublon meme
    en creations concurrentes par `sales.SalesOrder`/`AccMove` (SAL-6).
    `local_sequence`, lui, reste un compteur PUREMENT CLIENT (le POS hors
    ligne numerote ses propres tickets localement pendant une session sans
    jamais interroger le serveur) : il ne sert qu'a la caisse elle-meme
    pour detecter un trou/doublon dans SA PROPRE file d'attente locale —
    jamais la reference finale imprimee/affichee, jamais garanti unique au-
    dela d'une seule session (deux sessions distinctes du meme registre
    recommencent chacune a 1)."""

    TYPE_SALE = "sale"
    TYPE_RETURN = "return"
    TYPE_CHOICES = [
        (TYPE_SALE, "Vente"),
        (TYPE_RETURN, "Retour / avoir"),
    ]

    DOCUMENT_TICKET = "ticket"
    DOCUMENT_INVOICE = "invoice"
    DOCUMENT_CHOICES = [
        (DOCUMENT_TICKET, "Ticket"),
        (DOCUMENT_INVOICE, "Facture nominative"),
    ]

    STATE_DRAFT = "draft"
    STATE_VALIDATED = "validated"
    STATE_CANCELLED = "cancelled"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_VALIDATED, "Validée"),
        (STATE_CANCELLED, "Annulée"),
    ]

    SOURCE_ONLINE = "online"
    SOURCE_OFFLINE = "offline"
    SOURCE_CHOICES = [
        (SOURCE_ONLINE, "En ligne"),
        (SOURCE_OFFLINE, "Hors ligne (synchronisée)"),
    ]

    session = models.ForeignKey(PosSession, on_delete=models.PROTECT, related_name="orders")
    register = models.ForeignKey(PosRegister, on_delete=models.PROTECT, related_name="+")
    client_uuid = models.UUIDField()
    number = models.CharField(max_length=32, blank=True, db_index=True)
    local_sequence = models.PositiveIntegerField()
    order_type = models.CharField(max_length=8, choices=TYPE_CHOICES, default=TYPE_SALE)
    # Retour/avoir rattache au ticket d'origine (cahier : "Retour partiel
    # ou total rattaché au ticket d'origine").
    origin_order = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="returns"
    )
    document_type = models.CharField(
        max_length=8, choices=DOCUMENT_CHOICES, default=DOCUMENT_TICKET
    )
    # UUID nu de `apps.partners.models.Partner` (regle de couplage n1) —
    # nullable : "un ticket anonyme est autorisé" ; une facture nominative
    # exige un tiers identifié, revalidé cote service (`services.orders.
    # validate_order`), jamais seulement cote interface.
    partner_id = models.UUIDField(null=True, blank=True)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_DRAFT)
    source = models.CharField(max_length=8, choices=SOURCE_CHOICES, default=SOURCE_ONLINE)

    amount_untaxed = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    amount_tax = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    amount_total = models.DecimalField(max_digits=18, decimal_places=4, default=0)

    reprint_count = models.PositiveIntegerField(default=0)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "pos_order"
        constraints = [
            # POS-3/POS-4 : deux tentatives de synchronisation du meme
            # `client_uuid` (perte de reseau + nouvel essai) ne doivent
            # jamais produire deux commandes — garantie en base, pas
            # seulement applicative (meme discipline que l'immuabilite/
            # numerotation continue des factures `sales`, RG-SAL §13.2).
            models.UniqueConstraint(
                fields=["tenant", "client_uuid"], name="uniq_pos_order_client_uuid_per_tenant"
            ),
            # Scope SESSION (pas registre) : `local_sequence` recommence a
            # 1 a chaque nouvelle session (cf. docstring ci-dessus) — deux
            # sessions distinctes du meme registre partagent legitimement
            # la meme valeur.
            models.UniqueConstraint(
                fields=["session", "local_sequence"],
                name="uniq_pos_order_local_sequence_per_session",
            ),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.number or str(self.client_uuid)


class PosOrderLine(BaseModel):
    """Ligne de vente. `line_type=SERVICE` porte une prestation (cahier :
    "lignes de service sans référence de stock, au forfait ou au temps
    passé, avec acompte possible") — `variant_id` reste alors nul et
    AUCUN mouvement de stock n'est jamais genere pour cette ligne
    (POS-8, verifie par `services.orders.validate_order`)."""

    TYPE_PRODUCT = "product"
    TYPE_SERVICE = "service"
    TYPE_CHOICES = [
        (TYPE_PRODUCT, "Produit"),
        (TYPE_SERVICE, "Service"),
    ]

    SERVICE_BASIS_FORFAIT = "forfait"
    SERVICE_BASIS_TEMPS_PASSE = "temps_passe"
    SERVICE_BASIS_CHOICES = [
        (SERVICE_BASIS_FORFAIT, "Forfait"),
        (SERVICE_BASIS_TEMPS_PASSE, "Temps passé"),
    ]

    order = models.ForeignKey(PosOrder, on_delete=models.CASCADE, related_name="lines")
    sequence = models.PositiveIntegerField(default=0)
    line_type = models.CharField(max_length=16, choices=TYPE_CHOICES, default=TYPE_PRODUCT)
    # UUID nu de `apps.catalog.models.ProductVariant` (regle de couplage
    # n1) — nul pour une ligne de service.
    variant_id = models.UUIDField(null=True, blank=True)
    description = models.CharField(max_length=255)
    qty = models.DecimalField(max_digits=18, decimal_places=4, default=1)
    uom = models.CharField(max_length=16, blank=True)
    unit_price = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    # UUID nu de `apps.accounting.models.AccTax` (regle de couplage n1) —
    # `tax_rate` est un INSTANTANE du taux au moment de la vente (une
    # AccTax future ne doit jamais reinterpreter le montant d'une ligne
    # deja vendue, meme discipline "document valide immuable" que
    # `sales`/`accounting`).
    tax_id = models.UUIDField(null=True, blank=True)
    tax_rate = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    subtotal = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    service_basis = models.CharField(max_length=16, choices=SERVICE_BASIS_CHOICES, blank=True)
    is_deposit = models.BooleanField(default=False)
    # UUID nu du `StkPicking` genere pour cette ligne (POS distribution
    # uniquement, `line_type=PRODUCT`) — nul pour une ligne de service ou
    # tant que la commande n'est pas validee.
    stock_move_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "pos_order_line"
        ordering = ["sequence"]

    def __str__(self) -> str:
        return f"{self.description} x{self.qty}"


class PosPayment(BaseModel):
    """Règlement d'un `PosOrder` — plusieurs lignes possibles (paiement
    mixte, cahier POS-5 : "espèces + mobile money")."""

    order = models.ForeignKey(PosOrder, on_delete=models.CASCADE, related_name="payments")
    method = models.ForeignKey(PosPaymentMethod, on_delete=models.PROTECT, related_name="+")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    # POS-5 : obligatoire si `method.requires_reference` — revalide cote
    # service (`services.orders.add_payment`), jamais seulement au niveau
    # du champ (une reference vide reste un CharField valide en base).
    reference = models.CharField(max_length=64, blank=True)
    received_at = models.DateTimeField()

    class Meta:
        db_table = "pos_payment"
        ordering = ["received_at"]

    def __str__(self) -> str:
        return f"{self.method.name} {self.amount}"


class PosSyncLog(BaseModel):
    """Journal de synchronisation (écran back-office cahier §13.5) —
    trace CHAQUE tentative de synchronisation d'une commande créée hors
    ligne, y compris les rejets/doublons (POS-3/POS-4 : "en cas de
    divergence... l'écart est porté au journal de synchronisation")."""

    OUTCOME_ACCEPTED = "accepted"
    OUTCOME_DUPLICATE = "duplicate"
    OUTCOME_REJECTED = "rejected"
    OUTCOME_CHOICES = [
        (OUTCOME_ACCEPTED, "Acceptée"),
        (OUTCOME_DUPLICATE, "Doublon ignoré"),
        (OUTCOME_REJECTED, "Rejetée"),
    ]

    register = models.ForeignKey(PosRegister, on_delete=models.PROTECT, related_name="+")
    session = models.ForeignKey(
        PosSession, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    order = models.ForeignKey(
        PosOrder, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    client_uuid = models.UUIDField()
    local_sequence = models.PositiveIntegerField(null=True, blank=True)
    outcome = models.CharField(max_length=16, choices=OUTCOME_CHOICES)
    detail = models.CharField(max_length=255, blank=True)
    synced_at = models.DateTimeField()

    class Meta:
        db_table = "pos_sync_log"
        ordering = ["-synced_at"]

    def __str__(self) -> str:
        return f"{self.client_uuid} — {self.outcome}"
