"""Dictionnaire d'indicateurs gouverné (cahier Phase 2 §12) — enregistrement
et consultation d'`AnMetricDefinition`. SEULE voie déclarée d'accès aux
indicateurs décisionnels : le futur moteur de requête guidé du module BI
(§13.1) doit toujours passer par `list_metrics_for_user`, jamais composer
sa propre agrégation en dehors de ce catalogue."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.analytics.models import AnMetricDefinition
from apps.analytics.services.fact_specs import FACT_SPECS

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User


def available_facts() -> list[dict[str, Any]]:
    """Faits de l'entrepôt réellement interrogeables, et leurs axes.

    Primitives uniquement : c'est ce qu'un écran de création d'indicateur
    doit proposer, et ce contre quoi `register_metric` valide. La liste est
    dérivée de `FACT_SPECS` et jamais recopiée — un fait ajouté à
    l'entrepôt devient immédiatement proposable, un fait retiré cesse de
    l'être, sans seconde source de vérité à tenir à jour."""
    return [
        {"code": code, "axes": sorted(spec.dimension_fields)}
        for code, spec in sorted(FACT_SPECS.items())
    ]


def _validate_fact_and_axes(fait_source: str, axes_autorises: list[str]) -> None:
    """Refuse un fait inconnu, et un axe que ce fait ne sait pas produire.

    Lève plutôt que d'ignorer : un indicateur enregistré avec un axe
    fantôme se comporterait comme calculable jusqu'au moment où un
    utilisateur demanderait cette ventilation, et la perdrait alors en
    silence — exactement le genre d'écart que ce dépôt paie cher."""
    if not fait_source:
        return
    spec = FACT_SPECS.get(fait_source)
    if spec is None:
        raise ValidationError(
            _("Fait inconnu : %(fait)s. Faits disponibles : %(disponibles)s.")
            % {"fait": fait_source, "disponibles": ", ".join(sorted(FACT_SPECS))}
        )
    unknown = [axis for axis in axes_autorises if axis not in spec.dimension_fields]
    if unknown:
        raise ValidationError(
            _(
                "Axe(s) impossible(s) pour le fait %(fait)s : %(axes)s. "
                "Axes disponibles : %(disponibles)s."
            )
            % {
                "fait": fait_source,
                "axes": ", ".join(sorted(unknown)),
                "disponibles": ", ".join(sorted(spec.dimension_fields)),
            }
        )


@transaction.atomic
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
    fait_source: str = "",
) -> AnMetricDefinition:
    """Crée ou fait évoluer (par `code`) une entrée du dictionnaire —
    idempotent au sens "même appelant, mêmes valeurs, appelable sans
    risque à chaque démarrage" (même patron que `apps.core.services.
    data_query_tool_registry.register_data_query_tool`), mais chaque appel
    dont les valeurs diffèrent de la version courante INSÈRE une nouvelle
    ligne `version+1` plutôt que d'écraser la précédente (BI-9, cf.
    docstring du modèle) — la ligne précédente reste en base, `is_current`
    bascule atomiquement de l'une à l'autre.

    **`fait_source` (L8)** : le fait de l'entrepôt sur lequel l'indicateur
    se calcule. Validé ICI contre `services/fact_specs.py`, et
    `axes_autorises` validé contre les axes de ce fait — un indicateur ne
    peut pas déclarer une ventilation que son fait ne sait pas produire.
    C'est ce qui rend un indicateur créé à l'exécution réellement
    calculable, là où la correspondance vivait auparavant dans un
    dictionnaire Python figé (`bi.services.metric_computers.METRIC_FACTS`)
    et exigeait un déploiement.

    `fait_source` vide reste permis : un indicateur purement descriptif est
    un état légitime du dictionnaire. Il n'est simplement pas calculable —
    et `bi` le SIGNALE désormais au lieu de l'écarter en silence."""
    _validate_fact_and_axes(fait_source, axes_autorises or [])
    current = AnMetricDefinition.objects.filter(tenant=tenant, code=code, is_current=True).first()
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
        "fait_source": fait_source,
    }
    if current is None:
        return AnMetricDefinition.objects.create(tenant=tenant, code=code, version=1, **defaults)
    if all(getattr(current, field) == value for field, value in defaults.items()):
        return current
    current.is_current = False
    current.save(update_fields=["is_current"])
    return AnMetricDefinition.objects.create(
        tenant=tenant, code=code, version=current.version + 1, **defaults
    )


def list_metric_history(tenant: Tenant, code: str) -> list[AnMetricDefinition]:
    """Toutes les versions d'un indicateur, la plus récente en premier
    (BI-9 : « conserve la précédente ») — y compris la version courante."""
    return list(AnMetricDefinition.objects.filter(tenant=tenant, code=code).order_by("-version"))


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
        tenant=tenant, statut=AnMetricDefinition.STATUT_PUBLIE, is_current=True
    ).order_by("module_source", "code")
    return [
        metric
        for metric in metrics
        if not metric.roles_autorises or user_roles.intersection(metric.roles_autorises)
    ]
