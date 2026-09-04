"""Moteur de requête guidé (`services/query.py`) — cahier Phase 2 §13.1,
BI-1/BI-2/BI-6/BI-10."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.analytics.models import AnMetricDefinition
from apps.analytics.services.dictionary import register_metric
from apps.analytics.tests.factories import AnDimTiersFactory, AnFactVenteFactory
from apps.bi.services.query import drill_down, run_report
from apps.bi.tests.factories import BiReportFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import grant_role, use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def query_tenant() -> Tenant:
    return Tenant.objects.create(code="BI-QRY", name="BI Query Tenant")


def _publish_metric(tenant, *, code, roles_autorises=None, maille_minimale="", axes=None):
    return register_metric(
        tenant,
        code=code,
        libelle=f"Indicateur {code}",
        module_source="sales",
        axes_autorises=axes if axes is not None else ["temps", "tiers"],
        roles_autorises=roles_autorises or [],
        maille_minimale=maille_minimale,
        statut=AnMetricDefinition.STATUT_PUBLIE,
    )


def test_run_report_aggregates_by_declared_dimension(query_tenant: Tenant) -> None:
    with use_tenant(query_tenant.id):
        _publish_metric(query_tenant, code="sales.ca_ht")
        tiers = AnDimTiersFactory(tenant=query_tenant, nom="Client A")
        AnFactVenteFactory(tenant=query_tenant, dim_tiers=tiers, montant_ht_mga=Decimal("10000"))
        AnFactVenteFactory(tenant=query_tenant, dim_tiers=tiers, montant_ht_mga=Decimal("5000"))
        report = BiReportFactory(
            tenant=query_tenant,
            definition={"metric_codes": ["sales.ca_ht"], "dimensions": ["tiers"], "filters": []},
        )
        user = UserFactory()
        grant_role(user, "direction")

        result = run_report(query_tenant, report, user)

        rows = result["metrics"]["sales.ca_ht"]["rows"]
        assert rows == [{"tiers": "Client A", "value": Decimal("15000")}]
        assert result["scope_notes"] == []


def test_run_report_excludes_metric_unauthorized_for_role_before_aggregation(
    query_tenant: Tenant,
) -> None:
    """BI-6 : un indicateur restreint à un rôle est retiré AVANT tout
    calcul pour un utilisateur d'un autre rôle — jamais calculé puis
    masqué."""
    with use_tenant(query_tenant.id):
        _publish_metric(query_tenant, code="sales.ca_ht", roles_autorises=["direction"])
        AnFactVenteFactory(tenant=query_tenant, montant_ht_mga=Decimal("10000"))
        report = BiReportFactory(
            tenant=query_tenant,
            definition={"metric_codes": ["sales.ca_ht"], "dimensions": [], "filters": []},
        )

        collaborateur = UserFactory()
        grant_role(collaborateur, "collaborateur")
        result = run_report(query_tenant, report, collaborateur)
        assert result["metrics"] == {}
        assert result["scope_notes"] != []

        direction_user = UserFactory()
        grant_role(direction_user, "direction")
        result = run_report(query_tenant, report, direction_user)
        assert result["metrics"]["sales.ca_ht"]["rows"] == [{"value": Decimal("10000")}]


def test_run_report_caps_dimension_at_maille_minimale(query_tenant: Tenant) -> None:
    """BI-6 : une ventilation plus fine que la maille minimale déclarée
    est retirée, l'indicateur reste calculé en agrégat plus large."""
    with use_tenant(query_tenant.id):
        _publish_metric(query_tenant, code="sales.ca_ht", maille_minimale="tiers")
        tiers = AnDimTiersFactory(tenant=query_tenant, nom="Client A")
        AnFactVenteFactory(tenant=query_tenant, dim_tiers=tiers, montant_ht_mga=Decimal("10000"))
        report = BiReportFactory(
            tenant=query_tenant,
            definition={"metric_codes": ["sales.ca_ht"], "dimensions": ["tiers"], "filters": []},
        )
        user = UserFactory()
        grant_role(user, "direction")

        result = run_report(query_tenant, report, user)

        rows = result["metrics"]["sales.ca_ht"]["rows"]
        assert rows == [{"value": Decimal("10000")}]
        assert any("maille minimale" in note for note in result["scope_notes"])


def test_run_report_ignores_unknown_metric_code(query_tenant: Tenant) -> None:
    with use_tenant(query_tenant.id):
        report = BiReportFactory(
            tenant=query_tenant,
            definition={"metric_codes": ["does.not.exist"], "dimensions": [], "filters": []},
        )
        user = UserFactory()
        grant_role(user, "direction")

        result = run_report(query_tenant, report, user)

        assert result["metrics"] == {}


def test_drill_down_returns_underlying_rows(query_tenant: Tenant) -> None:
    with use_tenant(query_tenant.id):
        _publish_metric(query_tenant, code="sales.ca_ht")
        AnFactVenteFactory(tenant=query_tenant, montant_ht_mga=Decimal("10000"))
        report = BiReportFactory(tenant=query_tenant)
        user = UserFactory()
        grant_role(user, "direction")

        result = drill_down(query_tenant, report, user, metric_code="sales.ca_ht", cell_filters=[])

        assert result["blocked"] is False
        assert len(result["rows"]) == 1


def test_drill_down_is_blocked_when_maille_minimale_set(query_tenant: Tenant) -> None:
    """BI-10 : « le blocage éventuel est expliqué » — jamais un résultat
    partiel silencieux."""
    with use_tenant(query_tenant.id):
        _publish_metric(query_tenant, code="sales.ca_ht", maille_minimale="tiers")
        report = BiReportFactory(tenant=query_tenant)
        user = UserFactory()
        grant_role(user, "direction")

        result = drill_down(query_tenant, report, user, metric_code="sales.ca_ht", cell_filters=[])

        assert result["blocked"] is True
        assert result["reason"]
