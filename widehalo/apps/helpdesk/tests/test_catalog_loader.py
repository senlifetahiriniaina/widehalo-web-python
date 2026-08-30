"""HD1 : idempotence du chargement du catalogue de types (`ticket_type_
catalog.json`), meme discipline que `apps.accounting.tests.test_chart_of_
accounts::test_load_pcg2005_idempotent` (patron a suivre)."""

from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.helpdesk.models import HlpTicketTypeCatalog
from apps.helpdesk.services.catalog_loader import load_ticket_type_catalog

pytestmark = pytest.mark.django_db


def test_load_ticket_type_catalog_is_idempotent() -> None:
    tenant = Tenant.objects.create(code="HLP-CAT", name="Helpdesk Catalog Tenant")
    with use_tenant(tenant.id):
        first_created = load_ticket_type_catalog(tenant)
        assert first_created > 30
        total_after_first = HlpTicketTypeCatalog.objects.filter(tenant=tenant).count()

        second_created = load_ticket_type_catalog(tenant)
        assert second_created == 0
        total_after_second = HlpTicketTypeCatalog.objects.filter(tenant=tenant).count()
        assert total_after_first == total_after_second


def test_load_ticket_type_catalog_never_overwrites_tenant_customization() -> None:
    tenant = Tenant.objects.create(code="HLP-CAT2", name="Helpdesk Catalog Tenant 2")
    with use_tenant(tenant.id):
        load_ticket_type_catalog(tenant)
        entry = HlpTicketTypeCatalog.objects.get(tenant=tenant, code="stock.rupture_mp")
        entry.label = "Libelle personnalise par le tenant"
        entry.save(update_fields=["label"])

        load_ticket_type_catalog(tenant)

        entry.refresh_from_db()
        assert entry.label == "Libelle personnalise par le tenant"


def test_load_ticket_type_catalog_resolves_hierarchy() -> None:
    tenant = Tenant.objects.create(code="HLP-CAT3", name="Helpdesk Catalog Tenant 3")
    with use_tenant(tenant.id):
        load_ticket_type_catalog(tenant)
        child = HlpTicketTypeCatalog.objects.get(tenant=tenant, code="stock.rupture_mp")
        assert child.parent is not None
        assert child.parent.code == "stock"
