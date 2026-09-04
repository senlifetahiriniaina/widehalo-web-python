"""Entrepôt en étoile + dictionnaire d'indicateurs gouverné (cahier Phase 2
§12, préalable architectural des modules BI/Forecast/Strategy/WhatsApp).

**Dimensions conformes retenues** (réutilisées par plusieurs faits, donc
justifiant une vraie table dédiée) : `AnDimTemps` (jour), `AnDimTiers`
(client/fournisseur), `AnDimArticle` (produit/variante). **Simplification
assumée et disclosée** : le point de vente/canal (`PosRegister`) et le
compte comptable (`AccAccount`) ne sont PAS modélisés en dimensions
séparées — chacun n'est référencé que par un seul fait
(`AnFactTicketPos`/`AnFactEcriture` respectivement), donc la valeur d'une
dimension partagée (le principe même du modèle en étoile) ne s'applique
pas ; leurs quelques attributs sont dénormalisés directement sur la ligne
de fait concernée (dimension dégénérée), ce qui reste conforme aux
pratiques de modélisation dimensionnelle standard et économise 2 modèles
sur le budget d'architecture (`tests/architecture/test_budget.py`), déjà
sous tension pour les 4 chantiers Phase 2 restants. De même,
`core.User` (commercial/caissier) est référencé par FK Django réelle
(règle de couplage n°1 : `core` est le socle partagé, cf. précédent
`sales.SalesOrder.salesperson`) plutôt que par une dimension dédiée.

**Faits au grain de la ligne de document** (jamais pré-agrégés — condition
du drill-down promis par le cahier, §12 "Faits : grain document/ligne
métier") : `AnFactVente` (ligne de commande de vente), `AnFactTicketPos`
(ligne de ticket de caisse), `AnFactEncaissement` (règlement, le document
lui-même étant déjà le grain le plus fin côté `AccPayment`),
`AnFactEcriture` (ligne d'écriture comptable, publiée uniquement — cf.
`services/refresh.py`). Chaque fait porte un `source_*_id` (UUID de la
ligne/du document d'origine) qui sert de clé d'upsert idempotente au
rafraîchissement incrémental (`services/refresh.py`) : un même
rafraîchissement rejoué (ou un doublon d'événement) ne duplique jamais une
ligne de fait, il la remplace — condition du "replay idempotent" exigé par
le cahier.

**Gouvernance de l'accès analytique** (§12 "toute donnée décisionnelle
passe par le dictionnaire, jamais par une requête libre" — extension
directe de l'interdiction text-to-SQL de la Phase 1) : `AnMetricDefinition`
est la SEULE voie déclarée d'accès aux indicateurs — le moteur de requête
guidé du futur module BI (Phase 2 §13.1) ne doit jamais laisser un
utilisateur composer une agrégation ad hoc en dehors de ce catalogue.
`roles_autorises`/`maille_minimale` sont les deux garde-fous qui empêchent
la "fuite par agrégat" (un rôle sans droit sur le détail ne doit jamais
pouvoir la reconstituer en agrégeant lui-même une donnée plus fine que
celle que son rôle autorise) : la portée par rôle DOIT être appliquée à la
requête AVANT toute agrégation, jamais après — c'est au moteur de
requête du module BI de respecter cette contrainte, ce module-ci ne fait
que la déclarer."""

from __future__ import annotations

from django.db import models

from apps.core.models.base import BaseModel


class AnDimTemps(BaseModel):
    """Dimension temps matérialisée par jour. `exercice_fiscal`
    (simplification assumée et disclosée) : `core.Tenant` ne porte aucun
    mois de début d'exercice fiscal distinct de l'année civile — vaut donc
    toujours `annee`, substitut délibérément simple à un vrai
    partitionnement de table (aucun précédent de partitionnement Postgres
    dans ce dépôt) tant qu'un besoin réel de bascule d'exercice non
    calendaire n'est exprimé."""

    date = models.DateField()
    annee = models.PositiveSmallIntegerField()
    trimestre = models.PositiveSmallIntegerField()
    mois = models.PositiveSmallIntegerField()
    mois_libelle = models.CharField(max_length=16)
    semaine_iso = models.PositiveSmallIntegerField()
    jour_du_mois = models.PositiveSmallIntegerField()
    jour_semaine_iso = models.PositiveSmallIntegerField(help_text="1=lundi ... 7=dimanche")
    jour_semaine_libelle = models.CharField(max_length=16)
    est_weekend = models.BooleanField(default=False)
    exercice_fiscal = models.PositiveSmallIntegerField()

    class Meta:
        db_table = "an_dim_temps"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "date"], name="uniq_an_dim_temps_date")
        ]
        indexes = [models.Index(fields=["annee", "mois"])]
        ordering = ["date"]

    def __str__(self) -> str:
        return self.date.isoformat()


class AnDimTiers(BaseModel):
    """Miroir léger d'`apps.partners.Partner` (référencé par UUID nu, règle
    de couplage n°1) — attributs dénormalisés au moment du rafraîchissement,
    pas de FK Django. Aucun axe géographique/segment n'est modélisé ici :
    `Partner` ne porte aujourd'hui ni ville ni région ni segment structuré
    (vérifié en lisant `apps.partners.models.Partner`) — simplification
    assumée et disclosée, à enrichir si ces attributs apparaissent côté
    `partners` un jour."""

    partner_id = models.UUIDField()
    code = models.CharField(max_length=32, blank=True)
    nom = models.CharField(max_length=200)
    roles = models.JSONField(default=list, blank=True)
    is_placeholder = models.BooleanField(default=False)

    class Meta:
        db_table = "an_dim_tiers"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "partner_id"], name="uniq_an_dim_tiers")
        ]
        ordering = ["nom"]

    def __str__(self) -> str:
        return self.nom


class AnDimArticle(BaseModel):
    """Miroir léger d'`apps.catalog.ProductVariant` (référencé par UUID nu).
    Inclut les variantes NON vendables et les variantes générées par défaut
    (`is_placeholder`) : une ligne de vente déjà passée doit rester
    rattachable à sa dimension même si l'article a depuis été retiré de la
    vente — un entrepôt décisionnel ne doit jamais perdre l'historique au
    gré des changements du référentiel opérationnel."""

    variant_id = models.UUIDField()
    template_id = models.UUIDField(null=True, blank=True)
    reference = models.CharField(max_length=64, blank=True)
    libelle = models.CharField(max_length=200, blank=True)
    categorie_nom = models.CharField(max_length=120, blank=True)
    is_sellable = models.BooleanField(default=True)
    is_placeholder = models.BooleanField(default=False)

    class Meta:
        db_table = "an_dim_article"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "variant_id"], name="uniq_an_dim_article")
        ]
        ordering = ["libelle"]

    def __str__(self) -> str:
        return self.libelle or self.reference


class AnFactVente(BaseModel):
    """Grain = `sales.SalesOrderLine` (une ligne de commande de vente,
    jamais pré-agrégée). Ne couvre volontairement que `SalesOrder` (pas
    `SalesQuotation`, pas encore engagé/facturable) — cohérent avec le
    choix déjà fait par `apps.simulation` pour le même socle (cf.
    `apps.simulation.module`). `montant_ht_mga` = `subtotal` de la ligne
    (hors taxe) : `SalesOrderLine` ne décompose pas la TVA par ligne (champ
    absent), seul `SalesOrder.amount_tax` l'agrège au niveau document —
    simplification assumée et disclosée, le détail TVA reste consultable
    via `AnFactEcriture` (écritures comptables, qui ELLES portent la TVA
    ligne à ligne réelle)."""

    source_line_id = models.UUIDField()
    dim_temps = models.ForeignKey(AnDimTemps, on_delete=models.PROTECT, related_name="ventes")
    dim_tiers = models.ForeignKey(
        AnDimTiers, null=True, blank=True, on_delete=models.SET_NULL, related_name="ventes"
    )
    dim_article = models.ForeignKey(
        AnDimArticle, null=True, blank=True, on_delete=models.SET_NULL, related_name="ventes"
    )
    commercial = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    order_reference = models.CharField(max_length=64, blank=True)
    order_state = models.CharField(max_length=32, blank=True)
    canal = models.CharField(max_length=16, default="vente_directe")
    qty = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    unit_price_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    montant_ht_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    cost_estimate_mga = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    margin_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = "an_fact_vente"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "source_line_id"], name="uniq_an_fact_vente")
        ]
        indexes = [models.Index(fields=["dim_temps"]), models.Index(fields=["dim_tiers"])]

    def __str__(self) -> str:
        return f"{self.order_reference} — {self.montant_ht_mga}"


class AnFactTicketPos(BaseModel):
    """Grain = `pos.PosOrderLine`. `point_vente_code`/`point_vente_nom`
    (dimension dégénérée, cf. docstring de module) proviennent de
    `PosRegister` au moment du ticket."""

    source_line_id = models.UUIDField()
    dim_temps = models.ForeignKey(AnDimTemps, on_delete=models.PROTECT, related_name="tickets_pos")
    dim_tiers = models.ForeignKey(
        AnDimTiers, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets_pos"
    )
    dim_article = models.ForeignKey(
        AnDimArticle, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets_pos"
    )
    vendeur = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    point_vente_code = models.CharField(max_length=16, blank=True)
    point_vente_nom = models.CharField(max_length=120, blank=True)
    ticket_number = models.CharField(max_length=32, blank=True)
    order_type = models.CharField(max_length=8, blank=True)
    line_type = models.CharField(max_length=16, blank=True)
    canal = models.CharField(max_length=16, default="pos")
    qty = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    unit_price_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    montant_ht_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    montant_tva_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    montant_ttc_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)

    class Meta:
        db_table = "an_fact_ticket_pos"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "source_line_id"], name="uniq_an_fact_ticket_pos"
            )
        ]
        indexes = [models.Index(fields=["dim_temps"]), models.Index(fields=["point_vente_code"])]

    def __str__(self) -> str:
        return f"{self.ticket_number} — {self.montant_ttc_mga}"


class AnFactEncaissement(BaseModel):
    """Grain = `accounting.AccPayment` (le document lui-même : un
    règlement n'a pas de ligne de détail côté `accounting`)."""

    source_payment_id = models.UUIDField()
    dim_temps = models.ForeignKey(
        AnDimTemps, on_delete=models.PROTECT, related_name="encaissements"
    )
    dim_tiers = models.ForeignKey(
        AnDimTiers, null=True, blank=True, on_delete=models.SET_NULL, related_name="encaissements"
    )
    reference = models.CharField(max_length=64, blank=True)
    direction = models.CharField(max_length=16, blank=True)
    method = models.CharField(max_length=16, blank=True)
    montant_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    state = models.CharField(max_length=16, blank=True)

    class Meta:
        db_table = "an_fact_encaissement"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "source_payment_id"], name="uniq_an_fact_encaissement"
            )
        ]
        indexes = [models.Index(fields=["dim_temps"])]

    def __str__(self) -> str:
        return f"{self.reference} — {self.montant_mga}"


class AnFactEcriture(BaseModel):
    """Grain = `accounting.AccMoveLine`. Ne couvre que les écritures
    `state=posted` (`services/refresh.py`) : une écriture brouillon est par
    nature provisoire/modifiable, l'entrepôt décisionnel ne doit refléter
    que ce qui est définitivement publié (même discipline d'immuabilité que
    `AccMove` lui-même, RG-ACC-2/RG-ACC-3). `compte_*` = dimension
    dégénérée (cf. docstring de module) depuis `AccAccount`."""

    source_line_id = models.UUIDField()
    dim_temps = models.ForeignKey(AnDimTemps, on_delete=models.PROTECT, related_name="ecritures")
    dim_tiers = models.ForeignKey(
        AnDimTiers, null=True, blank=True, on_delete=models.SET_NULL, related_name="ecritures"
    )
    compte_code = models.CharField(max_length=20, blank=True)
    compte_libelle = models.CharField(max_length=200, blank=True)
    compte_classe_pcg = models.PositiveSmallIntegerField(null=True, blank=True)
    move_reference = models.CharField(max_length=64, blank=True)
    move_type = models.CharField(max_length=24, blank=True)
    debit_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    credit_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    solde_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)

    class Meta:
        db_table = "an_fact_ecriture"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "source_line_id"], name="uniq_an_fact_ecriture"
            )
        ]
        indexes = [models.Index(fields=["dim_temps"]), models.Index(fields=["compte_code"])]

    def __str__(self) -> str:
        return f"{self.compte_code} D{self.debit_mga}/C{self.credit_mga}"


class AnFactMouvementStock(BaseModel):
    """Grain = `stocks.StkMove` validé (`state=done` uniquement — un
    mouvement `draft`/`cancelled` n'est pas un fait constaté, même
    discipline que `AnFactEcriture` qui ne couvre que les écritures
    `posted`). Bloc Transverse, T1 (FOR-11 : preuve d'extension du
    modèle en étoile "sans reprise", développée juste après que son
    domaine source — Bloc A/P2 — soit fiabilisé).

    Aucune dimension tiers : `StkMove` ne porte aucun `partner_id` (la
    notion de fournisseur/client est portée par le TYPE de
    `location_from`/`location_to`, jamais par une référence directe) —
    contrairement à `AnFactVente`/`AnFactEncaissement`/`AnFactEcriture`,
    ce fait n'a donc pas de `dim_tiers`, simplification assumée et
    disclosée plutôt qu'une reconstruction approximative. Entrepôts/
    emplacements source et destination : dimensions dégénérées (mêmes
    principes que `point_vente_code` sur `AnFactTicketPos`) — un
    mouvement de stock traverse potentiellement deux entrepôts distincts
    (transfert inter-dépôts), donc jamais une seule paire
    entrepôt/emplacement comme les autres faits dégénérés à un seul
    site."""

    source_move_id = models.UUIDField()
    dim_temps = models.ForeignKey(
        AnDimTemps, on_delete=models.PROTECT, related_name="mouvements_stock"
    )
    dim_article = models.ForeignKey(
        AnDimArticle,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="mouvements_stock",
    )
    move_reference = models.CharField(max_length=64, blank=True)
    move_type = models.CharField(max_length=32, blank=True)
    lot_name = models.CharField(max_length=64, blank=True)
    entrepot_origine_code = models.CharField(max_length=16, blank=True)
    emplacement_origine_code = models.CharField(max_length=32, blank=True)
    entrepot_destination_code = models.CharField(max_length=16, blank=True)
    emplacement_destination_code = models.CharField(max_length=32, blank=True)
    qty = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    uom = models.CharField(max_length=16, blank=True)
    unit_cost_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    value_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    source_document = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "an_fact_mouvement_stock"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "source_move_id"], name="uniq_an_fact_mouvement_stock"
            )
        ]
        indexes = [models.Index(fields=["dim_temps"]), models.Index(fields=["move_type"])]

    def __str__(self) -> str:
        return f"{self.move_reference} — {self.move_type}"


class AnFactReception(BaseModel):
    """Grain = `purchase.PurReceiptLine` (un événement de réception, cf.
    docstring de ce modèle — pas d'en-tête `PurReceipt` séparé). Bloc
    Transverse, T2 (FOR-11, ferme ACH-10 : « aucun fait analytique
    achats/coût débarqué à comparer au moteur de valorisation »).

    `cout_debarque_unitaire_mga` : coût unitaire CUMP COURANT de la
    variante (`stocks.services.public.get_variant_unit_cost`, résolu au
    moment du rafraîchissement — jamais recalculé/figé à la réception),
    distinct de `unit_price_mga` (prix d'achat brut saisi sur la commande,
    AVANT toute réallocation de coût débarqué). C'est la comparaison
    explicite entre ces deux valeurs — le fait porte les deux — qui ferme
    ACH-10 : un écart révèle soit un coût débarqué encore non appliqué,
    soit une anomalie de valorisation. `None` si la variante n'a plus
    aucune couche de valorisation active au moment du rafraîchissement
    (jamais une exception — même discipline que `get_variant_unit_cost`
    lui-même)."""

    source_receipt_line_id = models.UUIDField()
    dim_temps = models.ForeignKey(AnDimTemps, on_delete=models.PROTECT, related_name="receptions")
    dim_tiers = models.ForeignKey(
        AnDimTiers, null=True, blank=True, on_delete=models.SET_NULL, related_name="receptions"
    )
    dim_article = models.ForeignKey(
        AnDimArticle, null=True, blank=True, on_delete=models.SET_NULL, related_name="receptions"
    )
    order_reference = models.CharField(max_length=64, blank=True)
    quality_status = models.CharField(max_length=16, blank=True)
    qty_received = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    uom = models.CharField(max_length=16, blank=True)
    unit_price_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    cout_debarque_unitaire_mga = models.DecimalField(
        max_digits=18, decimal_places=4, null=True, blank=True
    )

    class Meta:
        db_table = "an_fact_reception"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "source_receipt_line_id"], name="uniq_an_fact_reception"
            )
        ]
        indexes = [models.Index(fields=["dim_temps"]), models.Index(fields=["dim_tiers"])]

    def __str__(self) -> str:
        return f"{self.order_reference} — {self.qty_received}"


class AnFactOrdreFabrication(BaseModel):
    """Grain = `mrp.MrpOrder` clôturé (`state=closed`). Bloc Transverse,
    T3 (FOR-11).

    `cout_reel_mga`/`cout_planifie_mga` reprennent directement
    `MrpOrder.cost_total_mga`/`cost_total_planned_mga` (Bloc C, C3 — déjà
    calculés et persistés côté `mrp`, jamais recalculés ici).
    `ecart_cout_mga` (= réel − planifié) est PERSISTÉ, pas seulement
    calculable au moment de la lecture — même discipline que
    `AnFactEcriture.solde_mga` (`debit_mga - credit_mga`), pour rester
    directement agrégeable/filtrable via le moteur de requête guidé de
    `apps.bi` sans expression dérivée côté client.

    Aucun `closed_at` dédié sur `MrpOrder` — `date`/`dim_temps` utilise
    `updated_at.date()` comme proxy (même discipline documentée que
    `mrp.services.public.list_closed_orders`, déjà consommée par
    `stocks.services.consistency` pour le même besoin)."""

    source_order_id = models.UUIDField()
    dim_temps = models.ForeignKey(
        AnDimTemps, on_delete=models.PROTECT, related_name="ordres_fabrication"
    )
    dim_article = models.ForeignKey(
        AnDimArticle,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ordres_fabrication",
    )
    order_reference = models.CharField(max_length=64, blank=True)
    atelier_code = models.CharField(max_length=32, blank=True)
    qty_produced = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    qty_scrapped = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    cout_reel_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    cout_planifie_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    ecart_cout_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)

    class Meta:
        db_table = "an_fact_ordre_fabrication"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "source_order_id"], name="uniq_an_fact_ordre_fabrication"
            )
        ]
        indexes = [models.Index(fields=["dim_temps"]), models.Index(fields=["atelier_code"])]

    def __str__(self) -> str:
        return f"{self.order_reference} — écart {self.ecart_cout_mga}"


class AnWarehouseState(BaseModel):
    """Singleton par tenant : verrou de rafraîchissement + jalons
    (watermarks) `updated_at` par source, condition du rafraîchissement
    INCREMENTAL exigé par le cahier (§12) — chaque rafraîchissement ne
    relit que ce qui a changé depuis le jalon précédent, jamais
    l'intégralité de l'historique."""

    is_locked = models.BooleanField(default=False)
    locked_at = models.DateTimeField(null=True, blank=True)
    last_successful_refresh_at = models.DateTimeField(null=True, blank=True)
    watermark_sales_orderline = models.DateTimeField(null=True, blank=True)
    watermark_pos_orderline = models.DateTimeField(null=True, blank=True)
    watermark_acc_payment = models.DateTimeField(null=True, blank=True)
    watermark_acc_moveline = models.DateTimeField(null=True, blank=True)
    # Bloc Transverse, T1.
    watermark_stk_move = models.DateTimeField(null=True, blank=True)
    # Bloc Transverse, T2.
    watermark_pur_receipt_line = models.DateTimeField(null=True, blank=True)
    # Bloc Transverse, T3.
    watermark_mrp_order = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "an_warehouse_state"
        constraints = [
            models.UniqueConstraint(fields=["tenant"], name="uniq_an_warehouse_state_tenant")
        ]

    def __str__(self) -> str:
        return f"État entrepôt {self.tenant_id}"


class AnRefreshRun(BaseModel):
    """Journal d'exécution du rafraîchissement (§12 "traçable, avec
    contrôle de réconciliation") — une ligne par exécution, jamais
    modifiée après coup (sauf par la commande elle-même en cours
    d'exécution, cf. `services/refresh.py`)."""

    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_RUNNING, "En cours"),
        (STATUS_SUCCESS, "Succès"),
        (STATUS_FAILED, "Échec"),
    ]

    TRIGGER_CRON = "cron"
    TRIGGER_MANUAL = "manual"
    TRIGGER_CHOICES = [
        (TRIGGER_CRON, "Planifié"),
        (TRIGGER_MANUAL, "Manuel"),
    ]

    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_RUNNING)
    triggered_by = models.CharField(max_length=16, choices=TRIGGER_CHOICES, default=TRIGGER_CRON)
    rows_processed = models.PositiveIntegerField(default=0)
    # Contrôle de réconciliation (§12 "un chiffre faux en comité de
    # direction coûte des mois de crédibilité") : compare le total agrégé
    # de `AnFactVente` à `sales.services.public.get_revenue_summary` sur la
    # même période — `None` tant qu'aucun contrôle n'a encore été exécuté
    # (distinct de `False`, contrôle exécuté et en écart).
    reconciliation_ok = models.BooleanField(null=True, blank=True)
    reconciliation_detail = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        db_table = "an_refresh_run"
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.started_at:%Y-%m-%d %H:%M} — {self.status}"


class AnMetricDefinition(BaseModel):
    """Dictionnaire d'indicateurs gouverné (§12) — SEULE voie déclarée
    d'accès aux données décisionnelles (cf. docstring de module).

    Versionné par INSERTION, jamais par écrasement (BI-9, cahier Phase 2
    §13.1 : « toute modification de définition d'un indicateur crée une
    version, conserve la précédente, liste les rapports impactés » —
    corrige une simplification assumée à tort lors du chantier fondateur,
    qui écrasait la ligne courante) : `(tenant, code, version)` est la clef
    d'unicité réelle, `is_current` marque la SEULE ligne active par
    `(tenant, code)` à un instant donné — `services/dictionary.py::
    register_metric` insère toujours une nouvelle ligne `version+1` et
    bascule `is_current` de l'ancienne à la nouvelle dans la même
    transaction, jamais de `UPDATE` en place sur une ligne existante. Une
    ligne non courante reste interrogeable via `services/dictionary.py::
    list_metric_history` — c'est la définition exacte utilisée par un
    rapport déjà généré qui doit rester reconstituable, pas seulement le
    diff générique du journal d'audit (déjà couvert automatiquement,
    `AnMetricDefinition` héritant de `BaseModel`, cf. `apps.core.
    audit_signals`)."""

    STATUT_BROUILLON = "brouillon"
    STATUT_PUBLIE = "publie"
    STATUT_DEPRECIE = "deprecie"
    STATUT_CHOICES = [
        (STATUT_BROUILLON, "Brouillon"),
        (STATUT_PUBLIE, "Publié"),
        (STATUT_DEPRECIE, "Déprécié"),
    ]

    code = models.CharField(max_length=64)
    libelle = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    # Description humaine du mode de calcul — jamais une requête SQL
    # exécutable (§12, extension directe de l'interdiction text-to-SQL de
    # la Phase 1 : aucun module ne doit jamais évaluer ce champ comme du
    # code).
    formule = models.TextField(blank=True)
    unite = models.CharField(max_length=16, blank=True)
    module_source = models.CharField(max_length=32, blank=True)
    axes_autorises = models.JSONField(default=list, blank=True)
    roles_autorises = models.JSONField(default=list, blank=True)
    # Grain le plus fin auquel cet indicateur peut être restitué à un rôle
    # donné (ex. "tiers" interdit une ventilation par tiers individuel à un
    # rôle qui n'y a pas droit) — garde-fou anti "fuite par agrégat".
    maille_minimale = models.CharField(max_length=32, blank=True)
    proprietaire = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    statut = models.CharField(max_length=16, choices=STATUT_CHOICES, default=STATUT_BROUILLON)
    version = models.PositiveIntegerField(default=1)
    date_effet = models.DateField(null=True, blank=True)
    # Cf. docstring de classe : la SEULE ligne active par (tenant, code) —
    # `register_metric` bascule ce booléen atomiquement à chaque nouvelle
    # version, jamais de suppression ni d'écrasement d'une ligne existante.
    is_current = models.BooleanField(default=True)

    class Meta:
        db_table = "an_metric_definition"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code", "version"], name="uniq_an_metric_definition_version"
            ),
            models.UniqueConstraint(
                fields=["tenant", "code"],
                condition=models.Q(is_current=True),
                name="uniq_an_metric_definition_current",
            ),
        ]
        ordering = ["module_source", "code", "-version"]

    def __str__(self) -> str:
        return f"{self.code} ({self.statut})"
