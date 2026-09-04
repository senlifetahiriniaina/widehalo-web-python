"""Référentiel catalogue : unités de mesure et conversions, catégories,
attributs/valeurs generateurs de variantes, gammes de produits (template ->
variantes), specs textiles et sectorielles (`CatalogSectorSpec`, cf.
ci-dessous), information fournisseur (couplage generique vers `partners`
par UUID uniquement, jamais de FK Django), listes de prix en cascade,
conditionnement.

SEC3 (extension sectorielle Madagascar, cf. plan) — bilan de l'audit
prealable, note ici a titre de documentation permanente (pas seulement
dans le plan) : `mrp.MrpBomLine.qty_by_size` (JSONB clef->quantite),
`patronage` (grilles de tailles/gradation/`push_to_bom`) et `stocks`
(`StkLot` avec peremption/FEFO, `StkQualityState`) sont deja generiques
dans leur mecanique — AUCUN de ces 3 modules n'a ete modifie pour cette
extension sectorielle, ils sont reutilises tels quels avec des donnees
cuir/agroalimentaire/artisanat (cf.
`apps/catalog/tests/test_sector_end_to_end.py`). Seul `TextileSpec`
ci-dessous etait reellement verrouille sur le textile ; `CatalogSectorSpec`
est son pendant pour les 3 autres secteurs. `import_export` (negoce
generaliste) n'a recu aucun code : deja couvert nativement par
`purchase`/`stocks`/`sales`/`logistics` sans transformation.

REF1-REF3 (enrichissement referentiel LIFE MDG, cf. plan) — deux nouveaux
modeles legers : `CatalogMaterialReference` (referentiel de matieres
fibres/tissus reutilisable) et `CatalogCustomizationOption` (options de
personnalisation broderie/serigraphie/... avec compatibilite matiere,
cf. bas de fichier). `AttributeValue.pantone_code`/`hex_approximation` :
format de reference Pantone FHI Cotton TCX SANS aucune valeur
colorimetrique proprietaire chargee (reserve legale explicite, cf.
docstring `AttributeValue`). Composants semi-finis (trims), produits
d'exemple par famille et entrees lamba malgaches : AUCUN nouveau modele,
ce sont des `ProductTemplate`/`ProductVariant` ordinaires en fixture
demonstrative (REF3)."""

from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models.base import BaseModel, ReferenceMixin


class UnitOfMeasure(BaseModel):
    CATEGORY_WEIGHT = "weight"
    CATEGORY_LENGTH = "length"
    CATEGORY_COUNT = "count"
    CATEGORY_VOLUME = "volume"
    CATEGORY_CHOICES = [
        (CATEGORY_WEIGHT, "Poids"),
        (CATEGORY_LENGTH, "Longueur"),
        (CATEGORY_COUNT, "Comptage"),
        (CATEGORY_VOLUME, "Volume"),
    ]

    code = models.CharField(max_length=16)
    name = models.CharField(max_length=64)
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES)
    is_base = models.BooleanField(default=False)

    class Meta:
        db_table = "catalog_unit_of_measure"

    def __str__(self) -> str:
        return self.code


class UnitConversion(BaseModel):
    """Facteur multiplicatif : `1 <from_unit> == factor <to_unit>`, dans la
    meme categorie (pas de conversion poids<->longueur ici — cf.
    `services/textile.py` pour la conversion tissu specifique qui a besoin
    du grammage et de la laize)."""

    from_unit = models.ForeignKey(UnitOfMeasure, on_delete=models.CASCADE, related_name="+")
    to_unit = models.ForeignKey(UnitOfMeasure, on_delete=models.CASCADE, related_name="+")
    factor = models.DecimalField(max_digits=18, decimal_places=8)

    class Meta:
        db_table = "catalog_unit_conversion"


class Category(BaseModel):
    name = models.CharField(max_length=120)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )

    class Meta:
        db_table = "catalog_category"
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return self.name


class Attribute(BaseModel):
    name = models.CharField(max_length=80)

    class Meta:
        db_table = "catalog_attribute"

    def __str__(self) -> str:
        return self.name


class AttributeValue(BaseModel):
    """REF1 (enrichissement referentiel LIFE MDG, cf. plan) : `pantone_code`/
    `hex_approximation` documentent une valeur d'attribut couleur avec le
    format de reference **Pantone FHI Cotton TCX** (`NN-NNNN TCX`, ex.
    `19-4052 TCX`) — SANS jamais charger de valeur colorimetrique
    proprietaire Pantone (RGB/hex) dans ce depot. `pantone_code` est un
    simple format structure (regex validee par
    `services/material_reference.py::validate_pantone_code`, jamais au
    niveau modele — meme discipline que `CatalogSectorSpec.attributes`,
    valide en service). `hex_approximation` reste TOUJOURS une saisie
    manuelle de l'utilisateur (jamais auto-remplie depuis une source
    Pantone) : l'entreprise doit posseder son propre nuancier physique
    Cotton TCX pour la correspondance exacte, exactement comme le document
    source le recommande lui-meme. Cf. reserve legale explicite du plan."""

    attribute = models.ForeignKey(Attribute, on_delete=models.CASCADE, related_name="values")
    value = models.CharField(max_length=80)
    pantone_code = models.CharField(max_length=16, blank=True, help_text="Format 'NN-NNNN TCX'.")
    hex_approximation = models.CharField(
        max_length=7,
        blank=True,
        help_text=(
            "Approximation hex saisie manuellement — jamais une valeur "
            "sourcee du nuancier Pantone (reserve legale, cf. plan)."
        ),
    )

    class Meta:
        db_table = "catalog_attribute_value"

    def __str__(self) -> str:
        return f"{self.attribute.name}: {self.value}"


MAX_VARIANT_GENERATING_ATTRIBUTES = 2
MAX_VARIANTS_PER_TEMPLATE = 50


class ProductTemplate(BaseModel, ReferenceMixin):
    name = models.CharField(max_length=200)
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="templates"
    )
    # STK-11 (Phase 3 §12.2, sprint A5) : « chaque article a une unite de
    # stock unique et immuable apres le premier mouvement — la changer
    # invaliderait tout l'historique. » Garde posee en base (migration
    # `catalog.0013`, trigger `catalog_product_template_reject_uom_change_
    # after_movement`) plutot qu'ici en Python : aucune fonction de service
    # `update_product_template` n'existe aujourd'hui (les ecrans/API actuels
    # ne font que CREER un template, cf. `views.template_create`/
    # `api.py::create_template`) — le trigger anticipe donc un futur ecran
    # d'edition sans laisser un trou d'integrite en attendant, meme
    # discipline que STK-6/A4 pour un endpoint API pas encore ecrit. Le
    # trigger interroge directement `stk_move`/`catalog_product_variant` en
    # SQL pur (jamais un import Python `apps.stocks.*` — `catalog` ne
    # declare toujours pas `stocks` comme dependance, cf. `module.py` ;
    # une trigger SQL n'est pas soumise a la regle de couplage n1, qui ne
    # porte que sur les imports Python).
    base_uom = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="+")
    variant_attributes = models.ManyToManyField(Attribute, blank=True, related_name="templates")
    base_price_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)

    # Le catalogue est organise en parent (`ProductTemplate`) / fils
    # (`ProductVariant`, cf. ci-dessous) — cette case a cocher indique si
    # LE PRODUIT (au niveau du parent, pas variante par variante) peut
    # etre vendu a un client, par opposition a un composant/matiere interne
    # (ex. les "trims" de `sample_products_by_family.json` — zip, bouton,
    # doublure — jamais vendus tels quels, seulement consommes par une
    # nomenclature MRP). Defaut `True` : un produit cree normalement est
    # vendable, sauf indication contraire explicite.
    is_sellable = models.BooleanField(default=True)

    # Bloc D, D2 (QUA-8) : niveau TEMPLATE (meme granularite qu'is_sellable
    # ci-dessus), pas variante — un certificat d'analyse est une exigence
    # de matiere premiere/type de produit, jamais une propriete de
    # taille/couleur (a la difference d'is_lot_tracked cote
    # `ProductVariant`, deliberement au niveau variante pour une raison
    # differente documentee sur son propre champ). Defaut `False` :
    # aucune exigence sauf indication contraire explicite du tenant.
    requires_certificate_of_analysis = models.BooleanField(default=False)

    class Meta:
        db_table = "catalog_product_template"

    def __str__(self) -> str:
        return f"{self.reference} — {self.name}"


class ProductVariant(BaseModel, ReferenceMixin):
    template = models.ForeignKey(ProductTemplate, on_delete=models.CASCADE, related_name="variants")
    attribute_values = models.ManyToManyField(AttributeValue, related_name="variants")

    # Variante generique creee par
    # `apps.catalog.services.defaults.ensure_default_variant` quand un
    # import n'a pas identifie avec certitude la variante reelle (chantier
    # RG-QUALIF) — meme discipline que `partners.Partner.is_placeholder`.
    is_placeholder = models.BooleanField(default=False)

    # Code-barres EAN-13/GTIN par variante (T1 refonte UX, Sprint 4 / L3,
    # cf. docs/planning/2026-refonte-ux-sprints.md §5) — assigne par
    # `apps.catalog.services.barcodes.assign_ean13`, jamais saisi a la
    # main (checksum GS1 calcule). Vide tant qu'aucune variante n'a ete
    # generee/codee (variantes historiques anterieures a ce chantier).
    ean13 = models.CharField(max_length=13, blank=True, db_index=True)

    # STK-11 (Phase 3 §12.3 tableau "Lot", sprint A5) : « un article est
    # declare gere par lot ou non ; le passage de non a oui n'est possible
    # qu'a stock nul, et l'ecran l'explique plutot que de refuser sans
    # motif. » Champ nouveau (aucun equivalent n'existait avant A5, cf.
    # rapport de recherche du sprint — `StkLot`/`StkQuant`/`StkMove` sont
    # deja tous keyes par `variant_id`, donc ce booleen vit au niveau
    # VARIANTE, pas template, meme granularite). Defaut `False` : une
    # variante creee normalement n'est pas geree par lot, activation
    # explicite. « Stock nul » = stock physique sur emplacements INTERNES
    # uniquement (meme perimetre que `stocks.services.quants.on_hand_qty`,
    # PAS la vue brute double-entree qui inclut les emplacements virtuels)
    # — garde posee en base (migration `catalog.0013`, trigger
    # `catalog_product_variant_reject_lot_tracking_flip_with_stock`), pas
    # en Python ici, pour la meme raison que `base_uom` ci-dessus
    # (aucune fonction `update_variant` n'existe encore, et une trigger SQL
    # peut lire `stk_quant` sans jamais introduire d'import Python
    # `catalog` -> `stocks`, qui casserait le sens unique de couplage
    # etabli par `stocks.module.py`). Seul le sens non -> oui est garde,
    # conformement au CDC (le sens oui -> non n'est pas mentionne comme
    # contraint). Aucun ecran n'edite ce champ a ce jour (uniquement cree
    # a `False` implicite) : la clause CDC « l'ecran l'explique » reste un
    # rappel pour le futur ecran d'edition de variante, pas un gap actuel.
    is_lot_tracked = models.BooleanField(default=False)

    class Meta:
        db_table = "catalog_product_variant"

    def __str__(self) -> str:
        return self.reference


class TextileSpec(BaseModel):
    variant = models.OneToOneField(
        ProductVariant, on_delete=models.CASCADE, related_name="textile_spec"
    )
    material = models.CharField(max_length=120, blank=True)
    composition = models.JSONField(default=dict, blank=True)
    weight_gsm = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Grammage, g/m²"
    )
    width_cm = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Laize, cm"
    )
    certifications = ArrayField(models.CharField(max_length=64), default=list, blank=True)

    class Meta:
        db_table = "catalog_textile_spec"


class ProductSupplierInfo(BaseModel):
    """Information fournisseur d'une variante. `partner_id` reste un UUID
    simple, JAMAIS une FK Django vers `apps.partners.models.Partner` — le
    couplage entre `catalog` et `partners` ne doit transiter que par
    `partners.services.public` (cf. regle de couplage n°1).

    `priority`/`origin`/`min_qty` : gap PU2 du sous-sequencement `purchase`
    (RG-PUR-1, cf. plan) — le CDC exige que la selection multi-fournisseurs
    se fasse dans l'ordre priority > prix > delai. Convention retenue pour
    `priority` : plus la valeur est **basse**, plus la priorite est
    **haute** (memes semantiques qu'un rang de tri, coherent avec l'ordre
    de tri croissant applique ensuite sur prix puis delai — les trois
    criteres se trient tous en ordre croissant, aucune inversion a gerer
    dans `select_preferred_supplier`). Ces 3 champs sont ajoutes sans
    migration de donnees : les lignes existantes recoivent les valeurs par
    defaut (`priority=10`, `origin="local"`, `min_qty=0`), simplification
    documentee (pas de retro-classement des fournisseurs deja saisis)."""

    ORIGIN_LOCAL = "local"
    ORIGIN_IMPORT_CHINE = "import_chine"
    ORIGIN_IMPORT_AUTRE = "import_autre"
    ORIGIN_EN_LIGNE = "en_ligne"
    ORIGIN_CHOICES = [
        (ORIGIN_LOCAL, "Local"),
        (ORIGIN_IMPORT_CHINE, "Import Chine"),
        (ORIGIN_IMPORT_AUTRE, "Import autre"),
        (ORIGIN_EN_LIGNE, "En ligne"),
    ]

    variant = models.ForeignKey(
        ProductVariant, on_delete=models.CASCADE, related_name="supplier_infos"
    )
    partner_id = models.UUIDField()
    supplier_reference = models.CharField(max_length=100, blank=True)
    price_mga = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    lead_time_days = models.PositiveIntegerField(default=0)
    # Plus bas = plus prioritaire (cf. docstring ci-dessus).
    priority = models.PositiveSmallIntegerField(default=10)
    origin = models.CharField(max_length=16, choices=ORIGIN_CHOICES, default=ORIGIN_LOCAL)
    min_qty = models.DecimalField(max_digits=18, decimal_places=4, default=0)

    class Meta:
        db_table = "catalog_product_supplier_info"


class PriceList(BaseModel):
    KIND_DEFAULT = "default"
    KIND_CLIENT = "client"
    KIND_CONTRACT = "contract"
    KIND_CHOICES = [
        (KIND_DEFAULT, "Liste par defaut"),
        (KIND_CLIENT, "Liste client"),
        (KIND_CONTRACT, "Contrat"),
    ]

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    # Meme convention que ProductSupplierInfo : UUID simple, jamais de FK vers `partners`.
    partner_id = models.UUIDField(null=True, blank=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "catalog_price_list"


class PriceListItem(BaseModel):
    price_list = models.ForeignKey(PriceList, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.CASCADE, related_name="price_items"
    )
    price_mga = models.DecimalField(max_digits=18, decimal_places=4)

    class Meta:
        db_table = "catalog_price_list_item"
        constraints = [
            models.UniqueConstraint(fields=["price_list", "variant"], name="uniq_price_list_item")
        ]


class Packaging(BaseModel):
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name="packagings")
    unit_count = models.PositiveIntegerField(default=1)
    uom = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="+")
    barcode = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "catalog_packaging"


class CatalogStandard(BaseModel):
    """CAT-NORM1 : catalogue de normes/certifications (OEKO-TEX 100, GOTS,
    ISO 105 series, REACH...), referencable par `TextileSpec.certifications`
    ou par une certification datee via `CatalogCertification`."""

    code = models.CharField(max_length=32)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)

    class Meta:
        db_table = "catalog_standard"

    def __str__(self) -> str:
        return self.code


class CatalogCertification(BaseModel):
    """Certification datee d'une variante par un fournisseur donne — utilise
    par `mrp` (RG bloquante MRP-QQCD1 : conformite bloquante si une
    certification obligatoire manque ou est expiree).

    **`status` (QLT1-2, chantier qualite/certifications) — defaut
    `STATUS_OBTAINED` (choix assume)** : avant ce lot, une
    `CatalogCertification` ne pouvait representer QUE le cas "certification
    deja acquise" — c'est exactement le comportement suppose par toutes les
    fixtures/tests existants (`CatalogCertificationFactory`, `seed_catalog`,
    `load_sample_products`) et par `get_valid_certifications` (filtre
    uniquement sur les dates `valid_from`/`valid_until`, jamais sur un
    statut). Un defaut different (ex. `STATUS_TARGETED`) aurait
    silencieusement change le sens de chaque ligne deja creee sans qu'aucun
    appelant existant ne le decide explicitement — casse assumee a eviter.
    `status` reste un champ librement modifiable ensuite (ex. `vise` ->
    `en_cours` -> `obtenue`, ou `obtenue` -> `expiree`) pour suivre le cycle
    de vie reel d'une certification vise par le CDC (§5 qualite/
    certifications) ; son cablage dans `get_valid_certifications` (ex.
    n'accepter que `obtenue`) reste un travail futur hors perimetre QLT1-2
    (disclosed) : ce lot ajoute le champ de suivi, pas un nouveau
    comportement de blocage MRP."""

    STATUS_TARGETED = "vise"
    STATUS_IN_PROGRESS = "en_cours"
    STATUS_OBTAINED = "obtenue"
    STATUS_EXPIRED = "expiree"
    STATUS_CHOICES = [
        (STATUS_TARGETED, _("Visée")),
        (STATUS_IN_PROGRESS, _("En cours")),
        (STATUS_OBTAINED, _("Obtenue")),
        (STATUS_EXPIRED, _("Expirée")),
    ]

    variant = models.ForeignKey(
        ProductVariant, on_delete=models.CASCADE, related_name="certifications_detail"
    )
    standard = models.ForeignKey(CatalogStandard, on_delete=models.PROTECT, related_name="+")
    # Jamais de FK Django vers `apps.partners.models.Partner`.
    partner_id = models.UUIDField(null=True, blank=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_OBTAINED)

    class Meta:
        db_table = "catalog_certification"

    def __str__(self) -> str:
        return f"{self.variant_id} — {self.standard.code}"


class CatalogSectorSpec(BaseModel):
    """SEC1 (extension sectorielle Madagascar, cf. plan) : fiche de
    specification sectorielle pour cuir & maroquinerie / agroalimentaire /
    artisanat — jamais `import_export`, dont le negoce sans transformation
    est deja couvert nativement par `purchase`/`stocks`/`sales`/`logistics`
    sans aucune extension (confirme par audit prealable, cf. plan) : aucun
    code n'existe donc ici pour ce secteur, ni dans
    `SECTOR_CHOICES` ci-dessous, ni dans les validateurs de
    `services/sector_specs.py`.

    **Un seul modele flexible**, choisi plutot que trois modeles rigides
    façon `TextileSpec` duplique par secteur, pour economiser le budget de
    modeles (`tests/architecture/test_budget.py`) et suivre le patron JSONB
    deja applique a `TextileSpec.composition`/`mrp.MrpBomLine.qty_by_size` :
    `attributes` (JSONB) a un schema qui varie selon `sector_code`, valide
    en service par un petit dictionnaire de validateurs Python
    (`services/sector_specs.py`), PAS par un moteur JSON Schema generique —
    simplification deliberee et documentee, coherente avec le choix deja
    fait pour `TextileSpec.composition` (JSONB libre, jamais verrouille par
    un schema formel externe).

    Meme mecanique de relation qu'une extension `TextileSpec` : FK directe
    vers `ProductVariant` legitime car les deux modeles vivent dans la
    meme app `catalog` (pas un couplage cross-app, cf. regle de couplage
    n°1). Un seul secteur par variante (`OneToOne`), meme choix que
    `TextileSpec` — une variante donnee releve d'un seul secteur metier a
    la fois."""

    SECTOR_CUIR = "cuir"
    SECTOR_AGROALIMENTAIRE = "agroalimentaire"
    SECTOR_ARTISANAT = "artisanat"
    SECTOR_CHOICES = [
        (SECTOR_CUIR, "Cuir & maroquinerie"),
        (SECTOR_AGROALIMENTAIRE, "Agroalimentaire"),
        (SECTOR_ARTISANAT, "Artisanat"),
    ]

    variant = models.OneToOneField(
        ProductVariant, on_delete=models.CASCADE, related_name="sector_spec"
    )
    sector_code = models.CharField(max_length=16, choices=SECTOR_CHOICES)
    attributes = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "catalog_sector_spec"

    def __str__(self) -> str:
        return f"{self.variant_id} — {self.sector_code}"


class CatalogMaterialReference(BaseModel):
    """REF1 (enrichissement referentiel LIFE MDG, cf. plan) : referentiel
    normalise de matieres fibres/tissus (coton, PES, polycoton,
    modacrylique, Nomex, Kevlar, laine, soie, lin, neoprene, Gore-Tex,
    mesh...), reutilisable d'une variante a l'autre — a la difference de
    `TextileSpec.composition` (JSONB libre, propre a UNE variante), ce
    modele documente une liste de reference PARTAGEE que plusieurs
    `TextileSpec`/produits peuvent citer (par `code`, en texte libre pour
    l'instant — aucune FK depuis `TextileSpec` : simplification deliberee,
    cf. `services/material_reference.py`, pas de rupture retroactive sur
    les fiches textiles deja saisies en JSONB libre).

    `typical_gsm_min`/`typical_gsm_max` : fourchette de grammage indicative
    (tableau du document source), PAS une specification absolue — varie
    par fabricant/construction/lavage (disclosed explicitement dans le
    fixture `materials_reference_mg.json`, meme reserve non-experte que
    `pcg2005_mg.json`/`textile_mg.json`).

    `supplier_reference` : texte libre (ex. "DuPont", "W.L. Gore") —
    documentaire, JAMAIS une FK vers `apps.partners.models.Partner` : ce
    sont des references industrielles generiques (marques de matiere),
    pas necessairement des fournisseurs reels du tenant tant qu'aucune
    relation commerciale n'existe (regle de couplage n°1)."""

    NATURE_NATURELLE_CELLULOSIQUE = "naturelle_cellulosique"
    NATURE_NATURELLE_PROTEIQUE = "naturelle_proteique"
    NATURE_SYNTHETIQUE_HYDROPHOBE = "synthetique_hydrophobe"
    NATURE_SYNTHETIQUE_FR = "synthetique_fr"
    NATURE_MELANGE = "melange"
    NATURE_CAOUTCHOUC = "caoutchouc"
    NATURE_MEMBRANE = "membrane"
    NATURE_CHOICES = [
        (NATURE_NATURELLE_CELLULOSIQUE, "Naturelle cellulosique"),
        (NATURE_NATURELLE_PROTEIQUE, "Naturelle proteique"),
        (NATURE_SYNTHETIQUE_HYDROPHOBE, "Synthetique hydrophobe"),
        (NATURE_SYNTHETIQUE_FR, "Synthetique ignifuge (FR)"),
        (NATURE_MELANGE, "Melange"),
        (NATURE_CAOUTCHOUC, "Caoutchouc"),
        (NATURE_MEMBRANE, "Membrane technique"),
    ]

    code = models.CharField(max_length=32)
    name = models.CharField(max_length=120)
    nature = models.CharField(max_length=32, choices=NATURE_CHOICES)
    typical_gsm_min = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Grammage min, g/m²"
    )
    typical_gsm_max = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Grammage max, g/m²"
    )
    usage_notes = models.TextField(blank=True)
    supplier_reference = models.CharField(max_length=150, blank=True)

    class Meta:
        db_table = "catalog_material_reference"

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class CatalogCustomizationOption(BaseModel):
    """REF2 (enrichissement referentiel LIFE MDG, cf. plan) : option de
    personnalisation d'un produit (broderie, serigraphie, sublimation,
    transfert thermocollant, floquage, gravure, badge). `compatible_materials`
    (M2M vers `CatalogMaterialReference`, meme app donc FK/M2M legitime,
    regle de couplage n°1) documente les compatibilites matiere connues
    (ex. la sublimation necessite ~100% PES — cf. `notes` et fixture
    `customization_options.json`) — c'est une liste POSITIVE de
    compatibilites connues, pas une contrainte bloquante en base : une
    option non listee comme compatible avec une matiere n'est pas
    forcement impossible, seulement non documentee dans le fixture
    indicatif (meme reserve non-experte que le reste du referentiel)."""

    TECHNIQUE_BRODERIE = "broderie"
    TECHNIQUE_SERIGRAPHIE = "serigraphie"
    TECHNIQUE_SUBLIMATION = "sublimation"
    TECHNIQUE_TRANSFERT_THERMOCOLLANT = "transfert_thermocollant"
    TECHNIQUE_FLOQUAGE = "floquage"
    TECHNIQUE_GRAVURE = "gravure"
    TECHNIQUE_BADGE = "badge"
    TECHNIQUE_CHOICES = [
        (TECHNIQUE_BRODERIE, "Broderie"),
        (TECHNIQUE_SERIGRAPHIE, "Serigraphie"),
        (TECHNIQUE_SUBLIMATION, "Sublimation"),
        (TECHNIQUE_TRANSFERT_THERMOCOLLANT, "Transfert thermocollant"),
        (TECHNIQUE_FLOQUAGE, "Floquage"),
        (TECHNIQUE_GRAVURE, "Gravure"),
        (TECHNIQUE_BADGE, "Badge"),
    ]

    code = models.CharField(max_length=32)
    name = models.CharField(max_length=120)
    technique = models.CharField(max_length=32, choices=TECHNIQUE_CHOICES)
    compatible_materials = models.ManyToManyField(
        CatalogMaterialReference, blank=True, related_name="customization_options"
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "catalog_customization_option"

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"
