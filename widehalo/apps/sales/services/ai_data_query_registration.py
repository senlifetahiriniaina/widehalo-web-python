"""Passerelle IA locale d'analyse de donnees (GW3) : enregistrement des
tools `sales` dans le registre partage `core.services.data_query_tool_
registry`, appele depuis `apps.py::ready()` — meme patron exact que
`apps.sales.services.ai_context_registration`/`ai_anomaly_registration`/
`ai_insight_registration`. Chaque tool enveloppe une fonction DEJA
existante et testee de `apps.sales.services.reports` (SAL-CA/SAL-MARGE,
deja enregistrees dans `core.services.reports_registry` par `reports_
registration.py`), aucune reimplementation.

`required_permission` reprend EXACTEMENT le codename deja choisi pour ces
deux memes rapports dans `reports_registration.py::register_reports`
(`"sales.view_salesorder"`, cf. `SAL-CA`/`SAL-MARGE`) — coherence
deliberee : ce sont litteralement les memes rapports, exposes ici a un LLM
plutot qu'a un export PDF/CSV/XLSX, la granularite RBAC qui les protege ne
doit pas diverger selon le canal d'acces.

**`sales.margin_report` — demonstration exacte de l'exigence de securite du
cadrage (RG-SAL-5)** : `margin_report()` masque deja `margin_pct`/
`cost_estimate_mga` selon les roles de l'appelant (cf. sa docstring). Le
wrapper ci-dessous passe `user_role_codes(user)` de l'utilisateur REEL de
la requete en cours — jamais un role code en dur ni un ensemble elargi —
exactement comme le fait deja `_adapter_margin_report` de `reports_
registration.py` pour l'export classique."""

from __future__ import annotations

import datetime as dt
from typing import Any

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.data_query_tool_registry import register_data_query_tool
from apps.core.services.permissions import user_role_codes


def _tool_revenue_report(
    tenant: Tenant, user: User, *, date_from: str, date_to: str, group_by: str = "partner_id"
) -> list[dict[str, Any]]:
    from apps.sales.services.reports import revenue_report

    del tenant, user  # `revenue_report` n'est pas scope tenant explicitement
    # (TenantManager deja actif sur `SalesOrder.objects`, cf. sa docstring) —
    # signature uniforme `(tenant, user, **kwargs)` conservee pour tous les
    # tools de ce registre, meme si un tool donne n'en a pas besoin.
    return revenue_report(
        date_from=dt.date.fromisoformat(date_from),
        date_to=dt.date.fromisoformat(date_to),
        group_by=group_by,
    )


def _tool_margin_report(tenant: Tenant, user: User) -> list[dict[str, Any]]:
    from apps.sales.services.reports import margin_report

    del tenant  # meme raisonnement que ci-dessus (TenantManager deja actif)
    return margin_report(role_codes=user_role_codes(user))


def register_ai_data_query_tools() -> None:
    register_data_query_tool(
        "sales.revenue_report",
        module="sales",
        label="Chiffre d'affaires (SAL-CA)",
        description=(
            "Chiffre d'affaires des commandes de vente confirmees sur une periode donnee, "
            "groupe par client, commercial ou date. Utile pour repondre a des questions du "
            "type 'quel est le CA du mois dernier par client ?'."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "Date de debut, format AAAA-MM-JJ"},
                "date_to": {"type": "string", "description": "Date de fin, format AAAA-MM-JJ"},
                "group_by": {
                    "type": "string",
                    "enum": ["partner_id", "salesperson", "date"],
                    "description": "Dimension de regroupement (client, commercial ou date)",
                },
            },
            "required": ["date_from", "date_to"],
        },
        required_permission="sales.view_salesorder",
        function=_tool_revenue_report,
    )
    register_data_query_tool(
        "sales.margin_report",
        module="sales",
        label="Marge commerciale (SAL-MARGE)",
        description=(
            "Analyse de marge par ligne de commande de vente (marge en % et cout de revient "
            "estime). Ces deux champs ne sont renvoyes que si le role de l'utilisateur "
            "authentifie l'y autorise (RG-SAL-5) — ils peuvent etre absents des resultats."
        ),
        parameters_schema={"type": "object", "properties": {}, "required": []},
        required_permission="sales.view_salesorder",
        function=_tool_margin_report,
    )


__all__ = ["register_ai_data_query_tools"]
