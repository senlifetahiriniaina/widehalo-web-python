"""Registre central des tools de la passerelle IA locale d'analyse de
donnees (module `ai`, chantier "GW1-GW5") — 4e registre du depot, meme
patron exact que `apps.core.services.anomaly_registry`/`insight_source_
registry`/`advisor_rule_registry` : chaque module metier enregistre un
adaptateur MINCE vers une fonction de service DEJA testee et deja
existante (`services/reports.py` ou equivalent) via son propre
`apps.py::ready()` — `apps.ai` ne reimplemente JAMAIS de logique de calcul,
il se contente d'exposer un catalogue de tools au LLM et d'executer celui
que le LLM choisit.

**Le LLM n'a JAMAIS d'acces SQL/ORM direct** : il ne peut choisir qu'un
`code` de tool explicite parmi cette liste blanche, jamais un texte libre
execute (aucune generation de SQL, aucun acces direct a un modele Django
depuis le LLM).

**Trouvaille de securite actee au cadrage (disclosed, cf. plan)** : les
fonctions candidates (`apps.sales.services.reports.revenue_report`/
`margin_report`, `apps.stocks.services.reports.stock_state_rows`) sont de
simples fonctions de service — le controle RBAC (`require_permission`) vit
dans la couche VUE/API (`apps.sales.api`/`apps.stocks.api`), PAS dans la
fonction de service elle-meme. Appeler ces fonctions directement en
processus (contournant la couche vue) CONTOURNERAIT donc silencieusement
le RBAC si rien n'etait fait. **Correctif de conception** : chaque
`DataQueryTool` porte un `required_permission` explicite (ex.
`"sales.view_salesorder"`) ; l'appelant (`apps.ai.services.data_query_
gateway.ask`) DOIT filtrer `list_data_query_tools()` aux seuls tools dont
`user.has_perm(required_permission)` est vrai AVANT de presenter le
catalogue au LLM — un tool auquel l'utilisateur n'a pas droit n'est jamais
meme OFFERT (deny-by-default, meme philosophie que T6/le reste du RBAC de
ce depot), pas seulement bloque apres coup. Ce registre lui-meme ne fait
AUCUN filtrage : il se contente de porter la metadonnee, la responsabilite
du filtrage reste explicitement du cote appelant (meme separation exacte
que `RegisteredContext`/`ai_context_registry`, qui ne verifie pas non plus
de permission lui-meme).

**Regle de revue OBLIGATOIRE pour tout futur tool ajoute** : AUCUNE donnee
de paie nominative (IRSA/CNaPS/OSTIE, cf. `apps.payroll`) ni donnee de
presence individuelle (`apps.presence`) ne doit jamais etre enregistree
comme tool de ce registre dans son etat actuel — le premier lot de tools
(GW3) se limite deliberement a des rapports agreges `sales`/`stocks` deja
masques par role la ou necessaire (`margin_report`, RG-SAL-5). Un futur
module `payroll`/`presence` qui voudrait s'enregistrer ici DOIT documenter
explicitement, dans son propre adaptateur, comment il respecte le meme
niveau de masquage par role que son ecran/API existants — jamais une
exposition brute de donnees individuelles a un LLM."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Une fonction de tool recoit le tenant courant et les arguments DEJA
# valides contre `parameters_schema` (validation faite par l'appelant,
# `apps.ai.services.data_query_gateway.ask`, jamais par ce registre) et
# renvoie une liste de lignes tabulaires (meme forme que les fonctions de
# `services/reports.py` qu'elle enveloppe) — jamais un appel LLM a
# l'interieur de cette fonction.
DataQueryToolFunction = Callable[..., list[dict[str, Any]]]


@dataclass(frozen=True)
class DataQueryTool:
    code: str
    module: str
    label: str
    description: str
    parameters_schema: dict[str, Any]
    required_permission: str
    function: DataQueryToolFunction


_REGISTRY: dict[str, DataQueryTool] = {}


def register_data_query_tool(
    code: str,
    *,
    module: str,
    label: str,
    description: str,
    parameters_schema: dict[str, Any],
    required_permission: str,
    function: DataQueryToolFunction,
) -> None:
    """Appele depuis `apps.py::ready()` de chaque module metier. Idempotent
    (un meme `code` re-enregistre remplace simplement l'entree)."""
    _REGISTRY[code] = DataQueryTool(
        code=code,
        module=module,
        label=label,
        description=description,
        parameters_schema=parameters_schema,
        required_permission=required_permission,
        function=function,
    )


def get_data_query_tool(code: str) -> DataQueryTool | None:
    return _REGISTRY.get(code)


def list_data_query_tools() -> list[DataQueryTool]:
    return sorted(_REGISTRY.values(), key=lambda t: t.code)


def registry_size() -> int:  # pragma: no cover - utilitaire de diagnostic
    return len(_REGISTRY)
