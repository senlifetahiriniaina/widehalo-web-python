"""Contrat public de l'app `crm` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py)."""

from __future__ import annotations

from typing import Any

from apps.crm.models import CrmLead


def get_lead_reference(lead_id: Any) -> str:
    lead = CrmLead.objects.filter(id=lead_id).first()
    return lead.reference if lead is not None else ""
