"""S5 (Phase 4, bloc A) — correspondances de champs : FLX-6 et axe A2.

**Le critère, mot pour mot.** FLX-6 : « Une correspondance de champs
incomplète sur un champ déclaré obligatoire par le tiers est refusée à
l'enregistrement, avec désignation du champ manquant. » Et l'écran
« Éditeur de correspondance » : « Refuse à l'enregistrement toute
correspondance incomplète sur un champ obligatoire du tiers, **plutôt que
d'échouer au premier envoi** ».

C'est cette seconde moitié qui décide de l'architecture. Une correspondance
incomplète acceptée en base est une bombe à retardement : elle n'explose
qu'au premier échange réel, chez le tiers, sur une pièce d'un client, à un
moment où plus personne ne se souvient de l'avoir configurée. La validation
vit donc dans `save_mapping`, avant l'écriture, et jamais dans l'exécuteur.

**Le jeu de transformations est FERMÉ à six** (axe A2 : « format de date,
séparateur décimal, casse, concaténation, valeur constante, table de
correspondance de valeurs »). Même discipline que les six familles
d'erreur de S3, pour la même raison : une énumération qu'on peut allonger
sans que rien ne proteste redevient du texte libre en deux sprints. La
garde est `tests/architecture/test_flows_mapping_transformations.py`.

**Une contradiction du cahier, tranchée par le critère.** L'axe A2 s'ouvre
sur « Association un pour un entre champ source et champ cible » et se
ferme sur une liste de six transformations dont la CONCATÉNATION — qui est
par nature plusieurs-vers-un. Les deux ne peuvent pas être vraies ensemble.
La règle retenue sur ce chantier est que le critère l'emporte sur la prose :
la concaténation est donc supportée, et elle est la SEULE exception au
un-pour-un. Les cinq autres transformations refusent plus d'une source.

**Ce que la correspondance n'a pas le droit de faire**, et ce n'est pas un
détail de confort : « La correspondance de champs ne peut pas ajouter un
champ non déclaré nécessaire » (§ protection des données, ligne du tableau
« Identité et coordonnées de client »). Une règle qui vise un champ absent
du schéma déclaré est donc refusée elle aussi — c'est de la minimisation,
pas du pédantisme : le champ en trop part quand même chez le tiers.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.core.services.outbound_schemas import (
    SourceFieldRefusedError,
    get_outbound_document,
    validate_source_path,
)

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.flows.models import FlwLink, FlwMapping

# --- Le jeu fermé de six transformations (axe A2) -----------------------------

TRANSFORM_DATE_FORMAT = "format_date"
TRANSFORM_DECIMAL_SEPARATOR = "separateur_decimal"
TRANSFORM_CASE = "casse"
TRANSFORM_CONCATENATION = "concatenation"
TRANSFORM_CONSTANT = "valeur_constante"
TRANSFORM_LOOKUP_TABLE = "table_de_correspondance"

TRANSFORM_CHOICES: list[tuple[str, str]] = [
    (TRANSFORM_DATE_FORMAT, _("Format de date")),
    (TRANSFORM_DECIMAL_SEPARATOR, _("Séparateur décimal")),
    (TRANSFORM_CASE, _("Casse")),
    (TRANSFORM_CONCATENATION, _("Concaténation")),
    (TRANSFORM_CONSTANT, _("Valeur constante")),
    (TRANSFORM_LOOKUP_TABLE, _("Table de correspondance de valeurs")),
]

#: Le jeu fermé lui-même. Le RELEVER exige une décision explicite du
#: commanditaire, au même titre que les budgets de modèles et d'écrans.
KNOWN_TRANSFORMS: frozenset[str] = frozenset(code for code, _label in TRANSFORM_CHOICES)

#: La seule transformation plusieurs-vers-un (cf. docstring de module).
MULTI_SOURCE_TRANSFORMS: frozenset[str] = frozenset({TRANSFORM_CONCATENATION})

#: La seule transformation qui n'a besoin d'AUCUNE source : elle produit sa
#: valeur elle-même.
SOURCELESS_TRANSFORMS: frozenset[str] = frozenset({TRANSFORM_CONSTANT})

#: Paramètres exigés par transformation. Une transformation dont le
#: paramètre manque est invalide À L'ENREGISTREMENT — sans quoi elle
#: échouerait au premier envoi, ce que FLX-6 refuse explicitement.
REQUIRED_PARAMETERS: dict[str, tuple[str, ...]] = {
    TRANSFORM_DATE_FORMAT: ("format",),
    TRANSFORM_DECIMAL_SEPARATOR: ("separateur",),
    TRANSFORM_CASE: ("casse",),
    TRANSFORM_CONCATENATION: (),
    TRANSFORM_CONSTANT: ("valeur",),
    TRANSFORM_LOOKUP_TABLE: ("table",),
}

CASE_UPPER = "majuscules"
CASE_LOWER = "minuscules"
CASE_TITLE = "capitales_initiales"
KNOWN_CASES: frozenset[str] = frozenset({CASE_UPPER, CASE_LOWER, CASE_TITLE})


# --- Les problèmes, nommés ----------------------------------------------------

PROBLEM_MISSING_REQUIRED_FIELD = "champ_obligatoire_absent"
PROBLEM_UNKNOWN_TARGET_FIELD = "champ_cible_inconnu"
PROBLEM_UNKNOWN_TRANSFORM = "transformation_inconnue"
PROBLEM_NO_SOURCE = "source_absente"
PROBLEM_TOO_MANY_SOURCES = "sources_multiples_interdites"
PROBLEM_MISSING_PARAMETER = "parametre_absent"
PROBLEM_INVALID_PARAMETER = "parametre_invalide"
PROBLEM_EMPTY_SCHEMA = "schema_tiers_absent"
PROBLEM_UNDECLARED_SOURCE_DOCUMENT = "piece_source_non_declaree"
PROBLEM_REFUSED_SOURCE_FIELD = "champ_source_refuse"


@dataclass(frozen=True)
class MappingProblem:
    """Un défaut de correspondance, DÉSIGNANT SON CHAMP.

    Le champ n'est pas un ornement : FLX-6 exige « avec désignation du
    champ manquant ». Un refus qui dirait seulement « correspondance
    incomplète » obligerait l'utilisateur à comparer deux JSON à l'œil."""

    kind: str
    target_field: str
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.target_field} : {self.detail}" if self.detail else self.target_field


@dataclass
class MappingReport:
    problems: list[MappingProblem] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.problems

    @property
    def missing_required_fields(self) -> list[str]:
        """Les champs que FLX-6 nomme, et eux seuls."""
        return [
            problem.target_field
            for problem in self.problems
            if problem.kind == PROBLEM_MISSING_REQUIRED_FIELD
        ]

    def as_message(self) -> str:
        return " ; ".join(str(problem) for problem in self.problems)


# --- Validation (FLX-6) -------------------------------------------------------


def declared_fields(target_schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Les champs du schéma DÉCLARÉ par le tiers.

    Le schéma est stocké sur la correspondance plutôt que codé dans
    l'adaptateur : c'est ce qui permet à un tiers de faire évoluer son
    schéma sans livraison logicielle."""
    fields = target_schema.get("fields")
    return fields if isinstance(fields, dict) else {}


def required_field_names(target_schema: dict[str, Any]) -> list[str]:
    return [
        name
        for name, spec in declared_fields(target_schema).items()
        if isinstance(spec, dict) and spec.get("required")
    ]


def _params_of(rule: dict[str, Any]) -> dict[str, Any]:
    """Les paramètres d'une règle, toujours un dict — `None` et une valeur
    d'un autre type sont ramenés au dict vide plutôt que de propager un
    `None` que chaque appelant devrait retester."""
    params = rule.get("params")
    return params if isinstance(params, dict) else {}


def _sources_of(rule: dict[str, Any]) -> list[str]:
    if "sources" in rule:
        sources = rule.get("sources")
        return [str(s) for s in sources] if isinstance(sources, list) else []
    source = rule.get("source")
    return [str(source)] if source else []


def _source_problems(
    field_map: dict[str, Any], *, source_document: str, operations: Iterable[str]
) -> list[MappingProblem]:
    """Les refus dus à NOTRE schéma, jamais à celui du tiers.

    Le champ désigné dans le problème est le champ CIBLE — c'est celui que
    l'utilisateur voit dans l'éditeur de correspondance ; le chemin source
    fautif est dans le détail. Nommer la source en `target_field` obligerait
    à chercher quelle ligne de l'écran la porte."""
    if not source_document:
        return [
            MappingProblem(
                kind=PROBLEM_UNDECLARED_SOURCE_DOCUMENT,
                target_field="",
                detail=_(
                    "aucune pièce source déclarée : une correspondance se valide "
                    "contre notre schéma autant que contre celui du tiers"
                ),
            )
        ]
    if get_outbound_document(source_document) is None:
        return [
            MappingProblem(
                kind=PROBLEM_UNDECLARED_SOURCE_DOCUMENT,
                target_field="",
                detail=_(
                    "la pièce « %(code)s » n'est pas déclarée liable par son "
                    "module — rien de ce qu'elle porte ne peut sortir tant que "
                    "ce module n'a pas dit ce qui le peut"
                )
                % {"code": source_document},
            )
        ]

    problems: list[MappingProblem] = []
    for target_field, rule in field_map.items():
        if not isinstance(rule, dict):
            continue
        for chemin in _sources_of(rule):
            try:
                validate_source_path(source_document, chemin, operations=operations)
            except SourceFieldRefusedError as refus:
                problems.append(
                    MappingProblem(
                        kind=PROBLEM_REFUSED_SOURCE_FIELD,
                        target_field=target_field,
                        detail="; ".join(refus.messages),
                    )
                )
    return problems


def validate_mapping(
    field_map: dict[str, Any],
    target_schema: dict[str, Any],
    *,
    source_document: str = "",
    operations: Iterable[str] = (),
) -> MappingReport:
    """Confronte une correspondance aux DEUX schémas : celui du tiers et le
    nôtre.

    Ne lève jamais : elle RAPPORTE. C'est `save_mapping` qui refuse — un
    écran d'édition a besoin de montrer TOUS les problèmes d'un coup, pas
    de les découvrir un par un à chaque tentative d'enregistrement.

    **Le second schéma est arrivé avec T0, et il manquait.** Jusque-là
    cette fonction ne validait que contre `target_schema`, c'est-à-dire
    contre ce que le TIERS déclare attendre. Une correspondance pouvait
    donc désigner `lines[].margin_pct` en source : rien ne s'y opposait, et
    la marge partait au premier échange. Le §9.2 l'interdit — « marge,
    coût de revient, commentaires de gestion exclus par défaut de toute
    correspondance » — et c'est `apps.core.services.outbound_schemas` qui
    porte désormais la liste, module par module.

    `source_document` vide veut dire « aucune pièce source déclarée » : la
    correspondance est alors refusée en bloc. Deny-by-default assumé — une
    correspondance qu'on ne sait pas confronter à notre propre schéma est
    exactement celle qui laisse fuir."""
    report = MappingReport()
    fields = declared_fields(target_schema)
    report.problems.extend(
        _source_problems(field_map, source_document=source_document, operations=operations)
    )

    if not fields:
        # Une correspondance validée contre un schéma vide serait validée
        # contre rien. Le dire est plus honnête que de rendre « valide ».
        report.problems.append(
            MappingProblem(
                kind=PROBLEM_EMPTY_SCHEMA,
                target_field="",
                detail=_("le tiers n'a déclaré aucun champ : rien à valider"),
            )
        )
        return report

    for target_field in required_field_names(target_schema):
        if target_field not in field_map:
            report.problems.append(
                MappingProblem(
                    kind=PROBLEM_MISSING_REQUIRED_FIELD,
                    target_field=target_field,
                    detail=_("champ obligatoire du tiers sans correspondance"),
                )
            )

    for target_field, rule in field_map.items():
        if target_field not in fields:
            report.problems.append(
                MappingProblem(
                    kind=PROBLEM_UNKNOWN_TARGET_FIELD,
                    target_field=target_field,
                    detail=_("champ absent du schéma déclaré par le tiers"),
                )
            )
            continue
        report.problems.extend(_problems_of_rule(target_field, rule))

    return report


def _problems_of_rule(target_field: str, rule: Any) -> list[MappingProblem]:
    if not isinstance(rule, dict):
        return [
            MappingProblem(
                kind=PROBLEM_NO_SOURCE,
                target_field=target_field,
                detail=_("règle illisible : un objet est attendu"),
            )
        ]

    problems: list[MappingProblem] = []
    transform = rule.get("transform", "")
    sources = _sources_of(rule)
    params = _params_of(rule)

    if transform and transform not in KNOWN_TRANSFORMS:
        return [
            MappingProblem(
                kind=PROBLEM_UNKNOWN_TRANSFORM,
                target_field=target_field,
                detail=_("transformation '%(nom)s' hors du jeu fermé") % {"nom": transform},
            )
        ]

    if transform in SOURCELESS_TRANSFORMS:
        pass
    elif not sources:
        problems.append(
            MappingProblem(
                kind=PROBLEM_NO_SOURCE,
                target_field=target_field,
                detail=_("aucun champ source désigné"),
            )
        )
    elif len(sources) > 1 and transform not in MULTI_SOURCE_TRANSFORMS:
        problems.append(
            MappingProblem(
                kind=PROBLEM_TOO_MANY_SOURCES,
                target_field=target_field,
                detail=_("seule la concaténation accepte plusieurs sources"),
            )
        )

    for parametre in REQUIRED_PARAMETERS.get(transform, ()):
        if parametre not in params:
            problems.append(
                MappingProblem(
                    kind=PROBLEM_MISSING_PARAMETER,
                    target_field=target_field,
                    detail=_("paramètre '%(nom)s' manquant") % {"nom": parametre},
                )
            )

    if transform == TRANSFORM_CASE and params.get("casse") not in KNOWN_CASES:
        problems.append(
            MappingProblem(
                kind=PROBLEM_INVALID_PARAMETER,
                target_field=target_field,
                detail=_("casse inconnue : %(valeurs)s")
                % {"valeurs": ", ".join(sorted(KNOWN_CASES))},
            )
        )
    if transform == TRANSFORM_LOOKUP_TABLE and not isinstance(params.get("table"), dict):
        problems.append(
            MappingProblem(
                kind=PROBLEM_INVALID_PARAMETER,
                target_field=target_field,
                detail=_("la table de correspondance doit être un objet clef/valeur"),
            )
        )

    return problems


def save_mapping(
    tenant: Tenant,
    link: FlwLink,
    *,
    document_type: str,
    field_map: dict[str, Any],
    target_schema: dict[str, Any],
) -> FlwMapping:
    """LE point d'entrée de FLX-6 : enregistre, ou refuse en nommant le
    champ.

    Une `ValidationError`, jamais un booléen : un appelant qui ignore un
    booléen enregistre quand même. C'est le même choix que
    `attempt_transition` fait pour la permission.

    **`document_type` est aussi le code de la pièce source** — il vaut
    `app.Modele`, exactement ce que `workflow.transitioned` porte sous la
    clef `model`. C'est ce qui permet de retrouver le schéma déclaré par le
    module sans table de correspondance supplémentaire, et donc de
    confronter les CHEMINS SOURCES de la correspondance à ce que le module
    accepte de laisser sortir (§9.2).

    **Les opérations viennent du connecteur, pas de l'appelant.** La
    minimisation du §9.2 est « seuls les champs exigés par l'opération
    partent » : les opérations concernées sont celles que ce connecteur
    sait faire, puisque n'importe laquelle d'entre elles pourra emprunter
    cette correspondance. Les déduire ici plutôt que les demander évite
    qu'un appelant obtienne un champ personnel en déclarant l'opération qui
    l'arrange."""
    from apps.flows.models import FlwMapping

    report = validate_mapping(
        field_map,
        target_schema,
        source_document=document_type,
        operations=link.connector.supported_operations or (),
    )
    if not report.is_valid:
        raise ValidationError(
            _("Correspondance refusée — %(details)s") % {"details": report.as_message()}
        )

    mapping, _created = FlwMapping.objects.update_or_create(
        tenant=tenant,
        link=link,
        document_type=document_type,
        defaults={"field_map": field_map, "target_schema": target_schema},
    )
    return mapping


# --- Application (ce qui rend les six transformations autre chose qu'une liste)


class TransformationError(Exception):
    """La valeur source ne se laisse pas transformer.

    Distincte d'une correspondance invalide : celle-ci est refusée à
    l'enregistrement, celle-là ne se découvre qu'avec une donnée réelle
    (un texte là où une date est attendue). Elle appartient à la famille
    d'erreur `donnee_invalide` de S3, pas à une panne du tiers."""


def _apply_date_format(values: list[Any], params: dict[str, Any]) -> str:
    valeur = values[0]
    if isinstance(valeur, str):
        try:
            valeur = dt.date.fromisoformat(valeur)
        except ValueError as exc:
            raise TransformationError(
                _("'%(valeur)s' n'est pas une date lisible") % {"valeur": valeur}
            ) from exc
    if not isinstance(valeur, dt.date | dt.datetime):
        raise TransformationError(_("une date est attendue"))
    return valeur.strftime(str(params["format"]))


def _apply_decimal_separator(values: list[Any], params: dict[str, Any]) -> str:
    valeur = values[0]
    try:
        nombre = Decimal(str(valeur))
    except (InvalidOperation, ValueError) as exc:
        raise TransformationError(
            _("'%(valeur)s' n'est pas un nombre") % {"valeur": valeur}
        ) from exc
    return str(nombre).replace(".", str(params["separateur"]))


def _apply_case(values: list[Any], params: dict[str, Any]) -> str:
    texte = str(values[0])
    casse = params["casse"]
    if casse == CASE_UPPER:
        return texte.upper()
    if casse == CASE_LOWER:
        return texte.lower()
    return texte.title()


def _apply_concatenation(values: list[Any], params: dict[str, Any]) -> str:
    separateur = str(params.get("separateur", " "))
    return separateur.join(str(valeur) for valeur in values if valeur not in (None, ""))


def _apply_constant(_values: list[Any], params: dict[str, Any]) -> Any:
    return params["valeur"]


def _apply_lookup_table(values: list[Any], params: dict[str, Any]) -> Any:
    table = params["table"]
    clef = str(values[0])
    if clef not in table:
        if "defaut" in params:
            return params["defaut"]
        raise TransformationError(
            _("'%(clef)s' est absent de la table de correspondance") % {"clef": clef}
        )
    return table[clef]


#: Une implémentation par transformation, et la garde d'architecture vérifie
#: que ce dictionnaire et `KNOWN_TRANSFORMS` sont EXACTEMENT le même jeu —
#: une transformation déclarée sans implémentation serait acceptée à
#: l'enregistrement puis exploserait au premier envoi, ce que FLX-6 refuse.
TRANSFORMERS: dict[str, Callable[[list[Any], dict[str, Any]], Any]] = {
    TRANSFORM_DATE_FORMAT: _apply_date_format,
    TRANSFORM_DECIMAL_SEPARATOR: _apply_decimal_separator,
    TRANSFORM_CASE: _apply_case,
    TRANSFORM_CONCATENATION: _apply_concatenation,
    TRANSFORM_CONSTANT: _apply_constant,
    TRANSFORM_LOOKUP_TABLE: _apply_lookup_table,
}


def read_source(document: dict[str, Any], path: str) -> Any:
    """Lit `partner.tax_id` dans un dict imbriqué. `None` si le chemin
    n'aboutit pas — l'absence est traitée par l'appelant, jamais par une
    exception ici : un champ facultatif absent est un cas normal."""
    valeur: Any = document
    for segment in path.split("."):
        if not isinstance(valeur, dict) or segment not in valeur:
            return None
        valeur = valeur[segment]
    return valeur


def apply_mapping(field_map: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    """Produit la charge utile destinée au tiers.

    N'écrit RIEN et n'appelle personne : c'est une fonction pure sur des
    dicts. Un déclencheur peut donc la faire tourner sans mettre en péril
    la transition métier qui l'a réveillé (FLX-2).

    Un champ facultatif dont la source est absente n'est pas émis — plutôt
    qu'émis à vide. Envoyer une chaîne vide à un tiers, c'est affirmer que
    la valeur est vide ; ne rien envoyer, c'est dire qu'on ne la
    renseigne pas."""
    resultat: dict[str, Any] = {}
    for target_field, rule in field_map.items():
        if not isinstance(rule, dict):
            continue
        transform = rule.get("transform", "")
        sources = _sources_of(rule)
        params = _params_of(rule)
        values = [read_source(document, chemin) for chemin in sources]

        if transform not in SOURCELESS_TRANSFORMS and all(v is None for v in values):
            continue
        if not transform:
            resultat[target_field] = values[0]
            continue
        resultat[target_field] = TRANSFORMERS[transform](values, params)
    return resultat
