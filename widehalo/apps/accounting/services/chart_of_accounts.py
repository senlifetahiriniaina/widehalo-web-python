"""Chargement du plan comptable PCG 2005 malgache — jeu de donnees
REPRESENTATIF et SIMPLIFIE (pas exhaustif), a valider par un
expert-comptable membre de l'OECFM avant toute utilisation en production
(exigence explicite du cahier des charges, § 5.1.6). Modifiable par le
tenant apres chargement : ajout de sous-comptes, desactivation de comptes
inutilises."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.accounting.models import AccAccount
from apps.core.models.tenant import Tenant

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "pcg2005_mg.json"


def _read_fixture() -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return data


def load_pcg2005(tenant: Tenant) -> int:
    """Cree les comptes du plan PCG 2005 pour ce tenant. Idempotent : un
    compte dont le code existe deja pour ce tenant n'est pas recree."""
    existing_codes = set(AccAccount.objects.filter(tenant=tenant).values_list("code", flat=True))

    created = 0
    for entry in _read_fixture():
        if entry["code"] in existing_codes:
            continue
        AccAccount.objects.create(
            tenant=tenant,
            code=entry["code"],
            name=entry["name"],
            account_class=entry["account_class"],
            type=entry["type"],
        )
        created += 1

    return created
