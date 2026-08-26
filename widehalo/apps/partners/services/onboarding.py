from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.services.sequences import next_reference
from apps.partners.models import DuplicateAlert, Partner


def create_partner(
    *,
    tenant: Tenant,
    name: str,
    roles: list[str],
    nif: str = "",
    credit_limit_mga: Decimal = Decimal(0),
) -> Partner:
    """Cree un partenaire avec un code auto-sequence (PART-<annee>-NNNN) et
    detecte un eventuel doublon de NIF DANS LE MEME TENANT sans jamais
    bloquer la creation — une `DuplicateAlert` est simplement journalisee
    pour revue humaine."""
    reference = next_reference(tenant, "PART", timezone.now().year)

    partner = Partner.objects.create(
        tenant=tenant,
        reference=reference,
        name=name,
        roles=roles,
        nif=nif,
        credit_limit_mga=credit_limit_mga,
    )

    if nif:
        existing_matches = Partner.objects.filter(tenant=tenant, nif=nif).exclude(pk=partner.pk)
        for match in existing_matches:
            DuplicateAlert.objects.create(
                tenant=tenant, partner=partner, duplicate_of=match, matched_field="nif"
            )

    return partner
