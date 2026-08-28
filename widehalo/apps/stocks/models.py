"""Stocks (§5.8, ST1 du sous-sequencement `stocks` — cf. plan) : squelette
de l'app, entites de configuration/master-data de la hierarchie physique de
stockage — `StkWarehouse` (entrepot/site), `StkLocation` (emplacement, arbre
`parent`) et `StkDefectType` (referentiel de types de defaut qualite,
consomme par `StkQualityState` en ST3).

`stocks` est le module qui LEVE la plupart des stubs des modules
precedents (`sales`/`purchase`/`accounting`/`mrp`) plutot que d'en
introduire de nouveaux — cf. section "Decisions de replanification" et
"Module `stocks`" du plan. C'est pourquoi la discipline "stub honnete" ne
s'applique quasiment jamais A l'INTERIEUR de ce module lui-meme : quand
`stocks` a besoin d'une donnee externe, elle passe deja par un
`services.public` reel (`catalog` des ST2/ST3).

**Emplacements virtuels (RG-STK-1, invariant central de double entree,
implemente en ST2)** : `StkLocation.type` inclut, en plus des emplacements
physiques internes, des types "virtuels" au sens Odoo du terme —
`fournisseur`/`client`/`production`/`inventaire`/`rebut`/`transit`/
`sous_traitant` ne representent pas un rayonnage reel mais une frontiere
comptable du systeme de stock (l'exterieur cote fournisseur, l'exterieur
cote client, la consommation en production, l'ecart d'inventaire, le
rebut, un sas de transit, un sous-traitant externe). Chaque `StkMove`
(ST2) a TOUJOURS une origine et une destination `StkLocation`, y compris
quand l'un des deux est virtuel — jamais de mouvement "sans origine" ou
"sans destination", meme une entree fournisseur part conceptuellement de
l'emplacement virtuel `fournisseur`. Ce patron permet de garder la somme
algebrique des mouvements nulle par produit (verifie par le test de
propriete Hypothesis RG-STK-1 des ST2), condition necessaire de la
tracabilite complete exigee par le CDC.

Regle de couplage n1 (identique a `sales`/`purchase`/`crm`/`mrp`) :
`stocks` ne fait jamais de FK Django vers `apps.catalog`/`apps.mrp`/
`apps.sales`/`apps.accounting` — ces entites sont referencees par UUID nu
(ex. futur `StkQuant.variant_id`), resolues via `services.public` de
chaque app quand une information affichable est necessaire. Le seul FK
"reel" hors du perimetre `stocks` est vers `core.User` (responsable
d'entrepot), qui appartient au socle et n'est pas une autre app metier."""

from __future__ import annotations

from django.db import models

from apps.core.models.base import BaseModel, ReferenceMixin

# `ReferenceMixin` n'est PAS utilise en ST1 : aucun des trois modeles
# ci-dessous n'est un document sequence (`StkWarehouse`/`StkLocation`/
# `StkDefectType` sont de la config/master-data, meme categorie que
# `MrpWorkshop` — verifie explicitement ne pas utiliser ce mixin non plus).
# Choix delibere, pas un oubli — d'ou ce commentaire plutot qu'un import
# mort.


class StkWarehouse(BaseModel):
    """Entrepot/site de stockage. Meme categorie que `MrpWorkshop`
    (config/master-data, pas un document sequence) : pas de
    `ReferenceMixin` — precedent verifie explicitement sur
    `apps.mrp.models.MrpWorkshop`, qui n'utilise pas ce mixin non plus.

    `name` : le CDC annote ce champ "(i18n)" (§5.8, entite `StkWarehouse`).
    Precedent verifie sur les autres annotations "(i18n)" deja
    rencontrees dans ce depot (ex. `MrpWorkshop.name`, `CrmPipeline.name`)
    : aucune ne s'est jamais materialisee en traduction de DONNEES stockees
    (pas de `django-modeltranslation`, pas de champs `name_en`/`name_fr`) —
    l'annotation signifie seulement que le LIBELLE affiche a l'utilisateur
    (les labels de formulaire, les choix, les messages) doit passer par
    `gettext`/`{% trans %}` cote UI, jamais que la valeur SAISIE par
    l'utilisateur pour CE champ doive etre traduite. `name` reste donc un
    `CharField` simple, coherent avec ce precedent constant."""

    TYPE_PRINCIPAL = "principal"
    TYPE_ATELIER = "atelier"
    TYPE_MAGASIN = "magasin"
    TYPE_TRANSIT = "transit"
    TYPE_SOUS_TRAITANT = "sous_traitant"
    TYPE_CHOICES = [
        (TYPE_PRINCIPAL, "Principal"),
        (TYPE_ATELIER, "Atelier"),
        (TYPE_MAGASIN, "Magasin"),
        (TYPE_TRANSIT, "Transit"),
        (TYPE_SOUS_TRAITANT, "Sous-traitant"),
    ]

    code = models.CharField(max_length=32)
    name = models.CharField(max_length=150)
    address = models.CharField(max_length=255, blank=True)
    manager = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    type = models.CharField(max_length=16, choices=TYPE_CHOICES, default=TYPE_PRINCIPAL)

    class Meta:
        db_table = "stk_warehouse"

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class StkLocation(BaseModel):
    """Emplacement de stockage, noeud d'un arbre `parent`/`children` au sein
    d'un `StkWarehouse`. Meme categorie master-data que `StkWarehouse`
    (pas de `ReferenceMixin`).

    Arbre self-referentiel : patron le plus proche disponible dans ce depot
    est `apps.catalog.models.Category.parent` / `apps.accounting.models.
    AccAccount.parent` (`on_delete=SET_NULL`, `related_name="children"`).
    Deviation assumee ici : `on_delete=CASCADE` plutot que `SET_NULL` — un
    emplacement enfant n'a pas de sens metier une fois son parent
    definitivement supprime (contrairement a une categorie produit ou un
    compte comptable, qui peuvent legitimement devenir "orphelins" et
    rester consultables). En pratique cette branche ne s'execute quasiment
    jamais : toute suppression applicative passe par `BaseModel.soft_delete`
    (`is_active=False`), jamais un DELETE SQL reel.

    `type` reprend les emplacements virtuels documentes dans le docstring
    du module ci-dessus (RG-STK-1) en plus des emplacements physiques
    internes usuels."""

    TYPE_INTERNE = "interne"
    TYPE_FOURNISSEUR = "fournisseur"
    TYPE_CLIENT = "client"
    TYPE_PRODUCTION = "production"
    TYPE_INVENTAIRE = "inventaire"
    TYPE_REBUT = "rebut"
    TYPE_TRANSIT = "transit"
    TYPE_SOUS_TRAITANT = "sous_traitant"
    TYPE_CHOICES = [
        (TYPE_INTERNE, "Interne"),
        (TYPE_FOURNISSEUR, "Fournisseur (virtuel)"),
        (TYPE_CLIENT, "Client (virtuel)"),
        (TYPE_PRODUCTION, "Production (virtuel)"),
        (TYPE_INVENTAIRE, "Inventaire (virtuel)"),
        (TYPE_REBUT, "Rebut"),
        (TYPE_TRANSIT, "Transit"),
        (TYPE_SOUS_TRAITANT, "Sous-traitant"),
    ]

    warehouse = models.ForeignKey(StkWarehouse, on_delete=models.CASCADE, related_name="locations")
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=150)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    type = models.CharField(max_length=16, choices=TYPE_CHOICES, default=TYPE_INTERNE)
    # Redondant avec `type == TYPE_REBUT` mais explicitement liste comme
    # champ separe dans le tableau d'entites du CDC (§5.8) — conserve tel
    # quel, simple raccourci de filtrage/affichage.
    is_scrap = models.BooleanField(default=False)
    # Capacite physique optionnelle, aucune unite imposee a ce stade (ST1) —
    # informatif uniquement, pas encore exploite par une regle de
    # remplissage/alerte (hors perimetre ST1).
    capacity = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    # Code-barres/QR de l'emplacement — champ present des ST1 (entite du
    # CDC), generation reelle des etiquettes differee a STK-BC1 (ST7).
    barcode = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "stk_location"

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class StkDefectType(BaseModel):
    """Referentiel des types de defaut qualite (§5.8) — pas de
    `ReferenceMixin`, meme categorie master-data que `StkWarehouse`/
    `StkLocation`.

    `severity` : le CDC ne fixe pas d'echelle. Choix retenu ici : memes
    libellés que les futurs etats de `StkQualityState` (ST3) —
    `mineur`/`majeur`/`critique` — plutot qu'un entier 1-5 sans semantique
    metier, pour que ST3 puisse reutiliser directement cette valeur sans
    table de correspondance a construire."""

    CATEGORY_TISSU = "tissu"
    CATEGORY_COUTURE = "couture"
    CATEGORY_COULEUR = "couleur"
    CATEGORY_DIMENSION = "dimension"
    CATEGORY_FINITION = "finition"
    CATEGORY_EMBALLAGE = "emballage"
    CATEGORY_CHOICES = [
        (CATEGORY_TISSU, "Tissu"),
        (CATEGORY_COUTURE, "Couture"),
        (CATEGORY_COULEUR, "Couleur"),
        (CATEGORY_DIMENSION, "Dimension"),
        (CATEGORY_FINITION, "Finition"),
        (CATEGORY_EMBALLAGE, "Emballage"),
    ]

    SEVERITY_MINEUR = "mineur"
    SEVERITY_MAJEUR = "majeur"
    SEVERITY_CRITIQUE = "critique"
    SEVERITY_CHOICES = [
        (SEVERITY_MINEUR, "Mineur"),
        (SEVERITY_MAJEUR, "Majeur"),
        (SEVERITY_CRITIQUE, "Critique"),
    ]

    code = models.CharField(max_length=32)
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES)
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, default=SEVERITY_MINEUR)
    default_action = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "stk_defect_type"

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


# ST2 (cf. plan, §5.8) : le coeur du module — `StkLot`, `StkQuant`,
# `StkMove` (RG-STK-1, double entree) et `StkValuationLayer` (RG-STK-2,
# valorisation). `variant_id` reste un UUID nu partout (regle de couplage
# n1, cf. docstring de module ci-dessus) : `stocks` ne fait jamais de FK
# vers `apps.catalog`.


class StkLot(BaseModel):
    """Lot/numero de serie de tracabilite (RG-STK-3, §5.8). Pas de
    `ReferenceMixin` : le CDC ne liste pas de champ "reference" sequence
    pour cette entite dans son tableau §5.8 (contrairement a `StkMove`
    ci-dessous) — `name` EST l'identifiant metier du lot (le numero de lot
    lui-meme, souvent impose par le fournisseur/la production, jamais
    genere par une sequence interne comme le serait un numero de document).
    Categorie proche d'une reference/master-data plutot que d'un document
    sequence, meme raisonnement que `StkWarehouse`/`StkLocation`/
    `StkDefectType` en ST1.

    `UniqueConstraint(tenant, variant_id, name)` : un couple (produit, nom
    de lot) est unique PAR TENANT — deux lots differents du meme produit
    ne peuvent pas partager le meme identifiant au sein d'un meme tenant.
    Contrainte assumee, non explicitement formulee par le CDC mais
    necessaire pour que `StkQuant`/`StkMove` puissent referencer un lot
    sans ambiguite. `tenant` est explicitement inclus (a la difference
    d'un premier jet sans tenant, corrige) : sans lui, un aller-retour
    export/import (`apps.core.services.tenant_export`, T3) entre deux
    tenants qui coexistent en base collisionnerait sur ce couple —
    exactement le piege deja documente pour
    `core.SavedTableView.Meta.constraints` (`uniq_saved_view`), evite ici
    des la conception plutot que laisse comme limitation connue.

    `certificate` : reference a un document attache, meme convention que
    `apps.purchase.models.PurCri.attachment_document_ids` (JSONField de
    UUID, jamais de FK Django vers `core.Document`) — ici un champ
    singulier plutot qu'une liste (un lot n'a normalement qu'un seul
    certificat de conformite/analyse), mais meme type de champ (UUID nu,
    nullable) pour rester coherent avec ce precedent."""

    variant_id = models.UUIDField()
    name = models.CharField(max_length=64)
    date_production = models.DateField(null=True, blank=True)
    # Alimente STK-FEFO1 (ST6, premier perime premier sorti) — simple champ
    # de donnee ici, aucune logique FEFO construite en ST2.
    date_expiry = models.DateField(null=True, blank=True)
    supplier_lot = models.CharField(max_length=64, blank=True)
    origin = models.CharField(max_length=255, blank=True)
    certificate_document_id = models.UUIDField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "stk_lot"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "variant_id", "name"], name="uniq_stk_lot_variant_name"
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.variant_id})"


class StkQuant(BaseModel):
    """Photo instantanee de la quantite/valeur disponible pour un couple
    (produit, emplacement, lot) — **vue materialisee derivee de l'historique
    `StkMove`, jamais une source de verite independante**. Aucune API/ecran
    ne cree ou modifie un `StkQuant` directement : seul
    `services.moves.validate_move` le fait, en repercutant chaque mouvement
    valide sur les deux quants concernes (origine et destination). Pas de
    `ReferenceMixin` : ce n'est pas un document que l'utilisateur cree, au
    meme titre qu'une ligne d'ecriture derivee.

    **Emplacements virtuels** (cf. docstring de module ci-dessus, RG-STK-1) :
    un `StkQuant` est materialise pour TOUTE combinaison (variant,
    emplacement, lot) touchee par un mouvement valide, y compris quand
    l'emplacement est virtuel (`fournisseur`/`client`/etc.) — patron
    double-entree façon Odoo. Un emplacement `fournisseur` accumule donc une
    quantite negative au fil des receptions (le stock reel augmente pendant
    que le "stock" du fournisseur virtuel diminue symetriquement), et un
    emplacement `client` accumule une quantite positive au fil des
    livraisons. C'est le choix qui rend l'invariant RG-STK-1 ("aucune
    quantite n'apparait ni ne disparait sans contrepartie") trivialement
    verifiable par sommation sur TOUS les emplacements — c'est exactement
    ce que verifie le test de propriete Hypothesis de ce lot
    (`test_hypothesis_properties.py`). Une quantite negative sur un
    emplacement virtuel n'est donc jamais une anomalie, contrairement a une
    quantite negative sur un emplacement interne (RG-STK-10, stock negatif
    interdit par defaut, ST7).

    `UniqueConstraint(variant_id, location, lot)` avec `nulls_distinct=False`
    (Django 5.0+) : un quant est LA combinaison unique produit x
    emplacement x lot — deux lignes ne peuvent jamais coexister pour la
    meme combinaison, y compris quand `lot` est NULL (produit non trace par
    lot). Sans `nulls_distinct=False`, PostgreSQL traiterait chaque NULL
    comme distinct des autres et autoriserait plusieurs quants "sans lot"
    pour le meme (variant, emplacement) — brisant l'invariant meme de cette
    entite."""

    variant_id = models.UUIDField()
    location = models.ForeignKey(StkLocation, on_delete=models.PROTECT, related_name="quants")
    lot = models.ForeignKey(
        StkLot, null=True, blank=True, on_delete=models.SET_NULL, related_name="quants"
    )
    qty = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    qty_reserved = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    # Pas de FK `catalog.UnitOfMeasure` (regle de couplage n1) : texte libre
    # tel quel, meme discipline que `StkMove.uom` ci-dessous.
    uom = models.CharField(max_length=16, blank=True)
    unit_cost_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    # `qty * unit_cost_mga`, synchronise par `services.moves`/`services.quants`
    # — jamais recalcule dans un `save()` de modele (discipline etablie de
    # cette session : les totaux calcules vivent dans la couche service).
    value_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    last_count_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "stk_quant"
        constraints = [
            models.UniqueConstraint(
                fields=["variant_id", "location", "lot"],
                name="uniq_stk_quant_variant_location_lot",
                nulls_distinct=False,
            )
        ]

    def __str__(self) -> str:
        return f"{self.variant_id} @ {self.location_id} = {self.qty}"


class StkMove(BaseModel, ReferenceMixin):
    """Mouvement de stock — coeur de RG-STK-1 (double entree stricte, §5.8).
    `ReferenceMixin` : c'est un document sequence (le CDC liste un champ
    "reference" pour cette entite), contrairement a `StkLot`/`StkQuant`
    ci-dessus.

    **Discipline RG-STK-1** : `qty` est TOUJOURS strictement positive — la
    direction du mouvement s'exprime exclusivement par `location_from`/
    `location_to`, jamais par un signe sur la quantite (contrairement, par
    exemple, a un solde comptable qui peut etre negatif). Un `StkMove` a
    TOUJOURS les deux emplacements renseignes, y compris quand l'un des
    deux est virtuel — jamais de mouvement "sans origine" ou "sans
    destination". C'est cette structure meme (une seule ligne, toujours un
    from ET un to) qui EST la double entree ici, a la difference de
    `AccMove`/`AccMoveLine` en `accounting` ou la partie double se
    materialise par plusieurs LIGNES debit/credit distinctes au sein d'une
    meme ecriture.

    **Choix delibere : pas de contrainte DB CHECK pour la somme algebrique
    nulle par produit.** Contrairement a RG-ACC-1 (`accounting`, migration
    0003) qui pose un CHECK `total_debit = total_credit` PARCE QUE cette
    egalite est une propriete emergente calculee sur plusieurs lignes (donc
    verifiable/cassable independamment de chaque ligne), l'invariant
    RG-STK-1 est ici vrai PAR CONSTRUCTION du modele : chaque ligne
    `StkMove` porte deja exactement un from et un to, donc la somme
    algebrique globale (increment au to, decrement au from, pour chaque
    mouvement) est nulle par construction, quelle que soit la donnee — il
    n'existe aucun etat de la table `stk_move` qui violerait cet invariant,
    donc aucun CHECK ne serait jamais utile a poser dessus. Seul le test de
    propriete Hypothesis (`test_hypothesis_properties.py`) sert de garde
    de non-regression sur la LOGIQUE DE SERVICE qui traduit les mouvements
    en quants (`services.moves.validate_move`), pas sur la forme de la
    table elle-meme.

    **La seule contrainte DB qui a un sens ici** (migration `RunSQL`, meme
    patron RG-ACC-1) : `CHECK (location_from_id <> location_to_id)` — un
    mouvement vers/depuis le MEME emplacement n'est jamais valide (aucune
    circonstance metier ne le justifie), garde en base en plus de la garde
    de service `create_move` (meme discipline "ceinture et bretelles" que
    RG-ACC-1)."""

    STATE_DRAFT = "draft"
    STATE_DONE = "done"
    STATE_CANCELLED = "cancelled"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_DONE, "Valide"),
        (STATE_CANCELLED, "Annule"),
    ]

    TYPE_RECEPTION = "reception"
    TYPE_LIVRAISON = "livraison"
    TYPE_TRANSFERT_INTERNE = "transfert_interne"
    TYPE_PRODUCTION_IN = "production_in"
    TYPE_PRODUCTION_OUT = "production_out"
    TYPE_RETOUR = "retour"
    TYPE_REBUT = "rebut"
    TYPE_AJUSTEMENT = "ajustement"
    TYPE_SOUS_TRAITANCE = "sous_traitance"
    MOVE_TYPE_CHOICES = [
        (TYPE_RECEPTION, "Reception"),
        (TYPE_LIVRAISON, "Livraison"),
        (TYPE_TRANSFERT_INTERNE, "Transfert interne"),
        (TYPE_PRODUCTION_IN, "Entree production"),
        (TYPE_PRODUCTION_OUT, "Sortie production"),
        (TYPE_RETOUR, "Retour"),
        (TYPE_REBUT, "Rebut"),
        (TYPE_AJUSTEMENT, "Ajustement"),
        (TYPE_SOUS_TRAITANCE, "Sous-traitance"),
    ]

    variant_id = models.UUIDField()
    lot = models.ForeignKey(
        StkLot, null=True, blank=True, on_delete=models.SET_NULL, related_name="moves"
    )
    qty = models.DecimalField(max_digits=18, decimal_places=4)
    uom = models.CharField(max_length=16, blank=True)
    location_from = models.ForeignKey(
        StkLocation, on_delete=models.PROTECT, related_name="moves_out"
    )
    location_to = models.ForeignKey(StkLocation, on_delete=models.PROTECT, related_name="moves_in")
    date = models.DateField()
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_DRAFT)
    move_type = models.CharField(max_length=32, choices=MOVE_TYPE_CHOICES)
    # Reference libre vers le document d'origine (commande d'achat/de vente,
    # ordre de fabrication...), resolue par l'APPELANT via son propre
    # `services.public` avant d'etre transmise ici — `stocks` ne va jamais
    # chercher lui-meme ce qui a genere le mouvement (regle de couplage n1).
    source_document = models.CharField(max_length=255, blank=True)
    unit_cost_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    # `qty * unit_cost_mga`, synchronise par `services.moves` (meme
    # discipline que `StkQuant.value_mga` ci-dessus).
    value_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    operator = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Rempli par `services.moves.reverse_move` sur la nouvelle ecriture
    # inverse, meme patron que `AccMove.reverses` — `move` original n'est
    # jamais modifie.
    reverses = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="reversed_by"
    )
    # Motif obligatoire d'annulation — meme convention que
    # `PurOrder.cancel_reason`/`SalesOrder` (motif obligatoire, cf.
    # `services.moves.cancel_move`).
    cancel_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "stk_move"

    def __str__(self) -> str:
        return f"{self.reference or self.id} [{self.move_type}]"


class StkValuationLayer(BaseModel):
    """Couche de valorisation FIFO/CMP (RG-STK-2, §5.8) — une ligne par
    mouvement qui fait reellement entrer de la valeur en stock (reception,
    entree production...), decrementee au fil des sorties qui consomment
    cette couche (`remaining_qty`/`remaining_value_mga`). Pas de
    `ReferenceMixin` : entite derivee d'un `StkMove`, pas un document que
    l'utilisateur cree directement (meme categorie que `StkQuant`).

    `move` (`on_delete=PROTECT`) : une couche de valorisation ne doit
    jamais survivre a la suppression physique de son mouvement d'origine
    sans que cette suppression soit explicitement bloquee — meme discipline
    que `StkMove.location_from`/`location_to` (`PROTECT`), l'historique de
    valorisation ne doit jamais se retrouver orpheline silencieusement.

    Note de perimetre (ST2) : la methode de valorisation (`fifo`/`cmp`/
    `standard`) n'est PAS encore un parametre persistant par produit — le
    CDC ne prevoit aucune entite de configuration pour cela dans le
    perimetre ST2, et `apps.catalog.models.ProductVariant`/`TextileSpec`
    (Lot 1) n'expose aucun champ de methode de cout. `services.moves`
    accepte donc un parametre `valuation_method` (defaut `"fifo"`, seule
    methode reellement implementee en ST2) plutot que d'inventer ici un
    nouveau modele de configuration sans commanditaire clair dans le
    perimetre de ce lot — une vraie configuration par produit est un
    enrichissement naturel d'un ST ulterieur, pas fabrique ici sans
    fondement CDC."""

    move = models.ForeignKey(StkMove, on_delete=models.PROTECT, related_name="valuation_layers")
    variant_id = models.UUIDField()
    qty = models.DecimalField(max_digits=18, decimal_places=4)
    unit_cost_mga = models.DecimalField(max_digits=18, decimal_places=4)
    value_mga = models.DecimalField(max_digits=18, decimal_places=4)
    remaining_qty = models.DecimalField(max_digits=18, decimal_places=4)
    remaining_value_mga = models.DecimalField(max_digits=18, decimal_places=4)
    date = models.DateField()

    class Meta:
        db_table = "stk_valuation_layer"

    def __str__(self) -> str:
        return f"{self.variant_id} +{self.qty}@{self.unit_cost_mga} (reste {self.remaining_qty})"


# ST3 (cf. plan, §5.8) : `StkMeasurement` (RG-STK-4, mesures physiques) et
# `StkQualityState` (RG-STK-7, defauts/etats qualite). Toutes deux
# consomment le referentiel `StkDefectType` (ST1) et le coeur `StkMove`/
# `StkQuant` (ST2), et sont, comme `StkQuant`/`StkValuationLayer`, des
# enregistrements d'evenement/de classification derives — pas de
# `ReferenceMixin` sur l'une ou l'autre (le CDC ne liste pas de champ
# "reference" sequence dans le tableau §5.8 pour ces deux entites,
# contrairement a `StkMove`).


class StkMeasurement(BaseModel):
    """Mesure physique (RG-STK-4, §5.8, ST3) — poids/longueur/largeur/
    surface/epaisseur relevee sur un mouvement ou un quant, avec ecart
    calcule contre une valeur theorique quand elle est fournie.

    **`move`/`quant` (tous deux nullables, `on_delete=SET_NULL`)** : le CDC
    dit "move OU quant" (§5.8, entite `stk_measurement`). Contrairement a
    `StkQualityState.quant`/`lot` ci-dessous, PAS de contrainte XOR stricte
    en base ici — une mesure est d'abord un enregistrement d'evenement
    factuel ("on a mesure X a tel instant"), pas une decision de
    classification qui engagerait un etat de stock : rien n'empeche
    metier-parlant une mesure de reference sans mouvement ni quant precis
    (ex. controle d'un instrument, mesure d'echantillon hors contexte
    stock), et rien n'empeche non plus une mesure qui documente A LA FOIS
    le mouvement qui l'a genere ET le quant qu'elle affecte. Une vraie XOR
    ici serait une contrainte inventee au-dela de ce que le CDC exige.

    **"Quantite mesuree, jamais theorique" (RG-STK-4, acceptance test
    §5.8.7 n°3)** : ce n'est PAS ce modele qui applique cette regle — c'est
    une discipline d'appel de `services.moves.create_move` (cf. docstring
    `services/measurements.py`). `StkMeasurement` se contente d'enregistrer
    fidelement la valeur mesuree (`value`) et, le cas echeant, l'ecart
    (`variance_pct`) contre une theorique passee en parametre au moment du
    calcul (jamais stockee ici — seul l'ecart en pourcentage l'est).

    `photo_document_id` (UUID nu, singulier) : le CDC (§5.8, tableau
    `stk_measurement`) liste un champ `photo` au SINGULIER — a la
    difference de `stk_quality_state.photos[]` (pluriel) ci-dessous, une
    seule photo est prevue pour une mesure. Meme convention "UUID nu vers
    `core.Document`, jamais de FK Django" que `StkLot.certificate_document_id`."""

    TYPE_POIDS = "poids"
    TYPE_LONGUEUR = "longueur"
    TYPE_LARGEUR = "largeur"
    TYPE_SURFACE = "surface"
    TYPE_EPAISSEUR = "epaisseur"
    TYPE_CHOICES = [
        (TYPE_POIDS, "Poids"),
        (TYPE_LONGUEUR, "Longueur"),
        (TYPE_LARGEUR, "Largeur"),
        (TYPE_SURFACE, "Surface"),
        (TYPE_EPAISSEUR, "Epaisseur"),
    ]

    move = models.ForeignKey(
        StkMove, null=True, blank=True, on_delete=models.SET_NULL, related_name="measurements"
    )
    quant = models.ForeignKey(
        StkQuant, null=True, blank=True, on_delete=models.SET_NULL, related_name="measurements"
    )
    type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    value = models.DecimalField(max_digits=18, decimal_places=4)
    # Pas de FK `catalog.UnitOfMeasure` (regle de couplage n1), meme
    # discipline que `StkQuant.uom`/`StkMove.uom`.
    uom = models.CharField(max_length=16, blank=True)
    # Instrument de mesure utilise — texte libre, aucun referentiel
    # d'instruments dans le perimetre du CDC.
    device = models.CharField(max_length=120, blank=True)
    measured_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    measured_at = models.DateTimeField()
    # Ecart en % contre une valeur theorique, calcule par
    # `services.measurements.record_measurement` — `None` quand aucune
    # theorique n'a ete fournie a l'appel (pas toujours pertinent, ex.
    # mesure d'inventaire sans quantite attendue).
    variance_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    photo_document_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "stk_measurement"

    def __str__(self) -> str:
        return f"{self.type} = {self.value} {self.uom}"


class StkQualityState(BaseModel):
    """Etat de qualite/decision de classification (RG-STK-7, §5.8, ST3) sur
    un `quant` ou un `lot` precis.

    **`quant`/`lot` : XOR STRICT, applique par `services.quality.
    set_quality_state`** (`ValidationError` si les deux sont `None` ou les
    deux sont renseignes) — contrairement au traitement plus souple de
    `StkMeasurement.move`/`quant` ci-dessus. Difference assumee : une
    `StkQualityState` EST la decision de classification elle-meme
    (conforme/defaut/rebut...) et doit toujours porter sans ambiguite sur
    UNE unite de stock precise (soit un quant emplacement-par-emplacement,
    soit un lot dans son ensemble) — une mesure, elle, ne fait
    qu'enregistrer un fait, sans engager de decision, d'ou l'absence de
    garde equivalente sur `StkMeasurement`.

    **"Restant valorisee jusqu'a decision" (RG-STK-7)** : `defaut_majeur`/
    `rebut` deplacent la quantite defectueuse vers un emplacement dedie
    via un `StkMove` REEL (`services.quality.apply_quality_decision`,
    reutilisant `services.moves` de ST2) plutot que de la faire
    "disparaitre" — cf. docstring de ce service pour l'ajustement de
    perimetre de valorisation necessaire dans `services.moves.validate_move`
    (`TYPE_REBUT` traite comme "interne" au sens valorisation)."""

    STATE_CONFORME = "conforme"
    STATE_DEFAUT_MINEUR = "defaut_mineur"
    STATE_DEFAUT_MAJEUR = "defaut_majeur"
    STATE_REBUT = "rebut"
    STATE_EN_QUARANTAINE = "en_quarantaine"
    STATE_DECLASSE = "declasse"
    STATE_CHOICES = [
        (STATE_CONFORME, "Conforme"),
        (STATE_DEFAUT_MINEUR, "Defaut mineur"),
        (STATE_DEFAUT_MAJEUR, "Defaut majeur"),
        (STATE_REBUT, "Rebut"),
        (STATE_EN_QUARANTAINE, "En quarantaine"),
        (STATE_DECLASSE, "Declasse"),
    ]

    quant = models.ForeignKey(
        StkQuant, null=True, blank=True, on_delete=models.SET_NULL, related_name="quality_states"
    )
    lot = models.ForeignKey(
        StkLot, null=True, blank=True, on_delete=models.SET_NULL, related_name="quality_states"
    )
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_CONFORME)
    defect_type = models.ForeignKey(
        StkDefectType,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="quality_states",
    )
    defect_qty = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    description = models.TextField(blank=True)
    # Liste JSON d'UUID `core.Document`, JAMAIS une FK Django/M2M — meme
    # patron que `PurCri.attachment_document_ids`. Pluriel (`photos`) ici,
    # a la difference du `photo_document_id` singulier de `StkMeasurement`
    # ci-dessus : le CDC (§5.8, tableau `stk_quality_state`) liste
    # explicitement `photos[]`.
    photos = models.JSONField(default=list, blank=True)
    decided_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "stk_quality_state"

    def __str__(self) -> str:
        target = self.quant_id or self.lot_id
        return f"{self.state} @ {target}"
