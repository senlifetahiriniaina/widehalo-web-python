"""Moteur de requête guidé (cahier Phase 2 §13.1, BI-2/BI-6/BI-10) — SEULE
voie d'exécution d'un `BiReport` : ne lit jamais `BiReport.definition`
comme autre chose qu'une liste de codes déjà déclarés (indicateurs du
dictionnaire gouverné `apps.analytics.AnMetricDefinition`, axes abstraits
listés dans son `axes_autorises`) — aucun champ de ce module n'évalue
jamais une chaîne comme une expression, un lookup ORM ou du SQL. Le calcul
réel (traduction axe abstrait -> champ ORM, agrégation) est délégué à
`apps.analytics.services.public.aggregate_fact`/`detail_fact` (`bi` ne
doit jamais importer `apps.analytics.models` directement, règle de
couplage n°1) via `services/metric_computers.py::METRIC_FACTS`.

**BI-6 (droits appliqués AVANT agrégation, anti "fuite par agrégat")** :
chaque indicateur non autorisé pour le rôle courant est retiré du rapport
AVANT tout calcul (jamais calculé puis masqué) ; chaque axe qui dépasse la
"maille minimale" déclarée par l'indicateur est retiré du regroupement
AVANT l'agrégation (jamais recalculé à partir d'un détail déjà transmis au
client). Le rapport reste utilisable, seulement plus large que la version
demandée — jamais une erreur — et `scope_notes` explique exactement ce qui
a été retiré (cf. cahier §13.1 : "le périmètre s'adapte au rôle du
lecteur... l'interface l'indique")."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.analytics.services.public import aggregate_fact, detail_fact, get_metric_definition

if TYPE_CHECKING:
    from apps.bi.models import BiReport
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User


def _user_role_codes(user: User) -> set[str]:
    return set(user.groups.values_list("name", flat=True))


def _is_metric_authorized(metric: dict[str, Any], user_roles: set[str]) -> bool:
    if metric["statut"] != "publie":
        return False
    if not metric["roles_autorises"]:
        return True
    return bool(user_roles.intersection(metric["roles_autorises"]))


def run_report(tenant: Tenant, report: BiReport, user: User) -> dict[str, Any]:
    """Exécute `report.definition` pour `user` — retourne
    ``{"metrics": {code: {"libelle", "unite", "rows"}}, "scope_notes": [str, ...]}``.
    **Plus rien n'est écarté en silence (L8).** Un indicateur inconnu, non
    calculable (aucun `fait_source`) ou dont le fait ne renvoie rien est
    désormais annoncé dans `scope_notes`, comme l'étaient déjà les
    restrictions de rôle et de maille. L'asymétrie d'avant L8 était le
    défaut : `drill_down` ci-dessous répondait « Indicateur non calculable »
    quand `run_report`, sur la même condition, faisait disparaître la ligne
    du rapport. Un tableau de bord auquel il manque un indicateur sans
    qu'un mot l'explique se lit comme un tableau de bord complet."""
    definition = report.definition or {}
    requested_dimensions: list[str] = definition.get("dimensions", [])
    requested_filters: list[dict[str, Any]] = definition.get("filters", [])
    user_roles = _user_role_codes(user)

    metrics_out: dict[str, Any] = {}
    scope_notes: list[str] = []

    for code in definition.get("metric_codes", []):
        metric = get_metric_definition(tenant, code)
        if metric is None:
            scope_notes.append(
                f"« {code} » introuvable au dictionnaire d'indicateurs — rien à afficher."
            )
            continue
        if not _is_metric_authorized(metric, user_roles):
            scope_notes.append(f"« {metric['libelle']} » masqué : non autorisé pour votre rôle.")
            continue
        # L8 : le fait vient du dictionnaire lui-meme, plus d'une table de
        # correspondance figee dans le code — un indicateur cree a
        # l'execution est desormais calculable sans deploiement.
        fact = metric.get("fait_source") or ""
        if not fact:
            scope_notes.append(
                f"« {metric['libelle']} » non calculable : aucun fait de l'entrepôt ne lui "
                "est rattaché."
            )
            continue

        allowed_axes = set(metric["axes_autorises"])
        dims = [d for d in requested_dimensions if d in allowed_axes]
        dropped_unauthorized = [d for d in requested_dimensions if d not in allowed_axes]
        for dropped in dropped_unauthorized:
            scope_notes.append(
                f"« {metric['libelle']} » : ventilation par « {dropped} » non autorisée."
            )

        maille = metric.get("maille_minimale") or ""
        if maille and maille in dims:
            dims = [d for d in dims if d != maille]
            scope_notes.append(
                f"« {metric['libelle']} » : ventilation par « {maille} » masquée (maille minimale)."
            )

        rows = aggregate_fact(tenant, fact=fact, dimensions=dims, filters=requested_filters)
        if rows is None:
            scope_notes.append(
                f"« {metric['libelle']} » : le fait « {fact} » n'a pas pu être agrégé "
                "(fait inconnu de l'entrepôt ou filtre invalide)."
            )
            continue
        metrics_out[code] = {"libelle": metric["libelle"], "unite": metric["unite"], "rows": rows}

    return {"metrics": metrics_out, "scope_notes": scope_notes}


def drill_down(
    tenant: Tenant,
    report: BiReport,
    user: User,
    *,
    metric_code: str,
    cell_filters: list[dict[str, Any]],
    limit: int = 200,
) -> dict[str, Any]:
    """BI-10 : depuis une valeur agrégée, atteint les lignes qui la
    composent. `cell_filters` = les valeurs de dimension de la cellule
    cliquée (ex. ``[{"dimension": "temps", "op": "eq", "value": "2026-09-01"}]``).
    Retourne ``{"blocked": True, "reason": str}`` si la maille minimale de
    l'indicateur interdit tout accès au détail — jamais un résultat
    partiel silencieux (cahier : "le blocage éventuel est expliqué")."""
    metric = get_metric_definition(tenant, metric_code)
    if metric is None or not _is_metric_authorized(metric, _user_role_codes(user)):
        return {"blocked": True, "reason": "Indicateur non autorisé pour votre rôle."}
    fact = metric.get("fait_source") or ""
    if not fact:
        return {"blocked": True, "reason": "Indicateur non calculable."}
    if metric.get("maille_minimale"):
        return {
            "blocked": True,
            "reason": (
                f"Détail non accessible : cet indicateur est limité à la maille "
                f"« {metric['maille_minimale']} »."
            ),
        }

    rows = detail_fact(tenant, fact=fact, filters=cell_filters, limit=limit)
    return {"blocked": False, "rows": rows or []}
