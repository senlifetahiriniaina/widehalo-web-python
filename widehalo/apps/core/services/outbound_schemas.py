"""T0 (Phase 4, axes A1 et A2, §9.2) — ce que chaque module accepte de
laisser sortir, déclaré avant qu'une liaison existe.

**Le défaut fermé ici, et il est structurel.** Le hub de flux sait depuis
le sprint S5 refuser une correspondance incomplète *au regard du schéma du
tiers* (FLX-6). Il ne savait rien du NÔTRE : `save_mapping` validait
`field_map` contre `target_schema`, c'est-à-dire contre ce que le tiers
déclare attendre, et jamais contre ce que nous acceptons d'émettre. Une
correspondance pouvait donc désigner `lines[].margin_pct` comme source :
elle était acceptée, enregistrée, et la marge partait chez le tiers au
premier échange. Le §9.2 du cahier l'interdit mot pour mot — « Champs
internes — marge, coût de revient, commentaires de gestion — exclus par
défaut de toute correspondance » — mais un interdit sans schéma source
n'est qu'une phrase.

**Quatre règles du §9.2, toutes tenues ici.**

- *Pièce commerciale complète* — « marge, coût de revient, commentaires de
  gestion — exclus par défaut de toute correspondance » : ces champs sont
  déclarés et marqués interdits, avec motif écrit.
- *Identité et coordonnées de client* — « minimisation obligatoire : seuls
  les champs exigés par l'opération partent » : chaque champ déclare les
  opérations qui l'exigent, et une source non exigée est refusée.
- *Montant et référence de règlement* — « aucun numéro de compte complet
  dans une trace ou une charge utile archivée » : le numéro complet est
  déclaré interdit, seule la classe PCG sort.
- *Rémunération et données de paie* — « interdiction absolue […] vérifiée
  en intégration continue » : aucun document du domaine paie ne peut être
  enregistré ici, et une garde le vérifie.

**Pourquoi DÉCLARER l'interdit plutôt que l'omettre.** Un champ absent du
registre est déjà refusé — c'est la règle de fermeture. Nommer en plus
`lines[].margin_pct` comme interdit paraît donc redondant. Ça ne l'est
pas, pour deux raisons. D'abord le message : « champ non déclaré » et
« marge : champ interne, §9.2 » n'apprennent pas la même chose à qui
configure la liaison. Ensuite, et surtout, la garde : un interdit qu'on
n'a pas nommé ne se teste pas. Le jour où quelqu'un ajoute `margin_pct`
aux champs émis, seule une assertion qui NOMME ce champ s'y oppose.

**La déclaration n'est pas un commentaire : elle produit la charge
utile.** Chaque document déclare son `builder`, qui projette l'objet
métier en dictionnaire. `project_document` élague ensuite la projection
aux seuls chemins déclarés et émis. Un `builder` distrait qui ajouterait
la marge ne la fait donc pas sortir — l'élagage la retire. C'est cette
double barrière qui distingue ce registre d'un document de conception :
le schéma est ce qui construit la donnée, pas ce qui la décrit après coup.

**Registre en mémoire, déclaré depuis `apps.py::ready()`**, comme les
rapports, les anomalies, les adaptateurs et les opérations publiques. Un
schéma de sortie est un artefact de LIVRAISON : le stocker en base
permettrait à une ligne de configuration de désigner un champ absent de la
version déployée.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

#: Longueur minimale d'un motif écrit, même seuil que les autres registres
#: à motif du dépôt (`endpoint_governance`, `regulatory_governance`) : en
#: dessous, on écrit « interne » et on n'a rien expliqué.
MOTIF_MINIMUM = 40

#: Les huit opérations du cahier (§4.1), recopiées ici en CHAÎNES et non
#: importées : `apps.core` ne peut pas importer `apps.flows` (règle de
#: couplage n°1, `tests/architecture/test_module_boundaries.py`). La
#: fermeture est donc vérifiée par une garde qui, elle, voit les deux —
#: `tests/architecture/test_outbound_schema_vocabularies_are_closed.py`.
OPERATION_CODES: frozenset[str] = frozenset({f"OP{n}" for n in range(1, 9)})

#: Valeur explicite pour « aucune restriction par opération » : le champ
#: peut accompagner n'importe laquelle des huit. L'écrire évite qu'un
#: ensemble vide signifie tantôt « toutes » tantôt « aucune » — ambiguïté
#: qui ne survit jamais à deux sprints.
ALL_OPERATIONS: frozenset[str] = OPERATION_CODES


# --- Les six catégories du §9.2, fermées ---------------------------------------

CATEGORY_COMMERCIAL_DOCUMENT = "piece_commerciale"
CATEGORY_PARTY_IDENTITY = "identite_tiers"
CATEGORY_SETTLEMENT = "reglement"
CATEGORY_PAYROLL = "paie"
CATEGORY_PRODUCTION = "production"
CATEGORY_AUDIT_TRAIL = "preuve"


@dataclass(frozen=True)
class DataCategory:
    """Une ligne du tableau §9.2, avec sa règle citée.

    `outbound_allowed` dit si la catégorie peut sortir DU TOUT ;
    `minimisation` dit si, en plus, chaque champ doit justifier l'opération
    qui l'exige. Les deux sont distincts : la pièce commerciale sort
    entière après consentement, l'identité ne sort que champ par champ."""

    code: str
    #: `str | Promise` et non `str` : les libellés et la règle citée sont
    #: traduisibles, donc paresseux. Les typer `str` obligerait à choisir
    #: entre un libellé non traduit et un `# type: ignore` par ligne.
    label: str | Promise
    outbound_allowed: bool
    minimisation: bool
    rule: str | Promise


CATEGORIES: dict[str, DataCategory] = {
    CATEGORY_COMMERCIAL_DOCUMENT: DataCategory(
        code=CATEGORY_COMMERCIAL_DOCUMENT,
        label=_("Pièce commerciale complète (facture, commande)"),
        outbound_allowed=True,
        minimisation=False,
        rule=_(
            "Sortie autorisée après consentement. Champs internes — marge, coût "
            "de revient, commentaires de gestion — exclus par défaut de toute "
            "correspondance."
        ),
    ),
    CATEGORY_PARTY_IDENTITY: DataCategory(
        code=CATEGORY_PARTY_IDENTITY,
        label=_("Identité et coordonnées de client"),
        outbound_allowed=True,
        minimisation=True,
        rule=_(
            "Minimisation obligatoire : seuls les champs exigés par l'opération "
            "partent. La correspondance de champs ne peut pas ajouter un champ "
            "non déclaré nécessaire."
        ),
    ),
    CATEGORY_SETTLEMENT: DataCategory(
        code=CATEGORY_SETTLEMENT,
        label=_("Montant et référence de règlement"),
        outbound_allowed=True,
        minimisation=False,
        rule=_(
            "Sortie autorisée. Aucun numéro de compte complet dans une trace ou "
            "une charge utile archivée."
        ),
    ),
    CATEGORY_PAYROLL: DataCategory(
        code=CATEGORY_PAYROLL,
        label=_("Rémunération et données de paie"),
        outbound_allowed=False,
        minimisation=True,
        rule=_(
            "Interdiction absolue. Aucune liaison ne peut avoir pour source un "
            "objet du domaine Paie, à la seule exception de l'ordre de virement, "
            "qui expose un montant et un bénéficiaire sans aucun élément de "
            "rubrique. Vérifié en intégration continue."
        ),
    ),
    CATEGORY_PRODUCTION: DataCategory(
        code=CATEGORY_PRODUCTION,
        label=_("Données de production, nomenclature, coût"),
        outbound_allowed=False,
        minimisation=True,
        rule=_(
            "Aucune liaison sortante native. L'API publique y donne accès si et "
            "seulement si le rôle du jeton le permet, sous la responsabilité du "
            "client."
        ),
    ),
    CATEGORY_AUDIT_TRAIL: DataCategory(
        code=CATEGORY_AUDIT_TRAIL,
        label=_("Journal d'audit et registre d'échange"),
        outbound_allowed=False,
        minimisation=True,
        rule=_(
            "Jamais transmis à un tiers dans le cadre d'une liaison. Exportable "
            "intégralement par le client."
        ),
    ),
}


# --- Le champ déclaré ----------------------------------------------------------


@dataclass(frozen=True)
class OutboundField:
    """Un chemin du document, et ce qu'on a le droit d'en faire.

    `path` est un chemin de lecture dans la projection, pas un nom de
    colonne : `partner.tax_id`, `lines[].description`. Le segment `[]`
    traverse une liste — c'est là que vivent les champs de ligne, donc là
    que le §9.2 mord réellement (la marge est sur la ligne, pas sur
    l'en-tête).

    `forbidden_because` non vide fait du champ un INTERDIT DÉCLARÉ : il ne
    sort jamais, aucune correspondance ne peut le désigner, et l'élagage
    le retire même si le `builder` l'a produit. Le motif est écrit, et
    long : « interne » n'apprend rien à qui lit le refus."""

    path: str
    label: str | Promise
    category: str
    required_by: frozenset[str] = ALL_OPERATIONS
    forbidden_because: str = ""
    filterable: bool = False

    @property
    def is_forbidden(self) -> bool:
        return bool(self.forbidden_because)

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValidationError(
                _("Catégorie §9.2 inconnue pour « %(path)s » : %(cat)s.")
                % {"path": self.path, "cat": self.category}
            )
        if not self.path or self.path.strip() != self.path:
            raise ValidationError(_("Chemin de champ vide ou mal formé : %r.") % self.path)
        categorie = CATEGORIES[self.category]

        if self.is_forbidden:
            if len(self.forbidden_because) < MOTIF_MINIMUM:
                raise ValidationError(
                    _(
                        "Le motif d'interdiction de « %(path)s » fait %(n)s "
                        "caractères ; il en faut au moins %(min)s. Un interdit "
                        "sans motif écrit se lève par distraction."
                    )
                    % {
                        "path": self.path,
                        "n": len(self.forbidden_because),
                        "min": MOTIF_MINIMUM,
                    }
                )
            if self.filterable:
                raise ValidationError(
                    _(
                        "« %(path)s » est interdit de sortie mais déclaré "
                        "filtrable : un filtre sur un champ interdit choisit "
                        "quels objets partent d'après une donnée qui n'a pas le "
                        "droit de sortir, ce qui la divulgue par déduction."
                    )
                    % {"path": self.path}
                )
            return

        if self.filterable and "[]" in self.path:
            raise ValidationError(
                _(
                    "« %(path)s » traverse une liste et ne peut pas être "
                    "filtrable : un filtre s'évalue sur une valeur unique, et "
                    "sur une liste il lirait `None` sans que rien ne le dise — "
                    "le déclencheur ne tirerait jamais, silencieusement."
                )
                % {"path": self.path}
            )
        if not categorie.outbound_allowed:
            raise ValidationError(
                _(
                    "« %(path)s » relève de la catégorie « %(cat)s », dont le "
                    "§9.2 interdit la sortie. Un champ de cette catégorie ne "
                    "peut être déclaré qu'INTERDIT, avec son motif."
                )
                % {"path": self.path, "cat": categorie.code}
            )
        inconnues = set(self.required_by) - OPERATION_CODES
        if inconnues:
            raise ValidationError(
                _("Opération(s) inconnue(s) sur « %(path)s » : %(ops)s.")
                % {"path": self.path, "ops": ", ".join(sorted(inconnues))}
            )
        if not self.required_by:
            raise ValidationError(
                _(
                    "« %(path)s » n'est exigé par aucune opération. Un champ que "
                    "rien n'exige ne se déclare pas : il s'omet (ou s'interdit "
                    "explicitement). Écrire ALL_OPERATIONS pour « toutes »."
                )
                % {"path": self.path}
            )


# --- Le document déclaré -------------------------------------------------------

#: Signature du projecteur : de l'identifiant de la pièce vers son
#: dictionnaire, ou `None` si la pièce n'existe pas (ou n'est pas visible
#: dans la société active — la projection passe par les gestionnaires
#: filtrés, jamais par `all_objects`).
DocumentBuilder = Callable[[UUID], dict[str, Any] | None]


@dataclass(frozen=True)
class OutboundDocument:
    """Une pièce métier liable, ses champs et son projecteur.

    `code` est `app_label.NomDeModele` — exactement la valeur que
    `workflow.transitioned` porte sous la clef `model`, pour que le hub
    retrouve le schéma d'une pièce sans table de correspondance
    supplémentaire."""

    code: str
    label: str | Promise
    category: str
    fields: tuple[OutboundField, ...]
    builder: DocumentBuilder
    _by_path: dict[str, OutboundField] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValidationError(
                _("Catégorie §9.2 inconnue pour le document « %(code)s ».") % {"code": self.code}
            )
        if self.code.count(".") != 1 or not all(self.code.split(".")):
            raise ValidationError(
                _("Le code d'un document liable s'écrit « app.Modele » — reçu « %(code)s ».")
                % {"code": self.code}
            )
        if not self.fields:
            raise ValidationError(
                _(
                    "Le document « %(code)s » ne déclare aucun champ : il serait "
                    "liable et n'émettrait rien."
                )
                % {"code": self.code}
            )
        par_chemin: dict[str, OutboundField] = {}
        for champ in self.fields:
            if champ.path in par_chemin:
                raise ValidationError(
                    _("Le champ « %(path)s » est déclaré deux fois sur « %(code)s ».")
                    % {"path": champ.path, "code": self.code}
                )
            par_chemin[champ.path] = champ
        object.__setattr__(self, "_by_path", par_chemin)

    def get_field(self, path: str) -> OutboundField | None:
        return self._by_path.get(path)

    @property
    def emitted_paths(self) -> tuple[str, ...]:
        return tuple(champ.path for champ in self.fields if not champ.is_forbidden)

    @property
    def forbidden_paths(self) -> tuple[str, ...]:
        return tuple(champ.path for champ in self.fields if champ.is_forbidden)

    @property
    def filterable_paths(self) -> tuple[str, ...]:
        return tuple(champ.path for champ in self.fields if champ.filterable)


# --- Le registre ---------------------------------------------------------------

_DOCUMENTS: dict[str, OutboundDocument] = {}


def register_outbound_document(document: OutboundDocument) -> None:
    """Déclare une pièce liable. Idempotent sur le code.

    Refuse un code déjà pris par une DÉCLARATION DIFFÉRENTE : deux
    déclarations pour le même modèle rendraient la liste des champs émis
    dépendante de l'ordre de chargement des applications, donc la
    minimisation dépendante de `INSTALLED_APPS`."""
    existant = _DOCUMENTS.get(document.code)
    if (
        existant is not None
        and existant is not document
        and (existant.fields, existant.category) != (document.fields, document.category)
    ):
        raise ValidationError(
            _(
                "Le document liable « %(code)s » est déjà déclaré avec un autre "
                "schéma. Deux schémas pour un même modèle rendraient la "
                "minimisation dépendante de l'ordre de chargement des applications."
            )
            % {"code": document.code}
        )
    _DOCUMENTS[document.code] = document


def get_outbound_document(code: str) -> OutboundDocument | None:
    return _DOCUMENTS.get(code)


def list_outbound_documents() -> list[OutboundDocument]:
    return [_DOCUMENTS[code] for code in sorted(_DOCUMENTS)]


def outbound_document_codes() -> frozenset[str]:
    return frozenset(_DOCUMENTS)


# --- Ce que le hub appelle -----------------------------------------------------


class SourceFieldRefusedError(ValidationError):
    """Un chemin source refusé, et la raison lisible du refus.

    Une sous-classe plutôt qu'un code : l'appelant (`save_mapping`) veut
    RAPPORTER tous les refus d'un coup à l'écran d'édition, pas s'arrêter
    au premier."""


def validate_source_path(document_code: str, path: str, *, operations: Iterable[str] = ()) -> None:
    """Refuse un chemin source qui n'a pas le droit de partir.

    Quatre refus, dans l'ordre où ils comptent :

    1. le document n'est pas déclaré liable — rien de ce qu'il porte ne
       peut sortir tant qu'un module n'a pas dit ce qui le peut ;
    2. le chemin n'est pas déclaré — c'est la fermeture, et c'est elle qui
       tient « la correspondance ne peut pas ajouter un champ non déclaré » ;
    3. le chemin est déclaré INTERDIT — le refus cite alors le motif écrit ;
    4. le chemin est déclaré mais aucune des opérations de la liaison ne
       l'exige — c'est la minimisation du §9.2, et elle ne s'applique
       qu'aux catégories qui la portent.

    `operations` vide veut dire « on ne sait pas quelles opérations cette
    liaison sert » : le contrôle 4 est alors sauté plutôt que deviné. Le
    déclarer explicitement vaut mieux qu'un refus fondé sur une supposition
    — et l'appelant de production, `save_mapping`, le renseigne toujours."""
    document = _DOCUMENTS.get(document_code)
    if document is None:
        raise SourceFieldRefusedError(
            _(
                "Le document « %(code)s » n'est pas déclaré liable. Un module "
                "déclare ce qui peut sortir (registre des schémas de sortie) "
                "avant qu'une correspondance puisse le désigner."
            )
            % {"code": document_code}
        )
    champ = document.get_field(path)
    if champ is None:
        raise SourceFieldRefusedError(
            _(
                "« %(path)s » n'est pas un champ déclaré de « %(code)s ». Champs "
                "déclarés : %(liste)s."
            )
            % {
                "path": path,
                "code": document_code,
                "liste": ", ".join(document.emitted_paths) or _("aucun"),
            }
        )
    if champ.is_forbidden:
        raise SourceFieldRefusedError(
            _("« %(path)s » est interdit de sortie — %(motif)s")
            % {"path": path, "motif": champ.forbidden_because}
        )
    if not CATEGORIES[champ.category].minimisation:
        return
    demandees = set(operations)
    if demandees and not (demandees & set(champ.required_by)):
        raise SourceFieldRefusedError(
            _(
                "« %(path)s » n'est exigé par aucune des opérations de cette "
                "liaison (%(demandees)s) — minimisation §9.2 : seuls les champs "
                "exigés par l'opération partent. Exigé par : %(exigent)s."
            )
            % {
                "path": path,
                "demandees": ", ".join(sorted(demandees)),
                "exigent": ", ".join(sorted(champ.required_by)),
            }
        )


def _prune(valeur: Any, chemins: Iterable[str]) -> Any:
    """Ne garde d'un dict imbriqué que les feuilles déclarées.

    Le segment `[]` traverse une liste : `lines[].description` conserve la
    description de CHAQUE ligne et rien d'autre. Une liste dont plus aucune
    feuille n'est déclarée disparaît, plutôt que de laisser une liste de
    dictionnaires vides — un `[{}, {}, {}]` dans une charge utile divulgue
    encore le NOMBRE de lignes."""
    directes = {c for c in chemins if "." not in c and not c.endswith("[]")}
    resultat: dict[str, Any] = {}
    if not isinstance(valeur, dict):
        return resultat

    for clef in directes:
        if clef in valeur:
            resultat[clef] = valeur[clef]

    enfants: dict[str, list[str]] = {}
    listes: dict[str, list[str]] = {}
    for chemin in chemins:
        if "." not in chemin:
            continue
        tete, reste = chemin.split(".", 1)
        if tete.endswith("[]"):
            listes.setdefault(tete[:-2], []).append(reste)
        else:
            enfants.setdefault(tete, []).append(reste)

    for clef, sous_chemins in enfants.items():
        sous = _prune(valeur.get(clef), sous_chemins)
        if sous:
            resultat[clef] = sous

    for clef, sous_chemins in listes.items():
        elements = valeur.get(clef)
        if not isinstance(elements, list):
            continue
        elagues = [_prune(element, sous_chemins) for element in elements]
        if any(elagues):
            resultat[clef] = elagues

    return resultat


def project_document(document_code: str, object_id: UUID | str) -> dict[str, Any] | None:
    """Projette une pièce en dictionnaire, ÉLAGUÉ aux champs émis.

    La double barrière annoncée en tête de module : le `builder` du module
    décide ce qu'il produit, l'élagage décide ce qui sort. Un `builder`
    distrait qui ajouterait la marge ne la fait pas sortir — et la garde
    `tests/architecture/test_outbound_field_governance.py` le vérifie en
    lui faisant justement produire un champ interdit.

    Rend `None` quand le document n'est pas déclaré ou que la pièce est
    introuvable : l'appelant décide alors (le hub retombe sur la charge
    brute de l'événement, cf. `flows.services.triggers.body_for`)."""
    document = _DOCUMENTS.get(document_code)
    if document is None:
        return None
    identifiant = object_id if isinstance(object_id, UUID) else UUID(str(object_id))
    brut = document.builder(identifiant)
    if brut is None:
        return None
    elague: dict[str, Any] = _prune(brut, document.emitted_paths)
    return elague


__all__ = [
    "ALL_OPERATIONS",
    "CATEGORIES",
    "CATEGORY_AUDIT_TRAIL",
    "CATEGORY_COMMERCIAL_DOCUMENT",
    "CATEGORY_PARTY_IDENTITY",
    "CATEGORY_PAYROLL",
    "CATEGORY_PRODUCTION",
    "CATEGORY_SETTLEMENT",
    "MOTIF_MINIMUM",
    "OPERATION_CODES",
    "DataCategory",
    "OutboundDocument",
    "OutboundField",
    "SourceFieldRefusedError",
    "get_outbound_document",
    "list_outbound_documents",
    "outbound_document_codes",
    "project_document",
    "register_outbound_document",
    "validate_source_path",
]
