"""AUTO3 (chantier Studio de workflow visuel) : enregistrement de l'action
`purchase` dans le registre partage `core.services.automation_registry`,
appele depuis `apps.py::ready()` — meme patron que
`apps.accounting.services.reports_registration`/
`apps.strategy.services.reports_registration`.

**Choix assume et disclosed** : `open_purchase_incident` (deja construit
pour ST3, cf. docstring `services/public.py`) est deja utilisee ELLE-MEME
comme une action automatique par un autre module
(`apps.stocks.services.measurements.record_measurement` l'appelle
automatiquement quand un ecart de mesure depasse un seuil parametre,
SANS intervention humaine) — precedent direct dans ce depot qu'ouvrir un
incident fournisseur declenche par un evenement est deja considere sur
comme "sans effet de bord dangereux" (cree un document `draft`, ne modifie
aucun etat financier/de stock existant, entierement reversible/annulable
par un humain ensuite)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.core.services.automation_registry import register_action


def _adapter_open_incident(tenant_id: str, params: dict[str, Any]) -> str:
    from apps.core.models.tenant import Tenant
    from apps.purchase.services.public import open_purchase_incident

    tenant = Tenant.objects.get(id=tenant_id)
    incident_id = open_purchase_incident(
        tenant=tenant,
        type=params.get("type", "autre"),
        partner_id=params["partner_id"],
        description=params.get("description", ""),
        impact=params.get("impact", ""),
        cost_mga=Decimal(str(params.get("cost_mga", 0))),
    )
    return str(incident_id)


def register_actions() -> None:
    register_action(
        code="purchase.open_incident",
        module="purchase",
        label="Ouvrir un incident fournisseur",
        function=_adapter_open_incident,
        param_schema={
            "partner_id": "Identifiant du fournisseur concerne",
            "type": "Type d'incident (optionnel)",
            "description": "Description de l'incident",
            "impact": "Impact constate (optionnel)",
            "cost_mga": "Cout estime en MGA (optionnel)",
        },
    )
