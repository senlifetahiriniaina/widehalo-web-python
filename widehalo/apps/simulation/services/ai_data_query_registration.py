"""GW3 (passerelle IA locale d'analyse de données) : enregistrement du tool
`simulation.propose_scenario` dans le registre partagé `core.services.
data_query_tool_registry` — même patron exact que `apps.sales.services.
ai_data_query_registration` (cf. sa docstring pour le détail de la
séparation des responsabilités RBAC : `required_permission` est vérifié
par l'appelant, `apps.ai.services.data_query_gateway.ask`, AVANT même
d'offrir ce tool au LLM — jamais dans la fonction ci-dessous).

**`paramétrer_simulation` (cahier §13.4, tableau des outils exposés en
Phase 1)** : « Traduit une question en langage naturel en un jeu de
leviers et le transmet au moteur de simulation. Ne calcule rien et ne
retourne aucun chiffre [au sens où le LLM ne produit jamais lui-même une
valeur] : le moteur déterministe produit les valeurs. » La traduction
langage naturel -> jeu de leviers est le travail du LLM lui-même (function
calling, hors périmètre de ce dépôt Django) ; ce tool se contente
d'EXÉCUTER le moteur déterministe sur les leviers proposés et de renvoyer
les indicateurs EN LECTURE SEULE — cf. `apps.simulation.services.public.
preview_indicators_for_levers`, dont la docstring précise qu'AUCUN
`SimScenario` n'est créé par cet appel. Un utilisateur humain qui souhaite
conserver cette proposition dans sa bibliothèque doit explicitement le
faire depuis l'écran (action authentifiée et permissionnée distincte,
`apps.simulation.services.scenarios.apply_ai_proposed_levers`), jamais
automatiquement déclenchée par l'appel de ce tool."""

from __future__ import annotations

from typing import Any

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.data_query_tool_registry import register_data_query_tool
from apps.simulation.levers import LEVER_CATALOG
from apps.simulation.services.public import preview_indicators_for_levers


def _tool_propose_scenario(tenant: Tenant, user: User, **lever_values: Any) -> dict[str, Any]:
    del user  # controle RBAC deja fait en amont (required_permission ci-dessous)
    result = preview_indicators_for_levers(tenant, levers=lever_values)
    if result is None:
        return {"error": "Aucun socle de simulation n'a encore été construit pour ce tenant."}
    return result


def register_ai_data_query_tools() -> None:
    lever_properties = {
        lever.code: {
            "type": "number",
            "description": (
                f"{lever.label}, en {lever.unit}, entre {lever.min_value} et {lever.max_value} "
                f"(0 = pas de changement vs référence, sauf tva_taux_override_pct où -1 = taux "
                f"de référence)."
            ),
        }
        for lever in LEVER_CATALOG
    }
    register_data_query_tool(
        "simulation.propose_scenario",
        module="simulation",
        label="Simulation financière — atelier de scénarios (SIM-8)",
        description=(
            "Calcule l'effet d'un jeu de leviers financiers (prix, volume, coûts, délais de "
            "règlement, TVA...) sur le chiffre d'affaires, la marge, le résultat et la "
            "trésorerie projetée à 13 semaines, à partir des données réelles du tenant. Le "
            "modèle propose les leviers correspondant à la question posée ('et si on baissait "
            "les prix de 5 % ?') ; seul le moteur déterministe calcule les valeurs. N'enregistre "
            "aucun scénario — calcul en lecture seule."
        ),
        parameters_schema={"type": "object", "properties": lever_properties, "required": []},
        required_permission="simulation.view_simscenario",
        function=_tool_propose_scenario,
    )


__all__ = ["register_ai_data_query_tools"]
