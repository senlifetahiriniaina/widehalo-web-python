"""Contrat public de l'app `forecast` — seule surface que les autres apps
métier (`strategy`, cahier Phase 2 §13.3, STR-4 : « un budget peut être
initialisé depuis... une prévision publiée, avec conservation de la
référence et de la version de la source » ; `simulation`, Phase 1 §13.6,
FOR-10) ont le droit d'importer (cf. tests/architecture/
test_module_boundaries.py).

**FOR-10, périmètre couvert dans ce lot** : ce module rend la dernière
prévision publiée DISPONIBLE (version, date, valeurs) via `get_latest_
publication` — la consommation côté écran `simulation` (proposer cette
publication comme point de départ d'un nouveau scénario) est disclosée
comme un chantier de suivi : modifier le moteur de scénarios déjà livré
et testé (`apps.simulation.services.baseline`/`scenarios`) pour y brancher
une source externe est une extension distincte, hors budget de ce
chantier-ci."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.forecast.services.publication import get_latest_publication

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant


def get_latest_published_forecast(tenant: Tenant) -> dict[str, Any] | None:
    """Primitives uniquement, jamais l'objet `ForPublication` (règle de
    couplage n°1). `None` si aucune prévision n'a encore été publiée."""
    publication = get_latest_publication(tenant)
    if publication is None:
        return None
    return {
        "version": publication.version,
        "published_at": publication.published_at,
        "period_start": publication.period_start,
        "period_end": publication.period_end,
        "snapshot": publication.snapshot,
    }
