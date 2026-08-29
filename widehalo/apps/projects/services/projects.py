"""Creation de projet (PJ1). Reste volontairement minimal — l'edition
complete (dates, methodologie, client, objectif lie) sera enrichie au fil
des etapes PJ2-PJ15 au besoin des ecrans qu'elles introduiront."""

from __future__ import annotations

import datetime as dt
from uuid import UUID

from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.sequences import next_reference
from apps.projects.models import PrjProject


def create_project(
    tenant: Tenant,
    *,
    name: str,
    description: str = "",
    methodology: str = PrjProject.METHODOLOGY_WATERFALL,
    owner: User | None = None,
    client_partner_id: UUID | None = None,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
) -> PrjProject:
    reference = next_reference(tenant, "PRJ-PROJET", timezone.now().year)
    return PrjProject.objects.create(
        tenant=tenant,
        reference=reference,
        name=name,
        description=description,
        methodology=methodology,
        owner=owner,
        client_partner_id=client_partner_id,
        start_date=start_date,
        end_date=end_date,
    )
