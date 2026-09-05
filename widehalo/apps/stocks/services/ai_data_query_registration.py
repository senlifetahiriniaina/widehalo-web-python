"""Passerelle IA locale d'analyse de donnees (GW3) : enregistrement du
tool `stocks.stock_state_rows` dans le registre partage `core.services.
data_query_tool_registry`, appele depuis `apps.py::ready()` — meme patron
exact que `apps.stocks.services.ai_context_registration`/`ai_anomaly_
registration`. Enveloppe `apps.stocks.services.reports.stock_state_rows`
(STK-ETAT, deja enregistre dans `core.services.reports_registry` par
`reports_registration.py`), aucune reimplementation.

`required_permission="stocks.view_stkmove"` reprend EXACTEMENT le codename
deja choisi pour ce meme rapport dans `reports_registration.py::register_
reports` (`STK-ETAT`) — meme raisonnement de coherence que `apps.sales.
services.ai_data_query_registration` : c'est litteralement le meme
rapport, expose ici a un LLM plutot qu'a un export, la granularite RBAC ne
doit pas diverger selon le canal d'acces."""

from __future__ import annotations

from typing import Any

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.data_query_tool_registry import register_data_query_tool


def _tool_stock_state_rows(tenant: Tenant, user: User) -> list[dict[str, Any]]:
    from apps.stocks.services.reports import stock_state_rows

    del user  # non utilise : le rapport n'est pas masque par role
    return stock_state_rows(tenant)


def register_ai_data_query_tools() -> None:
    register_data_query_tool(
        "stocks.stock_state_rows",
        module="stocks",
        label="Etat des stocks (STK-ETAT)",
        description=(
            "Etat de stock valorise par emplacement interne et variante (quantite et valeur "
            "MGA). Utile pour repondre a des questions du type 'quel est le stock disponible "
            "de tel produit ?' ou 'quelle est la valeur totale du stock ?'."
        ),
        parameters_schema={"type": "object", "properties": {}, "required": []},
        required_permission="stocks.view_stkmove",
        read_only=True,
        function=_tool_stock_state_rows,
    )


__all__ = ["register_ai_data_query_tools"]
