"""AI5 : adaptateur `apps.presence.services.ai_insight_registration` —
verifie que la source REELLE compare deux appels reels a
`services.public.get_tenant_absence_days_in_period` (gap deja construit
pour CAP1-2) sur des `PrsAbsence` reelles, sans jamais calculer un nouveau
taux d'absenteisme."""

from __future__ import annotations

import datetime as dt

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.insight_source_registry import get_insight_source
from apps.core.tests.utils import use_tenant
from apps.presence.models import PrsAbsence
from apps.presence.services.ai_insight_registration import _absence_trend
from apps.presence.tests.factories import PrsAbsenceFactory

pytestmark = pytest.mark.django_db


def test_source_is_registered_in_the_shared_registry() -> None:
    registered = get_insight_source("presence.absence_trend")
    assert registered is not None
    assert registered.module == "presence"
    assert registered.function is _absence_trend


def test_source_surfaces_a_rising_absence_trend() -> None:
    tenant = Tenant.objects.create(code="PRS-AI5-1", name="Presence AI5 Tenant 1")
    today = dt.date.today()
    with use_tenant(tenant.id):
        # Semaine courante : 2 jours d'absence validee.
        PrsAbsenceFactory(
            tenant=tenant,
            date_from=today,
            date_to=today + dt.timedelta(days=1),
            state=PrsAbsence.STATE_VALIDATED,
        )
        # Aucune absence la semaine precedente -> hausse nette.
        candidates = _absence_trend(str(tenant.id))

    assert len(candidates) == 1
    assert candidates[0].category == "rh"
    assert candidates[0].source_modules == ["presence"]
    assert "2" in candidates[0].body


def test_source_ignores_a_flat_or_declining_trend() -> None:
    tenant = Tenant.objects.create(code="PRS-AI5-2", name="Presence AI5 Tenant 2")
    today = dt.date.today()
    with use_tenant(tenant.id):
        previous_start = today - dt.timedelta(days=13)
        # Semaine precedente : 3 jours d'absence, semaine courante : rien.
        PrsAbsenceFactory(
            tenant=tenant,
            date_from=previous_start,
            date_to=previous_start + dt.timedelta(days=2),
            state=PrsAbsence.STATE_VALIDATED,
        )

        candidates = _absence_trend(str(tenant.id))

    assert candidates == []


def test_source_ignores_a_draft_absence() -> None:
    tenant = Tenant.objects.create(code="PRS-AI5-3", name="Presence AI5 Tenant 3")
    today = dt.date.today()
    with use_tenant(tenant.id):
        PrsAbsenceFactory(
            tenant=tenant,
            date_from=today,
            date_to=today,
            state=PrsAbsence.STATE_DRAFT,
        )

        candidates = _absence_trend(str(tenant.id))

    assert candidates == []
