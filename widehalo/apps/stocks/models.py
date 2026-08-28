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

from apps.core.models.base import BaseModel

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
