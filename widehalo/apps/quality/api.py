"""API django-ninja du module `quality` (HACCP, Phase 3 Bloc D) — L11.

**Ce que ce fichier repare.** Le module etait livre complet et teste — plans
de controle, points critiques, mesures, non-conformites, dossiers de rappel,
alerte de controle en retard — et **inatteignable** : ni `views.py`, ni
`urls.py`, ni `api.py`, donc aucun montage dans `config/urls.py` ni
`config/api.py`, et pas une seule entree dans `rbac_policy.py` (omission
alors documentee comme volontaire, « a reviser le jour ou le module sera
monte »). Un utilisateur ne pouvait declarer aucun rappel de lot. C'est
l'ecart §3.4 de l'audit.

**Aucune logique metier ici.** Chaque endpoint delegue a
`apps.quality.services.public`, deja teste — c'est la meme discipline que
partout dans ce depot : l'API est une surface, jamais un second lieu de
regles. En particulier, le refus de liberer un lot sous non-conformite
ouverte reste porte par `release_lot_hold`, jamais re-verifie ici.

NOTE ordre des decorateurs (cf. `apps.core.services.permissions.
require_permission`) : `@router.xxx` DOIT rester le decorateur EXTERNE et
`@require_permission(...)` l'INTERNE (juste au-dessus de `def`).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.core.models.user import User
from apps.core.services.permissions import require_permission
from apps.core.views.tenant_web import resolve_tenant
from apps.quality.models import (
    QltControlPlan,
    QltCriticalPoint,
    QltMeasurement,
    QltNonConformity,
    QltRecallDossier,
)
from apps.quality.services import public as quality_public

router = Router(tags=["quality"])


def _error_response(exc: Exception) -> JsonResponse:
    message = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
    return JsonResponse({"detail": message}, status=400)


# ---------------------------------------------------------------------------
# Schemas d'entree
# ---------------------------------------------------------------------------


class ControlPlanIn(Schema):
    name: str
    frequency_days: int = 0
    notes: str = ""


class CriticalPointIn(Schema):
    name: str
    unit: str = ""
    limit_min: Decimal | None = None
    limit_max: Decimal | None = None
    sequence: int = 0


class MeasurementIn(Schema):
    value: Decimal
    lot_variant_id: str | None = None
    lot_name: str = ""
    measured_at: dt.datetime | None = None


class NonConformityIn(Schema):
    description: str
    lot_variant_id: str | None = None
    lot_name: str = ""


class CloseIn(Schema):
    closing_reason: str


class LotReleaseIn(Schema):
    lot_variant_id: str
    lot_name: str
    reason: str


class RecallIn(Schema):
    lot_variant_id: str
    lot_name: str
    reason: str


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _serialize_plan(plan: QltControlPlan) -> dict[str, Any]:
    return {
        "id": str(plan.id),
        "name": plan.name,
        "frequency_days": plan.frequency_days,
        "notes": plan.notes,
        "is_active": plan.is_active,
        "critical_points": [_serialize_point(p) for p in plan.critical_points.all()],
    }


def _serialize_point(point: QltCriticalPoint) -> dict[str, Any]:
    return {
        "id": str(point.id),
        "control_plan_id": str(point.control_plan_id),
        "name": point.name,
        "unit": point.unit,
        "limit_min": str(point.limit_min) if point.limit_min is not None else None,
        "limit_max": str(point.limit_max) if point.limit_max is not None else None,
        "sequence": point.sequence,
    }


def _serialize_measurement(measurement: QltMeasurement) -> dict[str, Any]:
    return {
        "id": str(measurement.id),
        "critical_point_id": str(measurement.critical_point_id),
        "value": str(measurement.value),
        # Champ DERIVE, jamais assigne par un appelant (cf. `QltMeasurement`) :
        # expose en lecture seule, comme il est calcule.
        "is_within_limits": measurement.is_within_limits,
        "lot_variant_id": str(measurement.lot_variant_id) if measurement.lot_variant_id else None,
        "lot_name": measurement.lot_name,
        "measured_at": measurement.measured_at.isoformat(),
    }


def _serialize_non_conformity(non_conformity: QltNonConformity) -> dict[str, Any]:
    return {
        "id": str(non_conformity.id),
        "reference": non_conformity.reference,
        "state": non_conformity.state,
        "description": non_conformity.description,
        "measurement_id": (
            str(non_conformity.measurement_id) if non_conformity.measurement_id else None
        ),
        "lot_variant_id": (
            str(non_conformity.lot_variant_id) if non_conformity.lot_variant_id else None
        ),
        "lot_name": non_conformity.lot_name,
        "opened_at": non_conformity.opened_at.isoformat(),
        "closed_at": non_conformity.closed_at.isoformat() if non_conformity.closed_at else None,
        "closing_reason": non_conformity.closing_reason,
    }


def _serialize_recall(dossier: QltRecallDossier) -> dict[str, Any]:
    return {
        "id": str(dossier.id),
        "reference": dossier.reference,
        "state": dossier.state,
        "reason": dossier.reason,
        "lot_variant_id": str(dossier.lot_variant_id) if dossier.lot_variant_id else None,
        "lot_name": dossier.lot_name,
        # Perimetre FIGE a la declaration, jamais recalcule (cf.
        # `QltRecallDossier`) — c'est ce qui en fait une preuve.
        "impacted_lots": dossier.impacted_lots,
        "initiated_at": dossier.initiated_at.isoformat(),
        "closed_at": dossier.closed_at.isoformat() if dossier.closed_at else None,
        "closing_reason": dossier.closing_reason,
    }


# ---------------------------------------------------------------------------
# Plans de controle et points critiques
# ---------------------------------------------------------------------------


@router.get("/quality/control-plans")
@require_permission("quality.view_qltcontrolplan")
def list_control_plans(request: Any) -> dict[str, Any]:
    tenant = resolve_tenant(request)
    plans = (
        QltControlPlan.objects.filter(tenant=tenant, is_active=True)
        .prefetch_related("critical_points")
        .order_by("name")
    )
    return {"results": [_serialize_plan(plan) for plan in plans]}


@router.post("/quality/control-plans")
@require_permission("quality.add_qltcontrolplan")
def create_control_plan(request: Any, payload: ControlPlanIn) -> Any:
    tenant = resolve_tenant(request)
    try:
        plan = quality_public.create_control_plan(
            tenant=tenant,
            name=payload.name,
            frequency_days=payload.frequency_days,
            notes=payload.notes,
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_plan(plan)


@router.post("/quality/control-plans/{plan_id}/critical-points")
@require_permission("quality.add_qltcriticalpoint")
def add_critical_point(request: Any, plan_id: str, payload: CriticalPointIn) -> Any:
    tenant = resolve_tenant(request)
    plan = get_object_or_404(QltControlPlan, id=plan_id, tenant=tenant)
    try:
        point = quality_public.add_critical_point(
            plan,
            name=payload.name,
            unit=payload.unit,
            limit_min=payload.limit_min,
            limit_max=payload.limit_max,
            sequence=payload.sequence,
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_point(point)


@router.post("/quality/critical-points/{point_id}/measurements")
@require_permission("quality.add_qltmeasurement")
def record_measurement(request: Any, point_id: str, payload: MeasurementIn) -> Any:
    """Une mesure hors limites ouvre une non-conformite ET bloque le lot,
    dans la meme transaction (QUA-1/2/3). L'endpoint ne decide rien de tout
    cela : c'est `services.public.record_measurement` qui le porte."""
    tenant = resolve_tenant(request)
    point = get_object_or_404(QltCriticalPoint, id=point_id, control_plan__tenant=tenant)
    user = request.auth
    assert isinstance(user, User)
    try:
        measurement = quality_public.record_measurement(
            point,
            tenant=tenant,
            value=payload.value,
            measured_by=user,
            lot_variant_id=payload.lot_variant_id or None,
            lot_name=payload.lot_name,
            measured_at=payload.measured_at,
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_measurement(measurement)


@router.get("/quality/overdue-controls")
@require_permission("quality.view_qltcontrolplan")
def list_overdue_controls(request: Any) -> dict[str, Any]:
    """QUA-9 : lots dont le controle est du ou en retard.

    LECTURE PURE — n'envoie aucune notification, contrairement a la commande
    periodique `run_quality_control_checks` qui, elle, notifie. Consulter
    l'ecran ne doit pas declencher d'alerte."""
    tenant = resolve_tenant(request)
    return {"results": quality_public.check_overdue_controls(tenant=tenant)}


# ---------------------------------------------------------------------------
# Non-conformites
# ---------------------------------------------------------------------------


@router.get("/quality/non-conformities")
@require_permission("quality.view_qltnonconformity")
def list_non_conformities(request: Any, state: str | None = None) -> dict[str, Any]:
    tenant = resolve_tenant(request)
    queryset = QltNonConformity.objects.filter(tenant=tenant)
    if state:
        queryset = queryset.filter(state=state)
    return {
        "results": [_serialize_non_conformity(nc) for nc in queryset.order_by("-opened_at")],
    }


@router.post("/quality/non-conformities")
@require_permission("quality.add_qltnonconformity")
def create_non_conformity(request: Any, payload: NonConformityIn) -> Any:
    tenant = resolve_tenant(request)
    user = request.auth
    assert isinstance(user, User)
    try:
        non_conformity = quality_public.create_non_conformity(
            tenant=tenant,
            opened_by=user,
            description=payload.description,
            lot_variant_id=payload.lot_variant_id or None,
            lot_name=payload.lot_name,
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_non_conformity(non_conformity)


@router.post("/quality/non-conformities/{non_conformity_id}/close")
@require_permission("quality.change_qltnonconformity")
def close_non_conformity(request: Any, non_conformity_id: str, payload: CloseIn) -> Any:
    tenant = resolve_tenant(request)
    non_conformity = get_object_or_404(QltNonConformity, id=non_conformity_id, tenant=tenant)
    user = request.auth
    assert isinstance(user, User)
    try:
        closed = quality_public.close_non_conformity(
            non_conformity, closed_by=user, closing_reason=payload.closing_reason
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_non_conformity(closed)


@router.post("/quality/lots/release")
@require_permission("quality.change_qltnonconformity")
def release_lot(request: Any, payload: LotReleaseIn) -> Any:
    """Refuse tant qu'une non-conformite reste ouverte sur le lot, et exige
    un motif dans tous les cas — les deux regles sont portees par
    `release_lot_hold`, jamais redites ici."""
    tenant = resolve_tenant(request)
    user = request.auth
    assert isinstance(user, User)
    try:
        quality_public.release_lot_hold(
            tenant=tenant,
            lot_variant_id=payload.lot_variant_id,
            lot_name=payload.lot_name,
            released_by=user,
            reason=payload.reason,
        )
    except ValidationError as exc:
        return _error_response(exc)
    return {"released": True, "lot_name": payload.lot_name}


# ---------------------------------------------------------------------------
# Dossiers de rappel
# ---------------------------------------------------------------------------


@router.get("/quality/recalls")
@require_permission("quality.view_qltrecalldossier")
def list_recalls(request: Any) -> dict[str, Any]:
    tenant = resolve_tenant(request)
    dossiers = QltRecallDossier.objects.filter(tenant=tenant).order_by("-initiated_at")
    return {"results": [_serialize_recall(dossier) for dossier in dossiers]}


@router.post("/quality/recalls")
@require_permission("quality.add_qltrecalldossier")
def declare_recall(request: Any, payload: RecallIn) -> Any:
    """QUA-4 a QUA-7 : met en quarantaine le lot ET toute sa descendance,
    genealogies figees au moment de la declaration."""
    tenant = resolve_tenant(request)
    user = request.auth
    assert isinstance(user, User)
    try:
        dossier = quality_public.declare_recall(
            tenant=tenant,
            lot_variant_id=payload.lot_variant_id,
            lot_name=payload.lot_name,
            reason=payload.reason,
            initiated_by=user,
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_recall(dossier)


@router.post("/quality/recalls/{dossier_id}/close")
@require_permission("quality.change_qltrecalldossier")
def close_recall(request: Any, dossier_id: str, payload: CloseIn) -> Any:
    tenant = resolve_tenant(request)
    dossier = get_object_or_404(QltRecallDossier, id=dossier_id, tenant=tenant)
    user = request.auth
    assert isinstance(user, User)
    try:
        closed = quality_public.close_recall(
            dossier, closed_by=user, closing_reason=payload.closing_reason
        )
    except ValidationError as exc:
        return _error_response(exc)
    return _serialize_recall(closed)
