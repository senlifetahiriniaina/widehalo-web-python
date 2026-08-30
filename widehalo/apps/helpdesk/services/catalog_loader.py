"""Chargement idempotent du catalogue de types de demandes/incidents
(`apps/helpdesk/fixtures/ticket_type_catalog.json`), cf. plan section
« Extension actee en cours de route ». Meme patron exact que
`apps.accounting.services.chart_of_accounts.load_pcg2005`/
`apps.strategy.services.*.load_textile_benchmarks` : idempotent PAR `code`
ET par tenant — jamais un doublon, jamais un ecrasement d'une
personnalisation deja faite par le tenant sur une entree existante (le
chargeur ne touche JAMAIS `label`/`sector_code`/... d'une ligne deja
presente, meme si la fixture a change depuis).

**Disclosure** (meme reserve que chaque fixture metier deja livree dans ce
depot, ex. `pcg2005_mg.json`) : catalogue de DEPART, point de depart
editable par chaque tenant — PAS une taxonomie sectorielle validee par un
expert metier.

`related_app_label`/`related_model` (jamais un id `ContentType` brut, qui
diffère par environnement) sont resolus a l'aide de `ContentType.objects.
get_by_natural_key()` — si le modele cible n'existe pas dans cet
environnement (app pas encore installee), la resolution est journalisee et
`related_content_type` reste `None`, jamais une exception qui bloquerait
tout le chargement."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from django.contrib.contenttypes.models import ContentType

from apps.core.models.tenant import Tenant
from apps.helpdesk.models import HlpTicketTypeCatalog

logger = logging.getLogger(__name__)

_FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "ticket_type_catalog.json"


def _read_fixture() -> list[dict[str, Any]]:
    with _FIXTURE_PATH.open(encoding="utf-8") as handle:
        entries: list[dict[str, Any]] = json.load(handle)
    return entries


def _resolve_content_type(entry: dict[str, Any]) -> ContentType | None:
    app_label = entry.get("related_app_label")
    model = entry.get("related_model")
    if not app_label or not model:
        return None
    try:
        return ContentType.objects.get_by_natural_key(app_label, model)
    except ContentType.DoesNotExist:
        logger.warning(
            "helpdesk.load_ticket_type_catalog: modele %s.%s introuvable dans cet "
            "environnement, related_content_type laisse a None pour le code %r.",
            app_label,
            model,
            entry.get("code"),
        )
        return None


def load_ticket_type_catalog(tenant: Tenant) -> int:
    """Cree les entrees du catalogue pour ce tenant. Idempotent : une entree
    dont le `code` existe deja pour ce tenant n'est ni recreee ni modifiee
    (personnalisation tenant preservee). Deux passes (types de tete puis
    sous-types) pour resoudre `parent` par `code`."""
    existing_codes = set(
        HlpTicketTypeCatalog.objects.filter(tenant=tenant).values_list("code", flat=True)
    )
    entries = _read_fixture()
    by_code: dict[str, HlpTicketTypeCatalog] = {
        obj.code: obj
        for obj in HlpTicketTypeCatalog.objects.filter(tenant=tenant, code__in=existing_codes)
    }

    created = 0
    # Premiere passe : entrees sans parent (types de tete) ou dont le
    # parent est deja resolu par le code source.
    for entry in entries:
        code = entry["code"]
        if code in existing_codes:
            continue
        if entry.get("parent_code"):
            continue
        obj = HlpTicketTypeCatalog.objects.create(
            tenant=tenant,
            kind=entry["kind"],
            code=code,
            label=entry["label"],
            sector_code=entry.get("sector_code", ""),
            related_module=entry.get("related_module", ""),
            related_content_type=_resolve_content_type(entry),
        )
        by_code[code] = obj
        created += 1

    # Deuxieme passe : sous-types, `parent` resolu via `by_code`.
    for entry in entries:
        code = entry["code"]
        if code in existing_codes:
            continue
        parent_code = entry.get("parent_code")
        if not parent_code:
            continue
        parent = by_code.get(parent_code)
        obj = HlpTicketTypeCatalog.objects.create(
            tenant=tenant,
            kind=entry["kind"],
            code=code,
            label=entry["label"],
            parent=parent,
            sector_code=entry.get("sector_code", ""),
            related_module=entry.get("related_module", ""),
            related_content_type=_resolve_content_type(entry),
        )
        by_code[code] = obj
        created += 1

    return created
