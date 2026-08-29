"""PRC3 : commande de management `run_price_watch_checks` — boucle tous
tenants, aucune fuite inter-tenant."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.purchase.models import PrcPriceSnapshot
from apps.purchase.tests.factories import PrcPriceWatchTargetFactory

pytestmark = pytest.mark.django_db


def test_run_price_watch_checks_command_creates_stub_snapshots() -> None:
    tenant = Tenant.objects.create(code="PRC-CMD", name="Price Watch Command Tenant")
    with use_tenant(tenant.id):
        target = PrcPriceWatchTargetFactory(tenant=tenant)

    call_command("run_price_watch_checks")

    with use_tenant(tenant.id):
        snapshot = PrcPriceSnapshot.objects.get(target=target)
        assert snapshot.is_stub is True
        assert snapshot.observed_price is None


def test_run_price_watch_checks_command_isolates_tenants() -> None:
    tenant_a = Tenant.objects.create(code="PRC-CMD-A", name="Price Watch Command Tenant A")
    tenant_b = Tenant.objects.create(code="PRC-CMD-B", name="Price Watch Command Tenant B")

    with use_tenant(tenant_a.id):
        target_a = PrcPriceWatchTargetFactory(tenant=tenant_a)
    with use_tenant(tenant_b.id):
        target_b = PrcPriceWatchTargetFactory(tenant=tenant_b)

    call_command("run_price_watch_checks")

    with use_tenant(tenant_a.id):
        assert PrcPriceSnapshot.objects.filter(target=target_a).count() == 1
        assert PrcPriceSnapshot.objects.filter(target=target_b).count() == 0
    with use_tenant(tenant_b.id):
        assert PrcPriceSnapshot.objects.filter(target=target_b).count() == 1
        assert PrcPriceSnapshot.objects.filter(target=target_a).count() == 0


def test_run_price_watch_checks_command_no_op_without_targets() -> None:
    Tenant.objects.create(code="PRC-CMD-EMPTY", name="Price Watch Command No Targets")
    # Ne doit pas lever malgre l'absence de cible.
    call_command("run_price_watch_checks")
