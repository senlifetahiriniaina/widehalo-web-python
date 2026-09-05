"""Contrat public de `bi` (`services/public.py`)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.analytics.models import AnMetricDefinition
from apps.analytics.services.dictionary import register_metric
from apps.analytics.tests.factories import AnFactVenteFactory
from apps.bi.services.public import get_report_result, list_report_catalog
from apps.bi.tests.factories import BiReportFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import grant_role, use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def public_tenant() -> Tenant:
    return Tenant.objects.create(code="BI-PUB", name="BI Public Tenant")


def test_list_report_catalog_returns_only_published(public_tenant: Tenant) -> None:
    with use_tenant(public_tenant.id):
        BiReportFactory(tenant=public_tenant, name="Publié", is_published=True)
        BiReportFactory(tenant=public_tenant, name="Brouillon", is_published=False)

        results = list_report_catalog(public_tenant)

    assert [r["name"] for r in results] == ["Publié"]


def test_get_report_result_none_for_unpublished_or_missing(public_tenant: Tenant) -> None:
    with use_tenant(public_tenant.id):
        BiReportFactory(tenant=public_tenant, code="draft", is_published=False)
        user = UserFactory()
        grant_role(user, "direction")

        assert get_report_result(public_tenant, "draft", user) is None
        assert get_report_result(public_tenant, "does-not-exist", user) is None


def test_get_report_result_runs_the_query(public_tenant: Tenant) -> None:
    with use_tenant(public_tenant.id):
        register_metric(
            public_tenant,
            code="sales.ca_ht",
            libelle="CA HT",
            module_source="sales",
            # L8 : le fait vient desormais du dictionnaire lui-meme, plus
            # d'une table de correspondance figee dans `bi`.
            fait_source="vente",
            axes_autorises=["temps"],
            statut=AnMetricDefinition.STATUT_PUBLIE,
        )
        AnFactVenteFactory(tenant=public_tenant, montant_ht_mga=Decimal("999"))
        BiReportFactory(
            tenant=public_tenant,
            code="ca",
            is_published=True,
            definition={"metric_codes": ["sales.ca_ht"], "dimensions": [], "filters": []},
        )
        user = UserFactory()
        grant_role(user, "direction")

        result = get_report_result(public_tenant, "ca", user)

    assert result["metrics"]["sales.ca_ht"]["rows"] == [{"value": Decimal("999")}]
