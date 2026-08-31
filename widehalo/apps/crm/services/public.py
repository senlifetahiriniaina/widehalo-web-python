"""Contrat public de l'app `crm` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.core.models.tenant import Tenant
from apps.crm.models import CrmLead, CrmLeadLine


def get_lead_reference(lead_id: Any) -> str:
    lead = CrmLead.objects.filter(id=lead_id).first()
    return lead.reference if lead is not None else ""


def pipeline_weighted_demand(
    tenant: Tenant, *, date_from: Any = None, date_to: Any = None
) -> dict[str, Decimal]:
    """RG-SAL-7 (composante "pipeline CRM pondere par la probabilite
    d'etape", cf. plan sous-sequencement `sales` S6) : demande ponderee
    actuelle du pipeline commercial, par variante.

    Formule (simple et explicable, RG-SAL-8) : pour chaque ligne
    d'opportunite ouverte (`stage.is_won=False` et `stage.is_lost=False` —
    une opportunite gagnee est deja devenue une vraie commande via
    `RG-CRM-4`, une opportunite perdue ne genere plus de demande),
    `qty_pondere = ligne.qty * lead.probability / 100`, sommee par
    `variant_id`.

    `date_from`/`date_to` sont acceptes mais delibererement ignores : le
    CDC ne definit aucun champ de date "periode couverte" sur une ligne
    d'opportunite (seul `CrmLead.expected_close_date`, nullable, existe au
    niveau du lead, pas de la ligne) — filtrer dessus exclurait
    silencieusement les leads sans date de cloture prevue, ce qui
    fausserait plus le signal qu'il ne l'affinerait. Le choix retenu :
    remonter le pipeline pondere COURANT (tel qu'il existe au moment de
    l'appel), a charge de l'appelant (`sales.services.forecast.
    build_forecast`) de le traiter comme une estimation instantanee du
    "carnet en cours", pas comme un decoupage par periode precis — coherent
    avec RG-SAL-8 (explicabilite plutot que precision).

    Les lignes hors-catalogue (`variant_id` nul) sont ignorees : une
    ligne "sur mesure"/personnalisee ne peut alimenter aucune prevision
    par produit. Ne leve jamais d'exception ; retourne `{}` si le
    pipeline du tenant est vide."""
    del date_from, date_to  # cf. docstring — pas de champ de date exploitable par ligne.

    lines = CrmLeadLine.objects.filter(
        lead__tenant=tenant,
        lead__stage__is_won=False,
        lead__stage__is_lost=False,
        variant_id__isnull=False,
    ).select_related("lead")

    weighted: dict[str, Decimal] = {}
    for line in lines:
        key = str(line.variant_id)
        contribution = line.qty * Decimal(line.lead.probability) / Decimal(100)
        weighted[key] = weighted.get(key, Decimal(0)) + contribution
    return weighted


def count_open_opportunities() -> int:
    """Nombre d'opportunites CRM ni gagnees ni perdues (`stage.is_won`/
    `is_lost` tous deux faux) pour le tenant courant — deja tenant-scope
    par `CrmLead.objects` (RLS), aucun parametre `tenant` necessaire.
    Utilise par le tableau de bord transversal (chantier UX6)."""
    return CrmLead.objects.filter(stage__is_won=False, stage__is_lost=False).count()
