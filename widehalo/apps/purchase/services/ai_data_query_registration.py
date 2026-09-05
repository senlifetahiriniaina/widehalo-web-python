"""INT2 : auto-enregistrement d'un tool `purchase` dans le registre partage
`core.services.data_query_tool_registry` (GW3), appele depuis
`apps.py::ready()` — meme patron exact que `apps.helpdesk.services.
ai_data_query_registration.register_ai_data_query_tools()` deja etabli
dans ce chantier (`_tool_*(tenant, user, **kwargs)`).

**`purchase.supplier_risk_scores`** : enveloppe DIRECTEMENT le gap deja
mutualise RG-PUR-8 (`apps.mrp.services.public.get_supplier_score`, deja
consomme par `purchase` depuis PU7, cf. `services/evaluation.py`) —
AUCUN nouveau calcul de score n'est introduit ici. Le tool se contente de
resoudre l'ensemble des fournisseurs REELLEMENT rattaches au tenant
courant (les `partner_id` distincts des `PurOrder` actifs non annules) et
d'exposer leur dernier score connu, optionnellement filtre sous un seuil
de risque — utile pour repondre a « quels fournisseurs sont a risque en ce
moment ? » sans jamais donner au LLM un acces direct a
`MrpSupplierEvaluation`/l'ORM. `required_permission="purchase.view_
purorder"` — meme permission auto-generee Django que celle qui gate deja
la lecture des commandes d'achat (RBAC app-level)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.data_query_tool_registry import register_data_query_tool


def _tool_supplier_risk_scores(
    tenant: Tenant, user: User, *, risk_threshold: float | None = None
) -> list[dict[str, Any]]:
    del user  # RBAC deja applique en amont par le filtrage `required_permission`
    from apps.mrp.services.public import get_supplier_score
    from apps.purchase.models import PurOrder

    partner_ids = (
        PurOrder.objects.filter(tenant=tenant, is_active=True)
        .exclude(state=PurOrder.STATE_CANCELLED)
        .values_list("partner_id", flat=True)
        .distinct()
    )

    threshold = Decimal(str(risk_threshold)) if risk_threshold is not None else None

    rows: list[dict[str, Any]] = []
    for partner_id in partner_ids:
        score = get_supplier_score(partner_id)
        if score is None:
            continue
        if threshold is not None and score > threshold:
            continue
        rows.append({"partner_id": str(partner_id), "weighted_score": str(score)})

    return rows


def register_ai_data_query_tools() -> None:
    register_data_query_tool(
        "purchase.supplier_risk_scores",
        module="purchase",
        label="Score de risque fournisseur (evaluation QQCD)",
        description=(
            "Dernier score d'evaluation fournisseur connu (RG-PUR-8, note ponderee "
            "sur 100) pour chaque fournisseur ayant au moins une commande d'achat "
            "active, optionnellement filtre sous un seuil de risque. Utile pour "
            "repondre a des questions du type 'quels fournisseurs sont a risque ?'."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "risk_threshold": {
                    "type": "number",
                    "description": (
                        "Ne renvoyer que les fournisseurs dont le score est "
                        "inferieur ou egal a ce seuil (optionnel)."
                    ),
                },
            },
            "required": [],
        },
        required_permission="purchase.view_purorder",
        read_only=True,
        function=_tool_supplier_risk_scores,
    )


__all__ = ["register_ai_data_query_tools"]
