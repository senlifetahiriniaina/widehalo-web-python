from __future__ import annotations

from decimal import Decimal

from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.core.services.permissions import require_permission
from apps.partners.models import Partner
from apps.partners.services.merge import merge_partners
from apps.partners.services.onboarding import create_partner

router = Router(tags=["partners"])


class PartnerIn(Schema):
    name: str
    roles: list[str] = []
    nif: str = ""
    credit_limit_mga: Decimal = Decimal(0)


class MergeIn(Schema):
    primary_id: str
    duplicate_id: str


def _serialize(partner: Partner) -> dict:
    return {
        "id": str(partner.id),
        "reference": partner.reference,
        "name": partner.name,
        "roles": partner.roles,
        "nif": partner.nif,
        "credit_limit_mga": str(partner.credit_limit_mga),
    }


# NOTE ordre des decorateurs : `@router.xxx` DOIT etre le decorateur EXTERNE
# (le plus haut) et `@require_permission(...)` l'INTERNE (juste au-dessus de
# `def`). `Router.api_operation` enregistre dans `add_api_operation` la
# fonction qui lui est passee DIRECTEMENT, puis la retourne inchangee — donc
# seul le decorateur le plus proche de `def` finit dans la table de routage
# effectivement invoquee a chaque requete (verifie empiriquement).
@router.get("/partners")
@require_permission("partners.view_partner")
def list_partners(request):
    return {"results": [_serialize(p) for p in Partner.objects.filter(is_active=True)]}


@router.post("/partners")
@require_permission("partners.add_partner")
def create_partner_endpoint(request, payload: PartnerIn):
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    partner = create_partner(
        tenant=tenant,
        name=payload.name,
        roles=payload.roles,
        nif=payload.nif,
        credit_limit_mga=payload.credit_limit_mga,
    )
    return _serialize(partner)


@router.get("/partners/{partner_id}")
@require_permission("partners.view_partner")
def get_partner(request, partner_id: str):
    partner = get_object_or_404(Partner, id=partner_id)
    return _serialize(partner)


@router.post("/partners/merge")
@require_permission("partners.change_partner")
def merge_endpoint(request, payload: MergeIn):
    primary = get_object_or_404(Partner, id=payload.primary_id)
    duplicate = get_object_or_404(Partner, id=payload.duplicate_id)
    reassigned = merge_partners(primary=primary, duplicate=duplicate)
    return {"reassigned": reassigned}
