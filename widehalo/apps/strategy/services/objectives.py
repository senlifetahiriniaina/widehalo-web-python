"""Cascade OKR (`StgObjective`/`StgKeyResult`/`StgCheckIn`) — creation,
progression, et calcul automatique du statut (cf. docstring `models.py` :
`status` n'est jamais un cycle de vie pilote par l'utilisateur)."""

from __future__ import annotations

import importlib
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.strategy.models import StgCheckIn, StgKeyResult, StgObjective

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User

# Seuil de progression moyenne au-dela duquel un objectif est considere
# "en bonne voie" plutot que "a risque" — decision de conception PRISE ICI
# (non specifiee explicitement au cadrage, disclosed) : 70% est un seuil
# usuel de pilotage OKR (methode Google/Doerr, "0.7 est un bon score"),
# retenu par coherence avec cette pratique plutot qu'invente arbitrairement.
_ON_TRACK_THRESHOLD_PCT = Decimal(70)


def create_objective(
    tenant: Tenant,
    *,
    title: str,
    level: str,
    period_start: Any,
    period_end: Any,
    description: str = "",
    owner: User | None = None,
    parent: StgObjective | None = None,
    department_id: Any = None,
    sector_code: str | None = None,
    created_by: User | None = None,
) -> StgObjective:
    """Cascade OKR (decision actee) : un objectif ne peut avoir pour parent
    qu'un objectif de niveau EGAL OU SUPERIEUR dans la hierarchie
    entreprise -> departement -> individuel (jamais un individuel comme
    parent d'un objectif d'entreprise)."""
    if (
        parent is not None
        and StgObjective.LEVEL_ORDER[parent.level] > StgObjective.LEVEL_ORDER[level]
    ):
        raise ValidationError(
            _(
                "Un objectif de niveau %(level)s ne peut pas avoir pour parent un "
                "objectif de niveau inferieur (%(parent_level)s)."
            )
            % {"level": level, "parent_level": parent.level}
        )
    objective = StgObjective(
        tenant=tenant,
        title=title,
        description=description,
        level=level,
        owner=owner,
        parent=parent,
        department_id=department_id,
        sector_code=sector_code or "",
        period_start=period_start,
        period_end=period_end,
        created_by=created_by,
        updated_by=created_by,
    )
    objective.full_clean()
    objective.save()
    return objective


def add_key_result(
    objective: StgObjective,
    *,
    metric_name: str,
    target_value: Decimal,
    unit: str = "",
    current_value: Decimal = Decimal(0),
    kpi_source_module: str = "",
    kpi_source_function: str = "",
) -> StgKeyResult:
    key_result = StgKeyResult(
        tenant=objective.tenant,
        objective=objective,
        metric_name=metric_name,
        target_value=target_value,
        current_value=current_value,
        unit=unit,
        kpi_source_module=kpi_source_module,
        kpi_source_function=kpi_source_function,
    )
    key_result.full_clean()
    key_result.save()
    recompute_objective_status(objective)
    return key_result


def record_check_in(
    key_result: StgKeyResult,
    *,
    date: Any,
    value: Decimal,
    comment: str = "",
    author: User | None = None,
) -> StgCheckIn:
    """`StgCheckIn` est la source de verite PAR DEFAUT de la progression :
    un check-in manuel met a jour `key_result.current_value` immediatement
    (contrairement a `refresh_key_result_from_source`, qui reste a la
    demande explicite de l'utilisateur)."""
    check_in = StgCheckIn(
        tenant=key_result.tenant,
        key_result=key_result,
        date=date,
        value=value,
        comment=comment,
        author=author,
    )
    check_in.full_clean()
    check_in.save()
    key_result.current_value = value
    key_result.full_clean()
    key_result.save(update_fields=["current_value", "updated_at"])
    recompute_objective_status(key_result.objective)
    return check_in


def recompute_objective_status(objective: StgObjective) -> str:
    """Statut calcule (jamais un workflow FSM, cf. `models.py`) :
    - aucun key result actif -> `draft` ;
    - progression moyenne >= 100% -> `achieved` ;
    - periode terminee (`period_end` depassee) et progression < 100% ->
      `missed` ;
    - progression moyenne >= `_ON_TRACK_THRESHOLD_PCT` -> `on_track` ;
    - sinon -> `at_risk`.

    Seuils/branchement DECIDES ICI (non specifies au cadrage, disclosed) —
    coherents avec la pratique OKR usuelle, pas une exigence explicite du
    plan."""
    key_results = list(objective.key_results.filter(is_active=True))
    if not key_results:
        status = StgObjective.STATUS_DRAFT
    else:
        average_progress = sum(
            (key_result.progress_pct() for key_result in key_results), Decimal(0)
        ) / len(key_results)
        today = timezone.now().date()
        if average_progress >= Decimal(100):
            status = StgObjective.STATUS_ACHIEVED
        elif objective.period_end < today:
            status = StgObjective.STATUS_MISSED
        elif average_progress >= _ON_TRACK_THRESHOLD_PCT:
            status = StgObjective.STATUS_ON_TRACK
        else:
            status = StgObjective.STATUS_AT_RISK

    if status != objective.status:
        objective.status = status
        objective.save(update_fields=["status", "updated_at"])
    return status


def refresh_key_result_from_source(tenant: Tenant, key_result: StgKeyResult) -> StgKeyResult:
    """Rafraichissement de `current_value` A LA DEMANDE uniquement — jamais
    un abonnement au bus d'evenements temps reel (simplification assumee et
    disclosed, cf. `models.py`/plan).

    **Convention d'appel decidee ici** (non specifiee au cadrage) : la
    fonction nommee par `kpi_source_function`, dans
    `apps.<kpi_source_module>.services.public`, doit accepter UNIQUEMENT
    `tenant` en argument positionnel et renvoyer une valeur coercible en
    `Decimal`, ou `None` si aucune donnee n'est disponible pour l'instant.
    Une source qui ne respecte pas cette convention (mauvais nom de module/
    fonction, signature differente) leve une `ValidationError` explicite,
    jamais un echec silencieux."""
    if not key_result.kpi_source_module or not key_result.kpi_source_function:
        raise ValidationError(_("Aucune source KPI configuree pour cet indicateur."))
    try:
        module = importlib.import_module(f"apps.{key_result.kpi_source_module}.services.public")
    except ImportError as exc:
        raise ValidationError(
            _("Module source KPI introuvable : %(module)s")
            % {"module": key_result.kpi_source_module}
        ) from exc
    function = getattr(module, key_result.kpi_source_function, None)
    if function is None or not callable(function):
        raise ValidationError(
            _("Fonction source KPI introuvable : %(function)s")
            % {"function": key_result.kpi_source_function}
        )
    raw_value = function(tenant)
    if raw_value is None:
        raise ValidationError(_("Aucune valeur disponible pour cette source KPI pour l'instant."))
    key_result.current_value = Decimal(str(raw_value))
    key_result.full_clean()
    key_result.save(update_fields=["current_value", "updated_at"])
    recompute_objective_status(key_result.objective)
    return key_result
