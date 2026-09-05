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
exposition brute de donnees individuelles a un LLM.

**`read_only` est declare, pas devine (L2-1)** : jusqu'a ce lot, la
distinction lecture/ecriture n'etait materialisee nulle part. Les huit
tools etaient en lecture, mais rien de mecanique ne le disait — et une
analyse statique du corps de la fonction ne l'aurait pas etabli, chacune
deleguant a un import local qu'il aurait fallu suivre. Le champ est donc
OBLIGATOIRE a l'enregistrement, et la garde
`tests/architecture/test_ai_tools_are_read_only.py` refuse tout tool
declarant `read_only=False` ainsi que tout `required_permission` qui ne
commence pas par `<app>.view_`. Un invariant declare se verifie ; un
invariant suppose se contredit en silence.

**Ecart assume (Sprint 11, L7 IA gateway)** : l'isolation garantie
aujourd'hui par ce registre est UNIQUEMENT applicative — liste blanche de
tools + `required_permission` filtre par `user.has_perm()` avant meme
d'offrir le catalogue au LLM (cf. plus haut). Le processus Django qui
execute ces tools tourne cependant sous le MEME role de base Postgres que
le reste de l'application (`widehalo_app`, cf. `apps.core.management.
commands.apply_rls`) — il n'existe PAS de role Postgres dedie, moindre
privilege (sans droit DDL/ecriture), reserve au chemin d'appel IA. Le
critere d'acceptation du CDC "aucun droit DDL/ecriture cote role DB de
l'IA" n'est donc PAS satisfait au niveau du role DB lui-meme, seulement au
niveau fonctionnel (le LLM n'a jamais d'acces SQL/ORM direct, seulement
des fonctions de lecture agregee deja testees). Provisionner un role
Postgres dedie (CREATE ROLE + GRANT SELECT uniquement, applique au
deploiement) est un travail d'infra/ops hors perimetre de ce sprint, qui
reste un ecart honnetement documente plutot qu'un correctif simule."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Une fonction de tool recoit le tenant courant et les arguments DEJA
# valides contre `parameters_schema` (validation faite par l'appelant,
# `apps.ai.services.data_query_gateway.ask`, jamais par ce registre) et
# renvoie soit une liste de lignes tabulaires (meme forme que les fonctions
# de `services/reports.py` qu'elle enveloppe), soit un dict unique pour un
# tool non tabulaire (ex. `apps.simulation.services.ai_data_query_
# registration`, qui renvoie un jeu d'indicateurs) — l'appelant
# (`apps.ai.services.data_query_gateway.ask`) se contente de serialiser le
# resultat en JSON (`json.dumps(rows, default=str)`), sans distinguer les
# deux formes — jamais un appel LLM a l'interieur de cette fonction.
DataQueryToolFunction = Callable[..., list[dict[str, Any]] | dict[str, Any]]


@dataclass(frozen=True)
class DataQueryTool:
    code: str
    module: str
    label: str
    description: str
    parameters_schema: dict[str, Any]
    required_permission: str
    # Invariant du cahier (IA-1) : le copilote lit, il n'ecrit jamais. Champ
    # obligatoire plutot que defaut a True — un defaut permissif laisserait
    # un futur tool d'ecriture passer par simple oubli.
    read_only: bool
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
    read_only: bool,
    function: DataQueryToolFunction,
) -> None:
    """Appele depuis `apps.py::ready()` de chaque module metier. Idempotent
    (un meme `code` re-enregistre remplace simplement l'entree).

    `read_only` n'a pas de valeur par defaut : le declarer est le seul moyen
    de rendre l'invariant IA-1 verifiable, et un defaut a True le rendrait
    verifiable sans etre vrai."""
    if not read_only:
        raise ValueError(
            f"Tool {code!r} : le copilote ne dispose que de tools en lecture "
            "(cahier IA-1). Un tool d'ecriture ne peut pas etre enregistre ici."
        )
    _REGISTRY[code] = DataQueryTool(
        code=code,
        module=module,
        label=label,
        description=description,
        parameters_schema=parameters_schema,
        required_permission=required_permission,
        read_only=read_only,
        function=function,
    )


def get_data_query_tool(code: str) -> DataQueryTool | None:
    return _REGISTRY.get(code)


def list_data_query_tools() -> list[DataQueryTool]:
    return sorted(_REGISTRY.values(), key=lambda t: t.code)


def registry_size() -> int:  # pragma: no cover - utilitaire de diagnostic
    return len(_REGISTRY)
