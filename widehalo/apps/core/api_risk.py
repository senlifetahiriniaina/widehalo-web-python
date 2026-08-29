"""API CRUD minimale du registre de risques operationnels (RSK1-2).

Scoping N3 volontairement simple (disclosed, cf. `rbac_policy.py`) :
`direction`/`admin` voient TOUS les risques du tenant ; les autres roles
(`acheteur`/`resp_production`/`resp_commercial`/`rh`) ne voient QUE les
leurs (`owner=request.auth`) — filtre direct dans `_visible_queryset`,
jamais un scope N3 complexe par entite rattachee (`apply_scope` ne
s'applique pas ici : ce mecanisme scope par departement/role de
`strategy`, sans equivalent pour un registre de risques transverse a tous
les modules). La visibilite totale est detectee via la permission
`core.change_riskitem` (accordee UNIQUEMENT a `admin`/`direction`, cf.
`rbac_policy.CUSTOM_PERMISSIONS`) plutot qu'un nom de role litteral : les
deux notions coincident exactement dans ce lot (seuls ces 2 roles recoivent
`change`), et un controle par permission reste correct meme si un role
personnalise futur recoit un jour cette meme permission."""

from __future__ import annotations

from datetime import date

from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.core.models.risk import RiskItem
from apps.core.services.permissions import require_permission
from apps.core.services.risk import close_risk_item, create_risk_item, update_risk_item

router = Router(tags=["risk"])


class RiskItemIn(Schema):
    category: str
    likelihood: int
    impact: int
    mitigation_plan: str = ""
    review_date: date | None = None


class RiskItemUpdateIn(Schema):
    category: str | None = None
    likelihood: int | None = None
    impact: int | None = None
    mitigation_plan: str | None = None
    review_date: date | None = None


def _serialize(risk_item: RiskItem) -> dict:
    return {
        "id": str(risk_item.id),
        "category": risk_item.category,
        "likelihood": risk_item.likelihood,
        "impact": risk_item.impact,
        "score": risk_item.score,
        "mitigation_plan": risk_item.mitigation_plan,
        "owner_id": str(risk_item.owner_id),
        "status": risk_item.status,
        "review_date": risk_item.review_date.isoformat() if risk_item.review_date else None,
        "content_type_id": risk_item.content_type_id,
        "object_id": risk_item.object_id,
    }


def _visible_queryset(request):
    queryset = RiskItem.objects.all()
    if request.auth.has_perm("core.change_riskitem"):
        return queryset
    return queryset.filter(owner=request.auth)


@router.get("/risks")
@require_permission("core.view_riskitem")
def list_risks(request):
    return {"results": [_serialize(r) for r in _visible_queryset(request)]}


@router.get("/risks/{risk_id}")
@require_permission("core.view_riskitem")
def get_risk(request, risk_id: str):
    risk_item = get_object_or_404(_visible_queryset(request), id=risk_id)
    return _serialize(risk_item)


@router.post("/risks")
@require_permission("core.add_riskitem")
def create_risk_endpoint(request, payload: RiskItemIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    risk_item = create_risk_item(
        tenant=tenant,
        category=payload.category,
        likelihood=payload.likelihood,
        impact=payload.impact,
        owner=request.auth,
        mitigation_plan=payload.mitigation_plan,
        review_date=payload.review_date,
    )
    return _serialize(risk_item)


@router.patch("/risks/{risk_id}")
@require_permission("core.change_riskitem")
def update_risk_endpoint(request, risk_id: str, payload: RiskItemUpdateIn):
    risk_item = get_object_or_404(RiskItem, id=risk_id)
    risk_item = update_risk_item(
        risk_item,
        updated_by=request.auth,
        category=payload.category,
        likelihood=payload.likelihood,
        impact=payload.impact,
        mitigation_plan=payload.mitigation_plan,
        review_date=payload.review_date,
    )
    return _serialize(risk_item)


@router.post("/risks/{risk_id}/close")
@require_permission("core.change_riskitem")
def close_risk_endpoint(request, risk_id: str):
    risk_item = get_object_or_404(RiskItem, id=risk_id)
    risk_item = close_risk_item(risk_item, closed_by=request.auth)
    return _serialize(risk_item)
