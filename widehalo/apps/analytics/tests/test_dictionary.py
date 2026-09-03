"""Dictionnaire d'indicateurs gouverné (`services/dictionary.py`) — cahier
Phase 2 §12 : seule voie déclarée d'accès aux indicateurs décisionnels,
filtrée par rôle (anti "fuite par agrégat")."""

from __future__ import annotations

import pytest

from apps.analytics.models import AnMetricDefinition
from apps.analytics.services.dictionary import list_metric_history, list_metrics_for_user, register_metric
from apps.analytics.tests.factories import AnMetricDefinitionFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import grant_role, use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def dict_tenant() -> Tenant:
    return Tenant.objects.create(code="AN-DICT", name="Analytics Dictionary Tenant")


def test_register_metric_creates_then_versions_on_update(dict_tenant: Tenant) -> None:
    with use_tenant(dict_tenant.id):
        created = register_metric(
            dict_tenant, code="ca.mensuel", libelle="CA mensuel", module_source="sales"
        )
        assert created.version == 1
        assert created.is_current is True

        updated = register_metric(
            dict_tenant,
            code="ca.mensuel",
            libelle="Chiffre d'affaires mensuel",
            module_source="sales",
        )

        # BI-9 : la version precedente est CONSERVEE (nouvelle ligne
        # inseree), jamais ecrasee en place.
        assert updated.id != created.id
        assert updated.version == 2
        assert updated.is_current is True
        assert updated.libelle == "Chiffre d'affaires mensuel"
        assert AnMetricDefinition.objects.filter(tenant=dict_tenant, code="ca.mensuel").count() == 2

        created.refresh_from_db()
        assert created.is_current is False
        assert created.libelle == "CA mensuel"

        history = list_metric_history(dict_tenant, "ca.mensuel")
        assert [m.version for m in history] == [2, 1]


def test_register_metric_is_a_noop_when_nothing_changed(dict_tenant: Tenant) -> None:
    with use_tenant(dict_tenant.id):
        first = register_metric(
            dict_tenant, code="ca.mensuel", libelle="CA mensuel", module_source="sales"
        )
        second = register_metric(
            dict_tenant, code="ca.mensuel", libelle="CA mensuel", module_source="sales"
        )

        assert second.id == first.id
        assert second.version == 1
        assert AnMetricDefinition.objects.filter(tenant=dict_tenant, code="ca.mensuel").count() == 1


def test_list_metrics_for_user_filters_by_role_and_status(dict_tenant: Tenant) -> None:
    with use_tenant(dict_tenant.id):
        AnMetricDefinitionFactory(
            tenant=dict_tenant,
            code="metric.open",
            roles_autorises=[],
            statut=AnMetricDefinition.STATUT_PUBLIE,
        )
        AnMetricDefinitionFactory(
            tenant=dict_tenant,
            code="metric.direction_only",
            roles_autorises=["direction"],
            statut=AnMetricDefinition.STATUT_PUBLIE,
        )
        AnMetricDefinitionFactory(
            tenant=dict_tenant,
            code="metric.draft",
            roles_autorises=[],
            statut=AnMetricDefinition.STATUT_BROUILLON,
        )

        collaborateur = UserFactory()
        grant_role(collaborateur, "collaborateur")
        visible_codes = {m.code for m in list_metrics_for_user(dict_tenant, collaborateur)}
        assert visible_codes == {"metric.open"}

        direction_user = UserFactory()
        grant_role(direction_user, "direction")
        visible_codes = {m.code for m in list_metrics_for_user(dict_tenant, direction_user)}
        assert visible_codes == {"metric.open", "metric.direction_only"}
