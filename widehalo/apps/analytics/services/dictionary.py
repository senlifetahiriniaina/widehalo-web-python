"""Dictionnaire d'indicateurs gouverné (cahier Phase 2 §12) — enregistrement
et consultation d'`AnMetricDefinition`. SEULE voie déclarée d'accès aux
indicateurs décisionnels : le futur moteur de requête guidé du module BI
(§13.1) doit toujours passer par `list_metrics_for_user`, jamais composer
sa propre agrégation en dehors de ce catalogue."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.analytics.models import AnMetricDefinition

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User


def register_metric(
    tenant: Tenant,
    *,
    code: str,
    libelle: str,
    module_source: str,
    description: str = "",
    formule: str = "",
    unite: str = "",
    axes_autorises: list[str] | None = None,
    roles_autorises: list[str] | None = None,
    maille_minimale: str = "",
    proprietaire: User | None = None,
    statut: str = AnMetricDefinition.STATUT_BROUILLON,
    date_effet: Any = None,
) -> AnMetricDefinition:
    """Crée ou met à jour (par `code`) une entrée du dictionnaire —
    idempotent, appelable depuis `apps.py::ready()` d'un module consommateur
    (même patron que `apps.core.services.data_query_tool_registry.
    register_data_query_tool`) ou depuis une commande de chargement initiale.
    Toute mise à jour incrémente `version` (cf. docstring du modèle : pas de
    préservation de l'historique des formules dans cette itération)."""
    existing = AnMetricDefinition.objects.filter(tenant=tenant, code=code).first()
    defaults = {
        "libelle": libelle,
        "module_source": module_source,
        "description": description,
        "formule": formule,
        "unite": unite,
        "axes_autorises": axes_autorises or [],
        "roles_autorises": roles_autorises or [],
        "maille_minimale": maille_minimale,
        "proprietaire": proprietaire,
        "statut": statut,
        "date_effet": date_effet,
    }
    if existing is None:
        return AnMetricDefinition.objects.create(tenant=tenant, code=code, **defaults)
    for field, value in defaults.items():
        setattr(existing, field, value)
    existing.version += 1
    existing.save()
    return existing


def list_metrics_for_user(tenant: Tenant, user: User) -> list[AnMetricDefinition]:
    """Filtre le catalogue publié par les rôles réels de `user` — garde-fou
    N2/N3 anti "fuite par agrégat" (cf. docstring de module) : un
    indicateur dont `roles_autorises` ne recoupe aucun des groupes de
    l'utilisateur n'est jamais renvoyé, même en lecture seule. Un
    indicateur sans `roles_autorises` déclaré (liste vide) est considéré
    ouvert à tout utilisateur authentifié — même discipline "liste
    blanche vide = pas de restriction déclarée" que `data_query_tool_
    registry`."""
    user_roles = set(user.groups.values_list("name", flat=True))
    metrics = AnMetricDefinition.objects.filter(
        tenant=tenant, statut=AnMetricDefinition.STATUT_PUBLIE
    ).order_by("module_source", "code")
    return [
        metric
        for metric in metrics
        if not metric.roles_autorises or user_roles.intersection(metric.roles_autorises)
    ]
