"""Chargement du plan comptable PCG 2005 malgache — jeu de donnees
REPRESENTATIF et SIMPLIFIE (pas exhaustif), a valider par un
expert-comptable membre de l'OECFM avant toute utilisation en production
(exigence explicite du cahier des charges, § 5.1.6). Modifiable par le
tenant apres chargement : ajout de sous-comptes, desactivation de comptes
inutilises.

Depuis l'etape A9 (Phase 2), la fixture porte aussi des valeurs par defaut
POUR `is_current` (ACC-BIL, §1.10.1 du document annexe) et
`functional_destination` (ACC-CR-FN1, §1.10.2) — ces deux mappings sont
EGALEMENT non valides par un expert-comptable OECFM, au meme titre que le
reste du plan comptable :
- `is_current` : False uniquement pour les immobilisations (classe 2) et les
  capitaux propres/dettes long terme (classe 1) — structurellement non
  courants au sens des criteres Art. 131-3 a 131-11. True par defaut
  partout ailleurs (creances, dettes, tresorerie, taxes, stocks classe 3),
  coherent avec le fait que ce sont les elements du cycle d'exploitation
  normal de l'entreprise.
- `functional_destination` : renseigne uniquement sur les comptes de charge
  (classe 6) — matieres premieres -> `production` (matiere transformee),
  achats de marchandises/transport -> `distribution` (cout de revient
  commercial), le reste (loyers, frais bancaires, impots, personnel,
  dotations aux amortissements) -> `administration` par defaut faute d'une
  cle de ventilation plus fine en V1 (ex. la masse salariale de production
  vs administrative n'est pas encore distinguee analytiquement) ; `autre`
  n'est utilise pour aucun compte de la fixture V1. Ce choix « tout ce qui
  n'est pas clairement production/distribution va en administration » est
  une simplification assumee, a affiner avec un vrai expert-comptable."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.utils.translation import gettext as _

from apps.accounting.models import AccAccount
from apps.core.models.tenant import Tenant

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "pcg2005_mg.json"

# Compte d'attente ("suspense") du chantier RG-QUALIF — classe 47x
# ("Comptes transitoires ou d'attente" du PCG 2005), absent de la fixture
# pcg2005_mg.json actuelle (comptes reels uniquement) : cree a la demande,
# jamais dans le chargement initial du plan comptable, pour ne pas
# polluer un plan comptable qui n'a jamais eu besoin d'un import
# "degrade" avec identification incertaine.
SUSPENSE_ACCOUNT_CODE = "471"


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
            is_current=entry.get("is_current", True),
            functional_destination=entry.get("functional_destination", ""),
        )
        created += 1

    return created


def ensure_suspense_account(tenant: Tenant) -> AccAccount:
    """Cree, s'il n'existe pas encore, LE compte d'attente (`is_placeholder
    =True`, code `471`, classe 47x) de ce tenant — idempotent par code,
    meme discipline que `load_pcg2005`. Utilise par
    `apps.accounting.services.cash_journal_import`/`invoice_import` quand
    un compte reel n'a pas pu etre identifie avec certitude (chantier
    RG-QUALIF) : plutot que de bloquer la ligne (`COMPTE_INCONNU`
    devenait non-defaultable auparavant), un `AccMove` brouillon est
    materialise immediatement sur ce compte, marque `needs_qualification`."""
    existing = AccAccount.objects.filter(tenant=tenant, code=SUSPENSE_ACCOUNT_CODE).first()
    if existing is not None:
        return existing
    return AccAccount.objects.create(
        tenant=tenant,
        code=SUSPENSE_ACCOUNT_CODE,
        name=str(_("Compte d'attente (à qualifier)")),
        account_class=4,
        type=AccAccount.TYPE_ASSET,
        is_placeholder=True,
    )
