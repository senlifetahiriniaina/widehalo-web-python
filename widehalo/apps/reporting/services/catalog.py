"""Synchronisation du catalogue persiste (`RptDefinition`, miroir par tenant
du registre en memoire `core.services.reports_registry`) — cf. docstring
`apps/reporting/models.py`. Distinct de `services/public.py` : cette
fonction est appelee UNIQUEMENT depuis l'interieur de `reporting` (API/
ecrans de ce module), jamais par un autre module metier — `test_module_
boundaries.py::test_declared_dependencies_match_module_spec` traite tout
import `apps.<app>.services.public` comme une dependance externe declaree,
y compris quand `<app>` s'importe lui-meme ; ce garde-fou n'a donc de sens
que pour du code consomme PAR D'AUTRES apps, jamais pour un helper interne
— aucune autre app du projet n'importe sa propre `services.public` (verifie
par grep avant ce choix)."""

from __future__ import annotations

from apps.core.models.tenant import Tenant
from apps.core.services.reports_registry import list_registered_reports
from apps.reporting.models import RptDefinition


def sync_report_definitions(tenant: Tenant) -> int:
    """Idempotent : cree ou met a jour une `RptDefinition` par rapport
    enregistre, sans jamais toucher `is_enabled` d'une ligne deja existante
    (une desactivation manuelle par le tenant ne doit pas etre effacee par
    une resynchronisation ulterieure declenchee par un redemarrage)."""
    count = 0
    for report in list_registered_reports():
        RptDefinition.objects.update_or_create(
            tenant=tenant,
            code=report.code,
            defaults={
                "module": report.module,
                "label": report.label,
                "permission": report.permission,
                "supports_pdf": report.supports_pdf(),
                "supports_rows": report.supports_rows(),
                "is_legal_document": report.is_legal_document,
            },
        )
        count += 1
    return count
