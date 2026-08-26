from django.utils.translation import gettext as _
from ninja import Router, Schema

from apps.core.errors import ProblemDetailResponse
from apps.core.models.user import UserTenantMembership

router = Router(tags=["tenants"])


class TenantOut(Schema):
    id: str
    code: str
    name: str
    is_default: bool


class TenantSelectIn(Schema):
    tenant_id: str


@router.get("/tenants", response=list[TenantOut])
def list_tenants(request):
    memberships = UserTenantMembership.objects.filter(user=request.auth).select_related("tenant")
    return [
        TenantOut(
            id=str(m.tenant_id),
            code=m.tenant.code,
            name=m.tenant.name,
            is_default=m.is_default,
        )
        for m in memberships
    ]


@router.post("/tenants/select")
def select_tenant(request, payload: TenantSelectIn):
    exists = UserTenantMembership.objects.filter(
        user=request.auth, tenant_id=payload.tenant_id
    ).exists()
    if not exists:
        return ProblemDetailResponse(
            status=403,
            title=_("Société non autorisée"),
            detail=_("Vous n'appartenez pas à cette société."),
            instance=request.path,
        )
    request.session["tenant_id"] = payload.tenant_id
    return {"status": "ok"}
