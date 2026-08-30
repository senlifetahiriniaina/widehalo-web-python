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
    pour revue humaine.

    **INT1 (chantier interactivite native inter-modules)** : chaque
    `DuplicateAlert` creee publie `partners.duplicate_alert_created` (meme
    patron que `core.services.risk._maybe_publish_flagged` — persistance
    metier d'abord, `publish_event` ensuite), pour qu'un flux du Studio de
    workflow visuel puisse notifier le role responsable de la revue des
    doublons sans modification de ce module."""
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
        from apps.core.events import publish_event

        existing_matches = Partner.objects.filter(tenant=tenant, nif=nif).exclude(pk=partner.pk)
        for match in existing_matches:
            alert = DuplicateAlert.objects.create(
                tenant=tenant, partner=partner, duplicate_of=match, matched_field="nif"
            )
            publish_event(
                "partners.duplicate_alert_created",
                {
                    "alert_id": str(alert.id),
                    "partner_id": str(partner.id),
                    "duplicate_of_id": str(match.id),
                    "matched_field": alert.matched_field,
                },
                tenant_id=str(tenant.id),
            )

    return partner
