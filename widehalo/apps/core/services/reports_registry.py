"""Registre central des rapports (§5.11 RPT-2/RPT-5) — meme patron que
`apps.core.events` : chaque module metier s'auto-enregistre via son propre
`apps.py::ready()`, jamais un import direct par `reporting` des fonctions
`services/reports.py` de chaque module (regle de couplage n°1 — `reporting`
ne declare de dependance que sur `core`).

Un rapport enregistre porte au moins UN renderer (`render_pdf` et/ou
`render_rows`) — `render_rows` alimente XLSX/CSV/JSON via
`apps.reporting.services.engine::rows_to_bytes` (le moteur ne connait que
des `list[dict]`, jamais les modeles d'origine). Le registre est un simple
dictionnaire en memoire, peuple une fois au demarrage de Django (comme
`core.events._HANDLERS`) — jamais reinitialise en cours de vie du process."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.core.models.user import User

# Un renderer recoit les parametres bruts du rapport (deja valides cote
# appelant) et l'utilisateur demandeur (pour le scoping RBAC/N3 propre au
# module, ex. `sales.margin_report(role_codes=...)`).
RowsRenderer = Callable[[dict[str, Any], "User | None"], list[dict[str, Any]]]
PdfRenderer = Callable[[dict[str, Any], "User | None"], bytes]


@dataclass(frozen=True)
class RegisteredReport:
    code: str
    module: str
    label: str
    permission: str
    #: Le PROPRIETAIRE metier du rapport — le role qui repond de sa
    #: definition, pas celui qui a le droit de le lire (c'est
    #: `permission`). Les deux different souvent : un bulletin de paie se
    #: lit par les RH ET la direction, mais une seule fonction repond de ce
    #: qu'il contient.
    #:
    #: Sans proprietaire, la rationalisation d'un catalogue est
    #: impossible : « faut-il garder ce rapport ? » n'a pas de reponse si
    #: personne n'est designe pour la donner. C'est le volet que le cahier
    #: (Phase 2, sprint S6) nomme « catalogue avec domaine, description,
    #: proprietaire et indicateurs utilises », et dont seul le domaine
    #: existait — sous le nom de `module`.
    owner_role: str = ""
    #: Ce que le rapport MONTRE, en une phrase, et pour qui. Pas ce qu'il
    #: calcule : un inventaire sert a decider quoi garder, et « somme des
    #: lignes de mouvement groupees par article » ne permet a personne de
    #: trancher.
    description: str = ""
    render_pdf: PdfRenderer | None = None
    render_rows: RowsRenderer | None = None
    # Colonnes pour l'export XLSX/CSV — si vide, `engine.rows_to_bytes`
    # derive les colonnes des cles de la premiere ligne (rapports a colonnes
    # dynamiques, ex. patronage mesures par taille).
    fields: tuple[str, ...] = ()
    is_legal_document: bool = False

    def supports_pdf(self) -> bool:
        return self.render_pdf is not None

    def supports_rows(self) -> bool:
        return self.render_rows is not None


_REGISTRY: dict[str, RegisteredReport] = {}


def register_report(
    *,
    code: str,
    module: str,
    label: str,
    permission: str,
    owner_role: str,
    description: str,
    render_pdf: PdfRenderer | None = None,
    render_rows: RowsRenderer | None = None,
    fields: tuple[str, ...] = (),
    is_legal_document: bool = False,
) -> None:
    """Appele depuis `apps.py::ready()` de chaque module metier. Idempotent
    (un meme `code` re-enregistre remplace simplement l'entree — utile en
    reload de dev) mais exige au moins un renderer, jamais un rapport
    'fantome' inscrit au catalogue sans fonction reelle derriere."""
    if render_pdf is None and render_rows is None:
        raise ValueError(f"report {code!r}: au moins un renderer (pdf ou rows) est requis")
    # Le proprietaire et la description sont EXIGES a l'enregistrement, pas
    # verifies apres coup par un test. La difference compte : un test dit
    # « il en manque trois » a la fin de la construction, ce refus dit
    # « celui-ci » au moment ou on l'ecrit. Et un catalogue dont trois
    # entrees sur soixante-trois sont vides n'est plus un catalogue.
    if not owner_role:
        raise ValueError(
            f"report {code!r}: `owner_role` est requis — le role qui REPOND de la "
            "definition du rapport, pas celui qui a le droit de le lire. Sans lui, "
            "« faut-il garder ce rapport ? » n'a personne a qui etre posee."
        )
    if not description:
        raise ValueError(
            f"report {code!r}: `description` est requise — ce que le rapport MONTRE, "
            "en une phrase, et pour qui. Un inventaire sert a decider quoi garder, et "
            "un libelle de trois mots ne permet a personne de trancher."
        )
    _REGISTRY[code] = RegisteredReport(
        code=code,
        module=module,
        label=label,
        permission=permission,
        owner_role=owner_role,
        description=description,
        render_pdf=render_pdf,
        render_rows=render_rows,
        fields=fields,
        is_legal_document=is_legal_document,
    )


def get_registered_report(code: str) -> RegisteredReport | None:
    return _REGISTRY.get(code)


def list_registered_reports() -> list[RegisteredReport]:
    return sorted(_REGISTRY.values(), key=lambda r: r.code)


def registry_size() -> int:  # pragma: no cover - utilitaire de diagnostic
    return len(_REGISTRY)
