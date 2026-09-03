"""Construction, verrouillage et suivi budgétaire (cahier §13.3,
STR-3/STR-4/STR-5/STR-6)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.db.models import Max
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.strategy.models import StgBudget

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User

_ALLOWED_AXIS_TYPES = {"famille", "point_vente", "compte"}


def line_key(axis_type: str, axis_value: str, period: Any) -> str:
    """Clé stable d'une ligne de budget — référencée par `variance_
    comments` (STR-6, « rattaché à la ligne »)."""
    period_str = period.isoformat() if hasattr(period, "isoformat") else str(period)
    return f"{axis_type}:{axis_value}:{period_str}"


def _validate_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    validated = []
    for line in lines:
        if line.get("axis_type") not in _ALLOWED_AXIS_TYPES:
            raise ValidationError(
                _("Axe de budget inconnu : %(axis)s") % {"axis": line.get("axis_type")}
            )
        period = line["period"]
        period_str = period.isoformat() if hasattr(period, "isoformat") else str(period)
        validated.append(
            {
                "axis_type": line["axis_type"],
                "axis_value": str(line["axis_value"]),
                "metric_code": line.get("metric_code", ""),
                "period": period_str,
                "budgeted_value": str(Decimal(str(line["budgeted_value"]))),
            }
        )
    return validated


def create_budget(
    tenant: Tenant,
    *,
    name: str,
    period_start: Any,
    period_end: Any,
    lines: list[dict[str, Any]],
    created_by: User | None = None,
    source_type: str = StgBudget.SOURCE_MANUAL,
    source_reference: dict[str, Any] | None = None,
) -> StgBudget:
    budget = StgBudget(
        tenant=tenant,
        name=name,
        period_start=period_start,
        period_end=period_end,
        source_type=source_type,
        source_reference=source_reference or {},
        lines=_validate_lines(lines),
        created_by=created_by,
        updated_by=created_by,
    )
    budget.full_clean()
    budget.save()
    return budget


def create_budget_from_simulation_scenario(
    tenant: Tenant,
    *,
    scenario_id: str,
    name: str,
    period_start: Any,
    period_end: Any,
    created_by: User | None = None,
) -> StgBudget:
    """STR-4 : « conservation de la référence et de la version de la
    source. » **Simplification assumée et disclosée** : les indicateurs
    d'un `SimScenario` (`computed_indicators`, vocabulaire interne au
    moteur de simulation) ne portent pas de `metric_code` du dictionnaire
    gouverné — les lignes générées ici ont donc `metric_code=""` tant
    qu'un mappage explicite n'est pas ajouté par révision (`compute_
    variance` les ignore alors, cf. sa docstring)."""
    from apps.simulation.services.public import get_scenario_summary

    summary = get_scenario_summary(scenario_id)
    if summary is None:
        raise ValidationError(
            _("Scénario de simulation introuvable : %(id)s") % {"id": scenario_id}
        )

    lines = [
        {
            "axis_type": "compte",
            "axis_value": indicator_code,
            "metric_code": "",
            "period": period_start,
            "budgeted_value": value,
        }
        for indicator_code, value in summary["indicators"].items()
        if isinstance(value, (int, float, str, Decimal))
    ]
    return create_budget(
        tenant,
        name=name,
        period_start=period_start,
        period_end=period_end,
        lines=lines,
        created_by=created_by,
        source_type=StgBudget.SOURCE_SIMULATION,
        source_reference={"scenario_id": str(scenario_id), "scenario_name": summary["name"]},
    )


def create_budget_from_forecast_publication(
    tenant: Tenant, *, name: str, created_by: User | None = None
) -> StgBudget:
    """STR-4 : source = la DERNIÈRE prévision publiée (FOR-10, cahier
    §13.2) — référence et version conservées dans `source_reference`."""
    from apps.forecast.services.public import get_latest_published_forecast

    publication = get_latest_published_forecast(tenant)
    if publication is None:
        raise ValidationError(_("Aucune prévision publiée disponible."))

    lines = [
        {
            "axis_type": (
                "compte" if entry["dimension_type"] == "canal" else entry["dimension_type"]
            ),
            "axis_value": entry["dimension_value"],
            "metric_code": "",
            "period": entry["period"],
            "budgeted_value": entry["value"],
        }
        for entry in publication["snapshot"]
    ]
    return create_budget(
        tenant,
        name=name,
        period_start=publication["period_start"],
        period_end=publication["period_end"],
        lines=lines,
        created_by=created_by,
        source_type=StgBudget.SOURCE_FORECAST,
        source_reference={
            "publication_version": publication["version"],
            "published_at": publication["published_at"].isoformat(),
        },
    )


def lock_budget(budget: StgBudget, *, user: User | None) -> StgBudget:
    """STR-3 : verrouille — immuable en base dès cet instant (trigger
    Postgres, cf. migration dédiée), aucun retour en arrière possible."""
    if budget.is_locked:
        raise ValidationError(_("Ce budget est déjà verrouillé."))
    budget.is_locked = True
    budget.locked_at = timezone.now()
    budget.locked_by = user
    budget.full_clean()
    budget.save(update_fields=["is_locked", "locked_at", "locked_by", "updated_at"])
    return budget


def revise_budget(
    budget: StgBudget, *, lines: list[dict[str, Any]], created_by: User | None = None
) -> StgBudget:
    """STR-3 : « une révision crée une version horodatée et l'ancienne
    reste consultable et comparable. » Ne modifie JAMAIS `budget` — insère
    toujours une nouvelle ligne, non verrouillée, `previous_version`
    pointant vers celle-ci."""
    last_version = (
        StgBudget.objects.filter(tenant=budget.tenant, name=budget.name).aggregate(
            m=Max("version")
        )["m"]
        or budget.version
    )
    new_budget = StgBudget(
        tenant=budget.tenant,
        name=budget.name,
        period_start=budget.period_start,
        period_end=budget.period_end,
        source_type=budget.source_type,
        source_reference=budget.source_reference,
        version=last_version + 1,
        previous_version=budget,
        lines=_validate_lines(lines),
        created_by=created_by,
        updated_by=created_by,
    )
    new_budget.full_clean()
    new_budget.save()
    return new_budget


def add_variance_comment(
    budget: StgBudget, *, line_key_value: str, text: str, user: User
) -> StgBudget:
    """STR-6 : commentaire de gestion RATTACHÉ À LA LIGNE — reste possible
    même sur un budget verrouillé (cf. docstring `models.py`/migration
    d'immuabilité : seuls les chiffres engagés sont figés)."""
    if not text.strip():
        raise ValidationError(_("Le commentaire de gestion est obligatoire."))
    known_keys = {
        line_key(line["axis_type"], line["axis_value"], line["period"]) for line in budget.lines
    }
    if line_key_value not in known_keys:
        raise ValidationError(_("Ligne de budget inconnue : %(key)s") % {"key": line_key_value})
    budget.variance_comments = [
        *budget.variance_comments,
        {
            "line_key": line_key_value,
            "author_id": str(user.id),
            "at": timezone.now().isoformat(),
            "text": text.strip(),
        },
    ]
    budget.save(update_fields=["variance_comments", "updated_at"])
    return budget


def compute_variance(
    tenant: Tenant, budget: StgBudget, *, user: User, threshold_pct: Decimal = Decimal(10)
) -> list[dict[str, Any]]:
    """STR-5 : « l'écart budget/réel est calculé sur la même définition
    d'indicateur que le réel. » Ne calcule un écart QUE pour les lignes
    dont `metric_code` est renseigné — la valeur réelle vient TOUJOURS de
    `bi.services.public.get_metric_current_value(tenant, metric_code,
    user)`, EXACTEMENT la même fonction que celle utilisée pour afficher
    ce même indicateur ailleurs (BI, résultats clés STR-1) : aucun autre
    chemin de calcul du « réel » n'existe dans ce module, ce qui garantit
    par construction l'identité de définition exigée par STR-5. Une ligne
    sans `metric_code` (budget initialisé depuis une simulation/prévision
    sans mappage explicite, cf. docstrings ci-dessus) est renvoyée avec
    `actual_value=None`, jamais un écart inventé."""
    from apps.bi.services.public import get_metric_current_value

    results = []
    for line in budget.lines:
        key = line_key(line["axis_type"], line["axis_value"], line["period"])
        comments = [c for c in budget.variance_comments if c["line_key"] == key]
        budgeted = Decimal(line["budgeted_value"])
        actual = (
            get_metric_current_value(tenant, line["metric_code"], user)
            if line["metric_code"]
            else None
        )
        variance_value = actual - budgeted if actual is not None else None
        variance_pct = (
            (variance_value / budgeted * 100) if actual is not None and budgeted != 0 else None
        )
        exceeds_threshold = variance_pct is not None and abs(variance_pct) > threshold_pct
        results.append(
            {
                "line_key": key,
                "axis_type": line["axis_type"],
                "axis_value": line["axis_value"],
                "period": line["period"],
                "metric_code": line["metric_code"],
                "budgeted_value": budgeted,
                "actual_value": actual,
                "variance_value": variance_value,
                "variance_pct": variance_pct,
                "exceeds_threshold": exceeds_threshold,
                "has_comment": bool(comments),
                "comments": comments,
            }
        )
    return results


def can_close_review(variance_rows: list[dict[str, Any]]) -> bool:
    """STR-6 : la revue ne peut être clôturée tant qu'un écart au-delà du
    seuil n'a pas de commentaire de gestion."""
    return all(row["has_comment"] for row in variance_rows if row["exceeds_threshold"])


def _str_or_none(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def serialize_variance_row(row: dict[str, Any]) -> dict[str, Any]:
    """Convertit les `Decimal`/`None` d'une ligne `compute_variance` en
    primitives sérialisables (API JSON, `StgReviewPack.snapshot`) — un seul
    endroit pour cette conversion, réutilisé par `api.py` et `services/
    review_pack.py`."""
    return {
        **row,
        "budgeted_value": str(row["budgeted_value"]),
        "actual_value": _str_or_none(row["actual_value"]),
        "variance_value": _str_or_none(row["variance_value"]),
        "variance_pct": _str_or_none(row["variance_pct"]),
    }
