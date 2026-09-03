"""Contrat public de l'app `analytics` — seule surface que les autres apps
métier (le futur module `bi`, cahier Phase 2 §13.1, au premier chef) ont le
droit d'importer (cf. tests/architecture/test_module_boundaries.py).
Aucun consommateur réel dans ce lot (fondations, cf. `module.py`) — même
discipline que `pos.services.public` à sa livraison initiale."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.analytics.models import AnMetricDefinition, AnWarehouseState
from apps.analytics.services.dictionary import list_metrics_for_user

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User


def get_warehouse_state(tenant: Tenant) -> dict[str, Any] | None:
    """État courant de l'entrepôt (verrou, dernier rafraîchissement réussi)
    — primitives uniquement, jamais l'objet `AnWarehouseState`. `None` si
    aucun rafraîchissement n'a encore jamais été lancé pour ce tenant."""
    state = AnWarehouseState.objects.filter(tenant=tenant).first()
    if state is None:
        return None
    return {
        "is_locked": state.is_locked,
        "last_successful_refresh_at": state.last_successful_refresh_at,
    }


def list_published_metrics(tenant: Tenant, user: User) -> list[dict[str, Any]]:
    """Dictionnaire d'indicateurs publiés et autorisés pour `user` (cf.
    `services/dictionary.py::list_metrics_for_user`) — primitives
    uniquement, jamais l'objet `AnMetricDefinition`."""
    return [
        {
            "code": metric.code,
            "libelle": metric.libelle,
            "unite": metric.unite,
            "module_source": metric.module_source,
            "axes_autorises": metric.axes_autorises,
            "maille_minimale": metric.maille_minimale,
        }
        for metric in list_metrics_for_user(tenant, user)
    ]


def get_metric_definition(tenant: Tenant, code: str) -> dict[str, Any] | None:
    """Détail d'un indicateur du dictionnaire (`None` si absent) — AUCUN
    filtrage par rôle ici (contrairement à `list_published_metrics`) :
    destiné à un appelant qui a déjà validé les droits de l'utilisateur
    courant (ex. le moteur de requête guidé du futur module BI, une fois
    l'indicateur choisi dans une liste déjà filtrée)."""
    metric = AnMetricDefinition.objects.filter(tenant=tenant, code=code).first()
    if metric is None:
        return None
    return {
        "code": metric.code,
        "libelle": metric.libelle,
        "description": metric.description,
        "formule": metric.formule,
        "unite": metric.unite,
        "module_source": metric.module_source,
        "axes_autorises": metric.axes_autorises,
        "roles_autorises": metric.roles_autorises,
        "maille_minimale": metric.maille_minimale,
        "statut": metric.statut,
        "version": metric.version,
    }
