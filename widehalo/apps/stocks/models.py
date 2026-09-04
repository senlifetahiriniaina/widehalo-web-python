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

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
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
    # STK-BC1 (§5.8, ST7) : code-barres/QR du lot — meme champ que
    # `StkLocation.barcode` (ST1), ajoute ici en ST7 plutot qu'en ST1 car le
    # CDC ne mentionne le code-barres AU NIVEAU LOT nulle part dans le
    # tableau d'entites §5.8 initial (contrairement a `stk_location`, qui le
    # liste des le depart) — c'est l'enrichissement STK-BC1 ("emplacements,
    # lots et produits") qui l'introduit pour cette entite. `stocks` est le
    # proprietaire de `StkLot` (regle de couplage n°1) : ajouter ce champ
    # ici est dans le perimetre normal de ce module, a la difference d'un
    # eventuel champ equivalent sur `apps.catalog.ProductVariant` (hors
    # perimetre de CE module, cf. `services/barcodes.py`).
    barcode = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "stk_lot"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "variant_id", "name"], name="uniq_stk_lot_variant_name"
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.variant_id})"

    def current_quality_state(self) -> str | None:
        """A3 (L4 Agro, cf. docs/planning/2026-refonte-ux-sprints.md §5) :
        dernier `StkQualityState` enregistré pour CE lot (`state=None` si
        aucun n'existe encore) — `StkQualityState` est un journal
        d'événements (une ligne par décision), jamais un champ mutable
        unique ; "l'état courant" du lot est donc toujours dérivé de la
        décision la plus récente, jamais stocké en double sur `StkLot`
        lui-même (une seule source de vérité).

        Référence `StkQualityState` par son nom de classe uniquement au
        moment de l'APPEL (jamais à la définition de cette méthode) — ce
        module l'importe donc sans souci d'ordre malgré sa définition plus
        bas dans ce même fichier."""
        latest = self.quality_states.order_by("-decided_at", "-id").first()
        return latest.state if latest else None

    def is_held(self) -> bool:
        """Vrai si la dernière décision qualité de ce lot est un état qui
        doit bloquer sa sortie du périmètre interne (`en_quarantaine`,
        posé explicitement par un contrôleur, ou `defaut_majeur`/`rebut`,
        qui impliquent déjà une relocalisation physique via
        `services.quality.apply_quality_decision`). Consommé par
        `services.moves.create_move` (RG-STK-11, A3) pour refuser un
        mouvement qui sortirait ce lot vers un emplacement autre que la
        quarantaine/le rebut eux-mêmes."""
        return self.current_quality_state() in (
            StkQualityState.STATE_EN_QUARANTAINE,
            StkQualityState.STATE_DEFAUT_MAJEUR,
            StkQualityState.STATE_REBUT,
        )


class StkLotGenealogy(BaseModel):
    """A2 (L4 Agro, cf. docs/planning/2026-refonte-ux-sprints.md §5) :
    généalogie de lot — un lot enfant (ex. lot de produit fini issu d'une
    transformation) est produit à partir d'un ou plusieurs lots parents
    (matières premières/composants consommés), pour permettre la
    traçabilité "amont/aval" exigée par l'écran A2/A3 (un lot suspect doit
    permettre de retrouver tous les lots finis impactés, et réciproquement).

    Pas de FK vers `apps.mrp` (règle de couplage n°1) : `source_document`
    (CharField libre) porte la référence de l'ordre à l'origine du lien,
    même convention que `StkMove.source_document` (cf. docstring de ce
    champ et `apps.stocks.services.consistency`, qui documente déjà cette
    corrélation par correspondance de chaîne pour `MrpOrder.reference`).

    `parent_lot`/`child_lot` sont `PROTECT` : un lot déjà impliqué dans une
    généalogie ne peut pas être supprimé sans casser la traçabilité — même
    discipline que les autres FK de document déjà validées par
    `MrpOrderComponent.bom_line` (cf. `test_structural_constraints.py`)."""

    parent_lot = models.ForeignKey(StkLot, on_delete=models.PROTECT, related_name="child_links")
    child_lot = models.ForeignKey(StkLot, on_delete=models.PROTECT, related_name="parent_links")
    qty = models.DecimalField(max_digits=18, decimal_places=4)
    source_document = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "stk_lot_genealogy"
        constraints = [
            models.UniqueConstraint(
                fields=["parent_lot", "child_lot", "source_document"],
                name="uniq_stk_lot_genealogy_link",
            )
        ]

    def __str__(self) -> str:
        return f"{self.parent_lot} -> {self.child_lot}"


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
    RG-ACC-1).

    **STK-11 (Phase 3 §13.1, sprint A5) : immuabilite technique, pas
    seulement conventionnelle.** `services.moves.validate_move`/
    `cancel_move`/`reverse_move` refusent deja toute mutation d'un mouvement
    `done` (docstrings ci-dessous) — mais rien n'empechait, AVANT A5, un
    acces ORM/admin/shell direct de contourner ces gardes de service (aucun
    `save()`/`clean()` ne les fait respecter au niveau modele). Migration
    `stocks.0015` : trigger Postgres `stk_move_immutable_when_done`
    (fonction `stk_move_reject_mutation_if_done`, meme patron « field-aware »
    que `AccMove`/RG-ACC-2, migrations `accounting.0003`+`0005` — compare
    OLD/NEW colonne par colonne, ne bloque QUE les colonnes qui definissent
    le mouvement lui-meme, pas les champs de suivi communs `BaseModel`
    (`is_active`/`archived_at`/`created_by`/`updated_by`/`updated_at`),
    exactement comme `AccMove` ne les protege pas non plus). DELETE
    egalement bloque une fois `done` — correction uniquement par
    `reverse_move` (nouveau mouvement, jamais de modification du mouvement
    original).

    **STK-9 (Phase 3 §7.3, sprint A6) : mode degrade terrain.**
    `client_uuid` (cf. champ ci-dessous) est la clef d'idempotence qui
    permet a `services.scan.sync_scan_reception_line` de rejouer sans
    risque une ligne scannee hors ligne, exactement comme
    `apps.pos.services.orders.sync_order` le fait deja pour `PosOrder` —
    protocole reutilise, pas reinvente (cahier, « H19 »). Chaque tentative
    de synchronisation (acceptee/doublon/rejetee) est journalisee via
    `apps.core.services.audit.log_action` (`AuditLog`, deja existant,
    immuable en base) plutot que par un nouveau modele dedie a la
    `PosSyncLog` : `stocks` etait deja a 290/290 modeles au moment de ce
    sprint (`tests/architecture/test_budget.py::
    test_model_budget_not_exceeded`), et ce plafond ne se releve pas sans
    decision explicite du commanditaire — reutiliser le journal d'audit
    transversal existant est le choix qui respecte ce garde-fou plutot que
    de le contourner."""

    STATE_DRAFT = "draft"
    STATE_DONE = "done"
    STATE_CANCELLED = "cancelled"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_DONE, "Valide"),
        (STATE_CANCELLED, "Annule"),
    ]

    # Phase 3 §5.8 (decision A1, plan Vague 2 Bloc A) : le cahier enumere
    # EXPLICITEMENT « douze natures, une table » — reception d'achat, retour
    # fournisseur, transfert, prelevement, expedition, vente au comptoir,
    # consommation d'atelier, entree de production, sous-produit, rebut,
    # casse, regularisation d'inventaire. Correspondance verifiee ligne a
    # ligne contre les choix ci-dessous :
    #   reception d'achat      -> TYPE_RECEPTION
    #   retour fournisseur     -> TYPE_RETOUR
    #   transfert               -> TYPE_TRANSFERT_INTERNE (+ services.moves.
    #                              transfer_between_warehouses pour le cas
    #                              inter-depots via emplacement TYPE_TRANSIT)
    #   prelevement             -> PAS un `move_type` distinct : le cahier
    #                              associe systematiquement ce terme a la
    #                              REGLE de selection FEFO/FIFO (§12.3,
    #                              "regle de prelevement") et au document
    #                              `StkPicking` qui groupe les `StkMove`
    #                              d'une preparation (cf. docstring
    #                              `StkPicking` ci-dessous) — le mouvement
    #                              physique reellement enregistre a l'issue
    #                              du prelevement EST l'expedition
    #                              (TYPE_LIVRAISON), jamais une ligne
    #                              separee. Decision documentee ici plutot
    #                              que redecouverte a chaque lecture.
    #   expedition              -> TYPE_LIVRAISON
    #   vente au comptoir       -> TYPE_VENTE_COMPTOIR (nouveau) : la sortie
    #                              de caisse POS, jusqu'ici un mouvement
    #                              seulement "indicatif" (cf. cahier §2,
    #                              "bascule du mouvement indicatif du POS en
    #                              mouvement reel"), reste hors perimetre de
    #                              CE lot (le cablage reel d'`apps.pos` sur
    #                              cette nouvelle valeur est un chantier
    #                              distinct) — seule la NATURE est ajoutee
    #                              ici pour que `MOVE_TYPE_CHOICES` porte
    #                              deja les douze natures completes.
    #   consommation d'atelier  -> TYPE_PRODUCTION_OUT
    #   entree de production    -> TYPE_PRODUCTION_IN
    #   sous-produit            -> TYPE_SOUS_PRODUIT (nouveau) : distinct de
    #                              TYPE_PRODUCTION_IN pour permettre un
    #                              traitement de valorisation different
    #                              (cout de revient) sur un coproduit d'une
    #                              nomenclature de process (Bloc C, C5).
    #   rebut                   -> TYPE_REBUT
    #   casse                   -> TYPE_CASSE (nouveau) : distinct de
    #                              TYPE_REBUT — la casse (perte accidentelle
    #                              a la manutention) et le rebut (decision
    #                              qualite) sont deux dimensions de reporting
    #                              separees au cahier (§9, "casse et
    #                              demarque" cite independamment des sorties
    #                              par nature).
    #   regularisation d'inventaire -> TYPE_AJUSTEMENT
    # `TYPE_SOUS_TRAITANCE` reste un 13e choix, AU-DELA des douze natures du
    # cahier — necessaire au flux reel de sous-traitance de facon (Bloc C,
    # C2 : emplacement TYPE_SOUS_TRAITANT deja modelise), le cahier ne
    # l'evoque simplement pas dans son enumeration des natures de stock pur.
    TYPE_RECEPTION = "reception"
    TYPE_LIVRAISON = "livraison"
    TYPE_TRANSFERT_INTERNE = "transfert_interne"
    TYPE_PRODUCTION_IN = "production_in"
    TYPE_PRODUCTION_OUT = "production_out"
    TYPE_RETOUR = "retour"
    TYPE_REBUT = "rebut"
    TYPE_AJUSTEMENT = "ajustement"
    TYPE_SOUS_TRAITANCE = "sous_traitance"
    TYPE_VENTE_COMPTOIR = "vente_comptoir"
    TYPE_SOUS_PRODUIT = "sous_produit"
    TYPE_CASSE = "casse"
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
        (TYPE_VENTE_COMPTOIR, "Vente au comptoir"),
        (TYPE_SOUS_PRODUIT, "Sous-produit"),
        (TYPE_CASSE, "Casse"),
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
    # ST4 (`StkPicking`, plus bas dans ce fichier) : FK INVERSE nullable
    # vers l'operation de stock groupee qui a genere ce mouvement, quand il
    # y en a une — un mouvement cree hors de tout picking (ex. un
    # ajustement direct via `services.quality`) laisse ce champ `None`.
    # `on_delete=SET_NULL` (pas `PROTECT`/`CASCADE`) : la suppression d'un
    # `StkPicking` ne doit jamais entrainer la suppression ni le blocage
    # d'un `StkMove` deja `done` — l'historique de mouvement doit survivre
    # independamment de son document groupeur, meme discipline que
    # `StkMove.lot`/`StkMove.reverses` ci-dessus (deja `SET_NULL`). Cf.
    # docstring `StkPicking` pour l'explication complete du choix "pas de
    # `stk_picking_line` dedie, le picking groupe directement des `StkMove`
    # existants".
    picking = models.ForeignKey(
        "StkPicking", null=True, blank=True, on_delete=models.SET_NULL, related_name="moves"
    )
    # STK-9 (Phase 3 §7.3, sprint A6, mode degrade) : clef d'idempotence de
    # la synchronisation hors ligne — generee COTE CLIENT (JS) au moment du
    # scan, jamais recalculee serveur, meme discipline que
    # `PosOrder.client_uuid`/`services.orders.sync_order` (POS). NULL pour
    # la quasi-totalite des mouvements existants (tout mouvement qui ne
    # transite pas par `services.scan.sync_scan_reception_line`) — seul un
    # mouvement REELLEMENT issu du scan en porte un, d'ou la contrainte
    # d'unicite PARTIELLE ci-dessous (pas de contrainte a la `PosOrder`,
    # qui l'exige sur 100% des lignes).
    client_uuid = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "stk_move"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "client_uuid"],
                condition=models.Q(client_uuid__isnull=False),
                name="uniq_stk_move_client_uuid_per_tenant",
            )
        ]

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

    Note de perimetre (ST2, revisee Phase 3 §11.1/§12.4, decision P3) : la
    methode de valorisation n'est PAS un parametre persistant par produit —
    le cahier Phase 3 tranche explicitement cette question au niveau
    produit entier plutot que par article : *« Le CUMP est la seule
    methode livree »*. `services.moves` accepte donc un parametre
    `valuation_method` (defaut desormais `"cmp"`, methode reellement
    ponderee — cf. `_consume_average_cost` ; `"fifo"` reste selectionnable
    explicitement, implementation preservee pour l'option paremetrable que
    le cahier reserve §11.1, mais n'est plus le comportement par defaut
    d'aucun appelant de ce depot) plutot que d'inventer ici un nouveau
    modele de configuration par produit sans commanditaire clair."""

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


# ST4 (cf. plan, §5.8) : `StkPicking` — operation de stock GROUPEE
# (reception/expedition/transfert interne), regroupant plusieurs `StkMove`
# individuels sous un meme document. Ecrans (reception/preparation)
# DIFFERES a ST8 (§5.8, note de replanification de cette session : chaque
# module de ce depot — `sales`/`purchase`/`mrp`/`patronage` — construit
# TOUS ses ecrans HTMX ensemble dans son dernier ST, jamais disperses en
# cours de module) — ST4 est donc backend seul (modele + services).


class StkPicking(BaseModel, ReferenceMixin):
    """Operation de stock groupee (§5.8, entite `stk_picking`) — reception
    fournisseur, expedition client ou transfert interne, regroupant
    plusieurs `StkMove` individuels (ci-dessous, champ `StkMove.picking`)
    sous un meme document sequence. `ReferenceMixin` : le CDC liste un
    champ "reference" pour cette entite (meme categorie document que
    `StkMove`), a la difference de `StkLot`/`StkQuant`/`StkMeasurement`/
    `StkQualityState`.

    **Design "picking groupe de moves" (pas de `stk_picking_line` dedie)**
    : le CDC (§5.8) ne montre aucune entite `stk_picking_line` distincte —
    contrairement a `PurOrder`/`PurOrderLine` ou `SalesQuotation`/
    `SalesQuotationLine`, ou une ligne de document est une entite propre
    sans effet de stock par elle-meme. Ici, chaque "ligne" d'un picking EST
    directement un `StkMove` (qui porte deja `variant_id`/`qty`/`uom`/
    `lot`/`unit_cost_mga` — tout ce qu'une ligne de picking aurait besoin
    de porter), donc `StkPicking` groupe les `StkMove` existants via une FK
    INVERSE (`StkMove.picking`, ci-dessous) plutot que d'introduire une
    nouvelle entite de ligne qui ferait doublon avec `StkMove` et devrait
    etre synchronisee avec lui. Le patron reste le meme esprit que
    `PurOrderLine.order` (une ligne associee a son document parent), juste
    porte par le mouvement lui-meme plutot que par une ligne intermediaire
    — cf. docstring du champ `StkMove.picking` ci-dessous pour le miroir de
    cette explication cote `StkMove`.

    **`type`** : `entree` (reception, typiquement depuis un emplacement
    `fournisseur`)/`sortie` (expedition, typiquement vers un emplacement
    `client`)/`interne` (transfert entre deux emplacements internes/sites).
    Determine le mapping par defaut vers `StkMove.move_type` applique par
    `services.pickings.add_picking_line` quand l'appelant ne precise pas
    explicitement `move_type` (cf. docstring de ce service pour la table
    complete) — mais `location_from`/`location_to` restent les champs qui
    font foi pour le mouvement reel (RG-STK-1), `type` n'etant qu'une
    classification de haut niveau du document.

    **`partner_id`** (UUID nu, jamais FK) : le fournisseur d'une reception
    ou le client d'une expedition — meme regle de couplage n1 que partout
    ailleurs dans `stocks` (jamais de FK Django vers `apps.partners`),
    nullable car un transfert interne (`type == "interne"`) n'a
    generalement aucun tiers associe.

    **`state` : CharField simple + gardes de service, PAS de FSM.**
    Contrairement a `PurOrder` (workflow BRANCHANT avec plusieurs chemins
    d'approbation, `django-fsm` justifie), le cycle de vie d'un picking est
    LINEAIRE — `draft -> waiting -> ready -> done`, avec `cancelled`
    atteignable depuis les trois premiers etats — exactement la meme forme
    que `PurRequisition` (verifie explicitement : celle-ci utilise aussi un
    `CharField` + gardes `services.py`, pas de FSM). Meme raisonnement
    retenu ici : une FSM n'apporte de valeur que pour un branchement
    metier reel a proteger, pas pour une simple sequence lineaire ou de
    simples gardes `if state != X: raise ValidationError` suffisent
    (precedent egalement `StkMove.state` lui-meme, deja un CharField
    simple pour `draft -> done -> (cancelled)`).

    **`waiting`** : etat intermediaire optionnel entre `draft` et `ready`
    (ex. "en attente de la marchandise cote transporteur") — le CDC ne le
    definit pas precisement, ajoute ici par symetrie avec un workflow
    reception/expedition classique ou "en attente" est un statut naturel
    distinct du brouillon ; les services traitent `draft` et `waiting` de
    facon identique partout ou la distinction n'a pas d'effet (ajout de
    lignes, passage a `ready`) — aucune transition service ne force
    explicitement `draft -> waiting`, l'appelant peut y placer un picking
    directement s'il le souhaite (aucune ecriture n'est proposee pour ce
    faire en ST4, hors perimetre backend-only de ce ST)."""

    TYPE_ENTREE = "entree"
    TYPE_SORTIE = "sortie"
    TYPE_INTERNE = "interne"
    TYPE_CHOICES = [
        (TYPE_ENTREE, "Entree"),
        (TYPE_SORTIE, "Sortie"),
        (TYPE_INTERNE, "Interne"),
    ]

    STATE_DRAFT = "draft"
    STATE_WAITING = "waiting"
    STATE_READY = "ready"
    STATE_DONE = "done"
    STATE_CANCELLED = "cancelled"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_WAITING, "En attente"),
        (STATE_READY, "Pret"),
        (STATE_DONE, "Termine"),
        (STATE_CANCELLED, "Annule"),
    ]

    type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    # Jamais de FK Django vers `apps.partners` (regle de couplage n1) — le
    # fournisseur (reception) ou le client (expedition) d'un picking,
    # nullable pour un transfert interne.
    partner_id = models.UUIDField(null=True, blank=True)
    location_from = models.ForeignKey(
        StkLocation, on_delete=models.PROTECT, related_name="pickings_out"
    )
    location_to = models.ForeignKey(
        StkLocation, on_delete=models.PROTECT, related_name="pickings_in"
    )
    date_scheduled = models.DateField(null=True, blank=True)
    date_done = models.DateField(null=True, blank=True)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_DRAFT)
    # Reference libre vers le document d'origine (commande d'achat/de
    # vente...), resolue par l'APPELANT — meme convention exacte que
    # `StkMove.source_document` (regle de couplage n1, `stocks` ne va
    # jamais chercher lui-meme ce qui a genere le picking).
    source_document = models.CharField(max_length=255, blank=True)
    carrier = models.CharField(max_length=150, blank=True)
    tracking = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = "stk_picking"

    def __str__(self) -> str:
        return self.reference or str(self.id)


# ST5 (cf. plan, §5.8) : RG-STK-8 (reservation), RG-STK-9 (inventaire +
# ecriture comptable auto), STK-CYCLE1/STK-ABC1 (classification ABC et
# comptage cyclique).


class StkReservation(BaseModel):
    """Reservation de stock (RG-STK-8, §5.8, ST5) sur un `StkQuant` precis
    — "la quantite disponible a la vente est `qty - qty_reserved`" (CDC),
    jamais de sur-reservation (garde `services.reservations.reserve_stock`).
    Pas de `ReferenceMixin` : le CDC ne liste pas de champ "reference"
    sequence pour cette entite (§5.8) — un enregistrement operationnel lie
    a un quant, pas un document que l'utilisateur numerote, meme categorie
    que `StkQualityState`/`StkMeasurement` en ST3.

    **Origine generique (`content_type`/`object_id`/`content_object`)** :
    une reservation nait d'une `sales_order_line` OU d'un
    `mrp_order_component` (RG-STK-8) — `stocks` ne peut jamais faire de FK
    Django directe vers `apps.sales.models.SalesOrderLine`/
    `apps.mrp.models.MrpOrderComponent` (regle de couplage n°1). Meme
    patron EXACT que `apps.core.models.document.Document.content_type`/
    `object_id`/`content_object` (`ContentType`, `on_delete=SET_NULL`,
    `CharField(max_length=64)` pour `object_id` plutot qu'un
    `UUIDField` — coherent avec le fait qu'un `pk` de modele Django n'est
    pas garanti etre un UUID en toute generalite, meme si c'est le cas
    partout dans ce depot) et deja repris par
    `apps.purchase.services.substitution._ensure_rule`/
    `request_substitute_approval` (`ContentType.objects.get_for_model(...)`,
    `object_id=str(instance.pk)`) pour un besoin similaire de reference
    generique inter-app. Nullable : une reservation manuelle (sans origine
    tracee, ex. saisie directe par un magasinier) laisse les deux champs
    vides — `stocks` ne construit ni ne resout jamais lui-meme cette
    generic FK au-dela de son stockage, cf. `services.reservations`.

    `quant` (`on_delete=CASCADE`) : contrairement a `StkMeasurement.quant`/
    `StkQualityState.quant` (`SET_NULL`, un enregistrement d'evenement/de
    decision qui doit survivre a la suppression de son quant), une
    reservation N'A AUCUN SENS sans le quant qu'elle bloque — la
    suppression (rarissime, soft-delete normalement) du quant doit
    entrainer celle de ses reservations, pas les laisser orphelines avec
    un `qty_reserved` qui ne correspondrait plus a rien."""

    STATE_ACTIVE = "active"
    STATE_RELEASED = "released"
    STATE_EXPIRED = "expired"
    STATE_CHOICES = [
        (STATE_ACTIVE, "Active"),
        (STATE_RELEASED, "Liberee"),
        (STATE_EXPIRED, "Expiree"),
    ]

    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=64, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")

    quant = models.ForeignKey(StkQuant, on_delete=models.CASCADE, related_name="reservations")
    qty = models.DecimalField(max_digits=18, decimal_places=4)
    date = models.DateField()
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_ACTIVE)

    class Meta:
        db_table = "stk_reservation"

    def __str__(self) -> str:
        return f"{self.quant_id} x{self.qty} [{self.state}]"


class StkInventory(BaseModel, ReferenceMixin):
    """Inventaire physique (RG-STK-9, §5.8, ST5) — document sequence
    (`ReferenceMixin`, le CDC liste un champ "reference" pour cette
    entite), regroupant des `StkInventoryLine` de comptage.

    `warehouse` (`on_delete=PROTECT`) : meme discipline que
    `StkPicking.location_from`/`location_to` — un document deja cree ne
    doit jamais se retrouver silencieusement orpheline de son entrepot.

    **`state` : CharField simple + gardes de service, PAS de FSM** — cycle
    de vie LINEAIRE `draft -> in_progress -> validated`, avec `cancelled`
    atteignable depuis `draft`/`in_progress` uniquement (immuable une fois
    `validated`, meme discipline "correction par document/mouvement
    inverse, jamais de retour arriere" que `StkMove`/`StkPicking`). Meme
    raisonnement exact que `StkPicking.state` (cf. sa docstring) : une FSM
    n'apporte de valeur que pour un branchement metier reel a proteger, pas
    pour une simple sequence lineaire.

    Pas de champ `cancel_reason` persiste : meme precedent que
    `StkPicking` (qui n'en a pas non plus) — le motif obligatoire
    d'annulation est une garde de `services.inventory.cancel_inventory`,
    jamais stockee sur le document lui-meme (le CDC §5.8 ne liste pas ce
    champ pour `stk_inventory`)."""

    TYPE_COMPLET = "complet"
    TYPE_TOURNANT = "tournant"
    TYPE_PONCTUEL = "ponctuel"
    TYPE_CHOICES = [
        (TYPE_COMPLET, "Complet"),
        (TYPE_TOURNANT, "Tournant"),
        (TYPE_PONCTUEL, "Ponctuel"),
    ]

    STATE_DRAFT = "draft"
    STATE_IN_PROGRESS = "in_progress"
    STATE_VALIDATED = "validated"
    STATE_CANCELLED = "cancelled"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_IN_PROGRESS, "En cours"),
        (STATE_VALIDATED, "Valide"),
        (STATE_CANCELLED, "Annule"),
    ]

    warehouse = models.ForeignKey(
        StkWarehouse, on_delete=models.PROTECT, related_name="inventories"
    )
    date = models.DateField()
    type = models.CharField(max_length=16, choices=TYPE_CHOICES, default=TYPE_PONCTUEL)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_DRAFT)
    validated_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "stk_inventory"

    def __str__(self) -> str:
        return self.reference or str(self.id)


class StkInventoryLine(BaseModel):
    """Ligne de comptage d'un `StkInventory` (§5.8, ST5) — un couple
    (produit, emplacement, lot) precis. Pas de `ReferenceMixin` : ligne
    d'un document, pas un document elle-meme, meme categorie que
    `StkMove` n'ayant PAS de ligne dediee pour `StkPicking` — sauf qu'ici,
    a la difference du patron "picking groupe directement des `StkMove`"
    (cf. docstring `StkPicking`), une ligne d'inventaire n'EST PAS un
    `StkMove` : elle precede et peut ne jamais en generer un (comptage
    conforme, `difference == 0`) — d'ou une entite `StkInventoryLine`
    dediee, distincte du moteur ST2.

    `qty_theoretical` : photo instantanee de `StkQuant.qty` au moment ou
    la ligne est AJOUTEE (`services.inventory.add_inventory_line`), jamais
    recalculee dynamiquement par la suite — un inventaire porte sur l'ecart
    constate a un instant T, pas sur un ecart glissant qui bougerait sous
    les pieds du compteur si d'autres mouvements de stock surviennent
    pendant la periode de comptage.

    `qty_counted` (nullable) : `None` tant que le comptage physique n'a pas
    ete saisi (`services.inventory.record_count`) — `validate_inventory`
    refuse tant qu'une ligne du document reste a `None`.

    `difference` : `qty_counted - qty_theoretical`, calculee et persistee
    par `record_count` (jamais dans un `save()` de modele, discipline
    etablie de cette session — cf. `StkQuant.value_mga`) ; reste `0` tant
    que `qty_counted` est `None` (valeur par defaut du champ, sans
    signification avant comptage)."""

    inventory = models.ForeignKey(StkInventory, on_delete=models.CASCADE, related_name="lines")
    variant_id = models.UUIDField()
    lot = models.ForeignKey(
        StkLot, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    location = models.ForeignKey(StkLocation, on_delete=models.PROTECT, related_name="+")
    qty_theoretical = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    qty_counted = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    difference = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    reason = models.CharField(max_length=255, blank=True)
    counted_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "stk_inventory_line"

    def __str__(self) -> str:
        return f"{self.variant_id} @ {self.location_id} : theo={self.qty_theoretical}"


class StkAbcClassification(BaseModel):
    """Classification ABC par valeur de consommation (STK-ABC1, §5.8, ST5)
    — une ligne PAR (tenant, produit), recalculee periodiquement par
    `services.abc_classification.compute_abc_classification`
    (`update_or_create`). Pas de `ReferenceMixin` : classification derivee,
    pas un document sequence, meme categorie que `StkQuant`/
    `StkValuationLayer`.

    **Pourquoi une nouvelle entite plutot qu'un champ sur une entite
    `catalog` existante** : le CDC (§5.8) ne liste aucune entite dediee
    pour cette classification, et `stocks` ne peut de toute facon jamais
    ajouter de champ a `apps.catalog.models.ProductVariant` (app distincte,
    hors de son perimetre de migration) ni y faire de FK Django (regle de
    couplage n°1) — la seule option coherente avec ce couplage est donc une
    table cote `stocks`, keyee sur `variant_id` (UUID nu), au meme titre
    que `StkLot.variant_id`/`StkQuant.variant_id`/`StkMove.variant_id`.

    `UniqueConstraint(tenant, variant_id)` : au plus une classification
    active par produit et par tenant — `compute_abc_classification` la
    RECALCULE en place (`update_or_create`) a chaque execution plutot que
    d'accumuler un historique, meme raisonnement que `StkQuant` (photo
    instantanee, pas un historique de valeurs successives).

    `next_count_due` : echeance du prochain comptage cyclique (STK-CYCLE1),
    calculee par `compute_abc_classification` a partir de `computed_at` +
    un decalage fixe selon `abc_class` (A mensuel/+30j, B trimestriel/+90j,
    C annuel/+365j — cf. docstring de `services/abc_classification.py` pour
    la justification complete de ce cadencement). `due_cyclic_counts` du
    meme service lit ce champ pour surfacer les comptages a effectuer,
    sans jamais creer lui-meme de `StkInventory` (decision humaine/ops,
    meme discipline "pas d'enregistrement cron automatique" que
    `run_purchase_reordering`/`run_sales_recurrences`)."""

    CLASS_A = "a"
    CLASS_B = "b"
    CLASS_C = "c"
    CLASS_CHOICES = [
        (CLASS_A, "A"),
        (CLASS_B, "B"),
        (CLASS_C, "C"),
    ]

    variant_id = models.UUIDField()
    abc_class = models.CharField(max_length=1, choices=CLASS_CHOICES)
    consumption_value_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    computed_at = models.DateTimeField()
    next_count_due = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "stk_abc_classification"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "variant_id"], name="uniq_stk_abc_classification_variant"
            )
        ]

    def __str__(self) -> str:
        return f"{self.variant_id} : {self.abc_class.upper()} ({self.consumption_value_mga})"


# ST6 (cf. plan, §5.8) : RG-STK-6 (cohérence production/stock, backend seul
# — pas de nouvelle entite, cf. `services/consistency.py`), STK-OBS1
# (obsolescence, pas de nouvelle entite non plus, cf.
# `services/obsolescence.py`), STK-FEFO1 (FEFO, pas de nouvelle entite, cf.
# `services/quants.select_lot_fefo`), STK-RMA1 (`StkReturn` ci-dessous,
# SEULE nouvelle entite de ce ST), STK-REDIS1 (redistribution
# inter-sites, pas de nouvelle entite, cf. `services/redistribution.py`).


class StkReturn(BaseModel, ReferenceMixin):
    """Retour client (STK-RMA1, §5.8, ST6) — le CDC qualifie explicitement
    cette entite d'"absente de la V1 initiale, lacune" et lui donne sa
    propre entite `stk_return` (pas un simple `StkMove` de type `retour`
    sans document porteur) : `ReferenceMixin`, meme categorie document
    sequence que `StkMove`/`StkPicking`/`StkInventory` — un retour client
    est un vrai document que l'on numerote et suit, pas un enregistrement
    derive comme `StkQuant`/`StkQualityState`.

    `partner_id` (UUID nu, jamais FK) : le client a l'origine du retour —
    meme regle de couplage n°1 que partout ailleurs dans `stocks` (jamais
    de FK Django vers `apps.partners`).

    `source_document` (CharField libre, blank) : reference de la vente
    d'origine — meme convention EXACTE que `StkMove.source_document`/
    `StkPicking.source_document` (texte libre resolu par l'appelant,
    jamais une FK ni une resolution automatique par `stocks` lui-meme).

    `quality_state` : vocabulaire DISTINCT de `StkQualityState.STATE_CHOICES`
    (ST3), pas une reutilisation directe — plus restreint
    (`conforme`/`defaut_mineur`/`defaut_majeur`/`rebut`) : `StkQualityState`
    couvre aussi `en_quarantaine`/`declasse`, deux etats qui n'ont aucun
    sens comme evaluation INITIALE d'un article retourne (une quarantaine
    est une etape d'attente ulterieure, pas une classification immediate ;
    "declasse" est une decision de valorisation qui suppose deja un
    passage par une classification plus simple en amont). Un champ
    `CharField` propre a cette entite, plutot qu'une FK/reutilisation d'un
    modele congu pour un besoin different, garde chaque vocabulaire aligne
    sur son propre cas d'usage.

    `decision` : vocabulaire litteral du CDC (STK-RMA1) —
    avoir/remplacement/reparation/refus.

    `move` (FK nullable, `on_delete=SET_NULL`) : le `StkMove` reel genere
    par `services.returns.process_return`, `None` tant que le retour reste
    `draft`. `SET_NULL` (pas `PROTECT`) : meme discipline que
    `StkMove.picking` ci-dessus — un retour deja `processed` doit survivre
    a la suppression eventuelle de son mouvement (rarissime, soft-delete
    normalement), l'historique du retour ne doit jamais dependre de la
    persistance physique du mouvement associe.

    `state` : `CharField` simple + gardes de service, PAS de FSM — cycle de
    vie LINEAIRE `draft -> processed`, avec `cancelled` atteignable
    seulement depuis `draft` (un retour `processed` a un effet de stock
    REEL et immuable, meme discipline "correction par mouvement inverse,
    jamais de retour arriere" que `StkMove`/`StkPicking`/`StkInventory`).
    Meme raisonnement exact que `StkPicking.state`/`StkInventory.state` :
    une FSM n'apporte de valeur que pour un branchement metier reel a
    proteger, pas pour une simple sequence lineaire."""

    QUALITY_CONFORME = "conforme"
    QUALITY_DEFAUT_MINEUR = "defaut_mineur"
    QUALITY_DEFAUT_MAJEUR = "defaut_majeur"
    QUALITY_REBUT = "rebut"
    QUALITY_CHOICES = [
        (QUALITY_CONFORME, "Conforme"),
        (QUALITY_DEFAUT_MINEUR, "Defaut mineur"),
        (QUALITY_DEFAUT_MAJEUR, "Defaut majeur"),
        (QUALITY_REBUT, "Rebut"),
    ]

    DECISION_AVOIR = "avoir"
    DECISION_REMPLACEMENT = "remplacement"
    DECISION_REPARATION = "reparation"
    DECISION_REFUS = "refus"
    DECISION_CHOICES = [
        (DECISION_AVOIR, "Avoir"),
        (DECISION_REMPLACEMENT, "Remplacement"),
        (DECISION_REPARATION, "Reparation"),
        (DECISION_REFUS, "Refus"),
    ]

    STATE_DRAFT = "draft"
    STATE_PROCESSED = "processed"
    STATE_CANCELLED = "cancelled"
    STATE_CHOICES = [
        (STATE_DRAFT, "Brouillon"),
        (STATE_PROCESSED, "Traite"),
        (STATE_CANCELLED, "Annule"),
    ]

    partner_id = models.UUIDField()
    source_document = models.CharField(max_length=255, blank=True)
    date = models.DateField()
    reason = models.TextField(blank=True)
    quality_state = models.CharField(max_length=16, choices=QUALITY_CHOICES, blank=True)
    decision = models.CharField(max_length=16, choices=DECISION_CHOICES, blank=True)
    variant_id = models.UUIDField()
    qty = models.DecimalField(max_digits=18, decimal_places=4)
    move = models.ForeignKey(
        StkMove, null=True, blank=True, on_delete=models.SET_NULL, related_name="returns"
    )
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_DRAFT)

    class Meta:
        db_table = "stk_return"

    def __str__(self) -> str:
        return self.reference or str(self.id)


class StkRecall(BaseModel, ReferenceMixin):
    """A3 (L4 Agro, cf. docs/planning/2026-refonte-ux-sprints.md §5) :
    rappel produit — journal horodaté d'un incident déclenché sur un lot
    suspect, avec le PÉRIMÈTRE calculé et figé au moment de la déclaration
    (`ReferenceMixin` : un rappel est un vrai document numéroté, même
    catégorie que `StkReturn`/`StkInventory`, jamais un enregistrement
    dérivé comme `StkQualityState`).

    **Périmètre figé, jamais recalculé a posteriori** : `impacted_lot_ids`/
    `impacted_lot_names`/`client_exposures` sont des `JSONField` qui
    SNAPSHOTTENT le résultat de `services.genealogy.genealogy_tree`/
    `services.traceability.lot_traceability` au moment de
    `services.recall.declare_recall` — un choix délibéré : la généalogie
    réelle peut continuer d'évoluer après coup (de nouveaux lots enfants
    créés plus tard à partir d'un lot déjà rappelé, par exemple), mais le
    journal d'incident doit rester une preuve immuable de "ce qui était
    su et déclaré à cet instant", jamais un rapport qui se réécrit tout
    seul. Consulter la généalogie ACTUELLE d'un lot reste possible à tout
    moment via `lot_genealogy_tree`/`genealogy_tree`, indépendamment de
    ce snapshot.

    `client_exposures` : liste de dicts primitifs `{"lot_name",
    "source_document", "qty"}` — `source_document` reprend la même
    convention par correspondance de chaîne que `StkMove.source_document`
    (référence de la commande/livraison client d'origine, jamais une FK
    vers `apps.sales`, règle de couplage n°1)."""

    STATE_OPEN = "open"
    STATE_CLOSED = "closed"
    STATE_CHOICES = [
        (STATE_OPEN, "Ouvert"),
        (STATE_CLOSED, "Clos"),
    ]

    lot = models.ForeignKey(StkLot, on_delete=models.PROTECT, related_name="recalls")
    reason = models.TextField()
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_OPEN)
    initiated_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    impacted_lot_ids = models.JSONField(default=list, blank=True)
    impacted_lot_names = models.JSONField(default=list, blank=True)
    client_exposures = models.JSONField(default=list, blank=True)
    closed_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "stk_recall"

    def __str__(self) -> str:
        return self.reference or str(self.id)


# ST7 (cf. plan, §5.8) : RG-STK-10 (stock negatif interdit par defaut,
# autorisable par exception par produit) — SEULE nouvelle entite de ce ST
# (STK-BC1, codes-barres/QR, ne cree aucune entite : `StkLocation.barcode`
# existe deja depuis ST1, `StkLot.barcode` est ajoute plus haut dans ce
# meme fichier, cf. `services/barcodes.py`).


class StkNegativeStockException(BaseModel):
    """Exception au stock negatif (RG-STK-10, §5.8, ST7) — "Interdit par
    defaut. Autorisable par exception, par produit, avec journalisation et
    alerte." (CDC). Pas de `ReferenceMixin` : une configuration/exception
    par produit, pas un document sequence — meme categorie master-data que
    `PurSubstitute` (cf. `apps.purchase.models.PurSubstitute`, verifie
    explicitement comme precedent le plus proche : donnee de parametrage
    par produit, `BaseModel` sans `ReferenceMixin`, `is_active` porte le
    double sens standard/metier).

    `variant_id` (UUID nu, jamais FK vers `apps.catalog` — regle de
    couplage n°1, identique a `StkLot.variant_id`/`StkMove.variant_id`).

    `UniqueConstraint(tenant, variant_id)` : au plus UNE exception par
    produit et par tenant, meme discipline exacte que
    `StkAbcClassification` (ci-dessus, ST5) — pas de contrainte partielle
    `condition=models.Q(is_active=True)` (aucun precedent d'index partiel
    dans ce depot a ce jour) : `services.negative_stock.
    grant_negative_stock_exception` REACTIVE la ligne existante
    (potentiellement soft-supprimee) plutot que d'en creer une seconde, ce
    qui rend une contrainte simple suffisante — cf. docstring de ce
    service pour le detail exact de cette reactivation.

    `authorized_by` (`on_delete=PROTECT`, jamais `SET_NULL`) : QUI a
    accorde l'exception doit rester tracable en permanence (l'exception
    elle-meme sert de piece de journalisation RG-STK-10 — "avec
    journalisation" — donc son auteur ne peut jamais disparaitre
    silencieusement). Meme discipline que `PurSubstitute.approved_by`
    (`PROTECT` egalement, verifie explicitement comme precedent) plutot
    que `SET_NULL` (utilise, par contraste, pour les FK "informatives"
    comme `StkMove.operator`).

    `authorized_at` (`auto_now_add=True`) : horodatage de l'octroi, jamais
    modifie par la suite — meme convention que `BaseModel.created_at`.
    Champ metier explicite conserve sous ce nom (vocabulaire RG-STK-10)
    plutot que de faire porter ce sens au `created_at` generique/technique
    du socle, meme si les deux dates coincident en pratique a la creation
    (mais PAS a une reactivation ulterieure — cf. service — ou
    `authorized_at` est reecrit alors que `created_at` reste celui de la
    toute premiere creation, difference qui justifie ce champ distinct).

    Le toggle marche/arret est `BaseModel.is_active` (`soft_delete()`) —
    pas de champ `revoked`/`revoked_at` distinct, meme convention que
    `PurSubstitute` (cf. sa docstring)."""

    variant_id = models.UUIDField()
    authorized_by = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    reason = models.TextField()
    authorized_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stk_negative_stock_exception"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "variant_id"], name="uniq_stk_negative_stock_exception_variant"
            )
        ]

    def __str__(self) -> str:
        return f"{self.variant_id} [{'active' if self.is_active else 'revoked'}]"


class StkImportBatch(BaseModel):
    """Lot d'import xlsx de quantites initiales (ouverture de stock) —
    cf. `services/stock_import.py`, `docs/IMPORT_FORMATS.md`. Meme patron
    exact que `apps.accounting.models.AccImportBatch`/`AccImportRow` : une
    ligne dont une reference (variante/entrepot/emplacement) ne peut pas
    etre resolue avec certitude est mise en attente de resolution humaine
    (`StkImportRow.status=anomaly`) plutot que devinee ou silencieusement
    ignoree — un import de quantites initiales touche potentiellement des
    centaines de lignes issues d'un existant externe, avec le meme besoin
    "corriger les quelques lignes fautives sans rejeter tout le fichier"
    que l'import du journal de caisse (contrairement au plan comptable/aux
    partenaires/au catalogue, tout-ou-rien car sans reference externe a
    resoudre ligne par ligne)."""

    KIND_INITIAL_QUANTITIES = "initial_quantities"
    KIND_CHOICES = [(KIND_INITIAL_QUANTITIES, "Quantités initiales")]

    kind = models.CharField(max_length=24, choices=KIND_CHOICES, default=KIND_INITIAL_QUANTITIES)
    source_filename = models.CharField(max_length=255, blank=True)
    format_version = models.PositiveSmallIntegerField()
    total_rows = models.PositiveIntegerField(default=0)
    anomaly_rows_count = models.PositiveIntegerField(default=0)
    applied_rows_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "stk_import_batch"
        indexes = [models.Index(fields=["tenant", "kind"])]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} — {self.source_filename or self.id}"


class StkImportRow(BaseModel):
    """Une ligne d'un `StkImportBatch` — meme cycle de vie que
    `AccImportRow` (`ok`/`anomaly`/`resolved`/`discarded`). Une ligne SANS
    anomalie produit immediatement un `StkMove` de type `TYPE_AJUSTEMENT`,
    VALIDE (pas seulement brouillon, a la difference de l'import
    comptable) depuis l'emplacement virtuel d'ecart d'inventaire de
    l'entrepot cible vers l'emplacement interne demande — une quantite
    initiale n'a pas de circuit d'approbation metier distinct a suivre
    apres coup (contrairement a une ecriture comptable, qui reste
    brouillon jusqu'a validation humaine explicite) : l'acte d'import EST
    la confirmation, exactement comme `services.inventory.validate_inventory`
    valide immediatement les mouvements d'ecart qu'il genere."""

    STATUS_OK = "ok"
    STATUS_NEEDS_QUALIFICATION = "needs_qualification"
    STATUS_PENDING_APPROVAL = "pending_approval"
    STATUS_QUALIFIED = "qualified"
    STATUS_UNRESOLVABLE = "unresolvable"
    STATUS_RESOLVED = "resolved"
    STATUS_DISCARDED = "discarded"
    STATUS_CHOICES = [
        (STATUS_OK, "Importée"),
        (STATUS_NEEDS_QUALIFICATION, "À qualifier"),
        (STATUS_PENDING_APPROVAL, "Qualification en attente d'approbation"),
        (STATUS_QUALIFIED, "Qualifiée"),
        (STATUS_UNRESOLVABLE, "Non résoluble — à corriger"),
        (STATUS_RESOLVED, "Anomalie corrigée"),
        (STATUS_DISCARDED, "Écartée"),
    ]

    batch = models.ForeignKey(StkImportBatch, on_delete=models.CASCADE, related_name="rows")
    row_number = models.PositiveIntegerField()
    raw_data = models.JSONField(default=dict)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_UNRESOLVABLE)
    anomaly_codes = models.JSONField(default=list, blank=True)
    move = models.ForeignKey(
        StkMove, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Chantier RG-QUALIF — jamais de FK Django vers `apps.catalog.models.
    # ProductVariant` (regle de couplage n°1) : variante resolue (reelle ou
    # placeholder), UUID opaque.
    resolved_variant_id = models.UUIDField(null=True, blank=True)
    resolved_location = models.ForeignKey(
        StkLocation, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    uses_placeholder_variant = models.BooleanField(default=False)
    uses_placeholder_location = models.BooleanField(default=False)
    qualification_approval_request = models.ForeignKey(
        "core.ApprovalRequest", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "stk_import_row"
        indexes = [models.Index(fields=["batch", "status"])]
        permissions = [("qualify_stkimportrow", "Peut qualifier une ligne d'import de stock")]

    def __str__(self) -> str:
        return f"Ligne {self.row_number} du lot {self.batch_id}"
