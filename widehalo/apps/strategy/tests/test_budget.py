"""Construction, verrouillage et suivi budgétaire (cahier §13.3,
STR-3/STR-4/STR-5/STR-6)."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, transaction

from apps.analytics.models import AnMetricDefinition
from apps.analytics.services.dictionary import register_metric
from apps.analytics.tests.factories import AnFactVenteFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.forecast.tests.factories import ForPublicationFactory
from apps.simulation.tests.factories import SimScenarioFactory
from apps.strategy.services.budget import (
    add_variance_comment,
    can_close_review,
    compute_variance,
    create_budget,
    create_budget_from_forecast_publication,
    create_budget_from_simulation_scenario,
    line_key,
    lock_budget,
    revise_budget,
)
from apps.strategy.tests.factories import StgBudgetFactory

pytestmark = pytest.mark.django_db


def _line(axis_value: str = "compte1", metric_code: str = "", value: str = "1000") -> dict:
    return {
        "axis_type": "compte",
        "axis_value": axis_value,
        "metric_code": metric_code,
        "period": datetime.date(2026, 1, 1),
        "budgeted_value": value,
    }


def test_create_budget_rejects_unknown_axis_type() -> None:
    tenant = Tenant.objects.create(code="STG-BUD1", name="Budget Tenant 1")
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        create_budget(
            tenant,
            name="Budget invalide",
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
            lines=[{**_line(), "axis_type": "inconnu"}],
        )


def test_lock_budget_sets_flag_and_rejects_double_lock() -> None:
    tenant = Tenant.objects.create(code="STG-BUD2", name="Budget Tenant 2")
    with use_tenant(tenant.id):
        user = UserFactory()
        budget = create_budget(
            tenant,
            name="Budget 2026",
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
            lines=[_line()],
        )
        assert budget.is_locked is False

        lock_budget(budget, user=user)
        assert budget.is_locked is True
        assert budget.locked_by_id == user.id
        assert budget.locked_at is not None

        with pytest.raises(ValidationError):
            lock_budget(budget, user=user)


def test_locked_budget_engaged_figures_immutable_at_db_level() -> None:
    """STR-3, §17.2 : « y compris pour un administrateur » — le trigger
    Postgres rejette la mutation, pas seulement le service Python."""
    tenant = Tenant.objects.create(code="STG-BUD3", name="Budget Tenant 3")
    with use_tenant(tenant.id):
        user = UserFactory()
        budget = create_budget(
            tenant,
            name="Budget verrouille",
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
            lines=[_line()],
        )
        lock_budget(budget, user=user)

        with (
            pytest.raises(Exception, match="immuable"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute("UPDATE stg_budget SET name = 'hack' WHERE id = %s", [str(budget.id)])


def test_locked_budget_variance_comments_remain_mutable() -> None:
    """STR-6 : un commentaire de gestion doit pouvoir être ajouté APRÈS le
    verrouillage — la migration d'immuabilité exclut délibérément ce champ
    des chiffres engagés figés."""
    tenant = Tenant.objects.create(code="STG-BUD4", name="Budget Tenant 4")
    with use_tenant(tenant.id):
        user = UserFactory()
        budget = create_budget(
            tenant,
            name="Budget commentable",
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
            lines=[_line()],
        )
        lock_budget(budget, user=user)

        key = line_key("compte", "compte1", datetime.date(2026, 1, 1))
        add_variance_comment(budget, line_key_value=key, text="Ecart explique", user=user)

        budget.refresh_from_db()
        assert budget.variance_comments[0]["text"] == "Ecart explique"


def test_add_variance_comment_rejects_unknown_line_key() -> None:
    tenant = Tenant.objects.create(code="STG-BUD5", name="Budget Tenant 5")
    with use_tenant(tenant.id):
        user = UserFactory()
        budget = create_budget(
            tenant,
            name="Budget",
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
            lines=[_line()],
        )
        with pytest.raises(ValidationError):
            add_variance_comment(
                budget, line_key_value="compte:inconnu:2026-01-01", text="x", user=user
            )


def test_revise_budget_creates_new_version_previous_untouched() -> None:
    tenant = Tenant.objects.create(code="STG-BUD6", name="Budget Tenant 6")
    with use_tenant(tenant.id):
        user = UserFactory()
        budget = create_budget(
            tenant,
            name="Budget revisable",
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
            lines=[_line(value="1000")],
        )
        lock_budget(budget, user=user)

        revised = revise_budget(budget, lines=[_line(value="2000")], created_by=user)

        assert revised.version == budget.version + 1
        assert revised.previous_version_id == budget.id
        assert revised.is_locked is False
        assert revised.lines[0]["budgeted_value"] == "2000"

        budget.refresh_from_db()
        assert budget.lines[0]["budgeted_value"] == "1000"


def test_compute_variance_uses_bi_governed_metric_value() -> None:
    """STR-5 : l'écart est calculé via la MÊME fonction que BI (`bi.
    services.public.get_metric_current_value`), garantissant l'identité de
    définition entre budget et réel."""
    tenant = Tenant.objects.create(code="STG-BUD7", name="Budget Tenant 7")
    with use_tenant(tenant.id):
        user = UserFactory()
        register_metric(
            tenant,
            code="sales.ca_ht",
            libelle="CA HT",
            module_source="sales",
            fait_source="vente",
            statut=AnMetricDefinition.STATUT_PUBLIE,
        )
        AnFactVenteFactory(tenant=tenant, montant_ht_mga=Decimal("1200"))

        budget = create_budget(
            tenant,
            name="Budget CA",
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
            lines=[_line(metric_code="sales.ca_ht", value="1000")],
        )

        rows = compute_variance(tenant, budget, user=user)

        assert len(rows) == 1
        row = rows[0]
        assert row["actual_value"] == Decimal("1200")
        assert row["variance_value"] == Decimal("200")
        assert row["exceeds_threshold"] is True


def test_compute_variance_none_actual_when_line_has_no_metric_code() -> None:
    """Ligne issue d'une simulation/prévision sans mappage explicite : pas
    d'écart inventé, `actual_value=None`."""
    tenant = Tenant.objects.create(code="STG-BUD8", name="Budget Tenant 8")
    with use_tenant(tenant.id):
        user = UserFactory()
        budget = create_budget(
            tenant,
            name="Budget sans indicateur",
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
            lines=[_line(metric_code="")],
        )
        rows = compute_variance(tenant, budget, user=user)
        assert rows[0]["actual_value"] is None
        assert rows[0]["variance_value"] is None
        assert rows[0]["exceeds_threshold"] is False


def test_can_close_review_blocked_by_uncommented_significant_variance() -> None:
    tenant = Tenant.objects.create(code="STG-BUD9", name="Budget Tenant 9")
    with use_tenant(tenant.id):
        user = UserFactory()
        register_metric(
            tenant,
            code="sales.ca_ht",
            libelle="CA HT",
            module_source="sales",
            fait_source="vente",
            statut=AnMetricDefinition.STATUT_PUBLIE,
        )
        AnFactVenteFactory(tenant=tenant, montant_ht_mga=Decimal("5000"))
        budget = create_budget(
            tenant,
            name="Budget ecart",
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
            lines=[_line(metric_code="sales.ca_ht", value="1000")],
        )

        rows = compute_variance(tenant, budget, user=user)
        assert can_close_review(rows) is False

        key = line_key("compte", "compte1", datetime.date(2026, 1, 1))
        add_variance_comment(budget, line_key_value=key, text="Ecart justifie", user=user)
        rows = compute_variance(tenant, budget, user=user)
        assert can_close_review(rows) is True


def test_create_budget_from_simulation_scenario_maps_indicators_to_lines() -> None:
    tenant = Tenant.objects.create(code="STG-BUD10", name="Budget Tenant 10")
    with use_tenant(tenant.id):
        user = UserFactory()
        scenario = SimScenarioFactory(
            tenant=tenant, computed_indicators={"resultat_net": "12000000", "ebe": "39000000"}
        )

        budget = create_budget_from_simulation_scenario(
            tenant,
            scenario_id=str(scenario.id),
            name="Budget depuis simulation",
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
            created_by=user,
        )

        assert budget.source_type == budget.SOURCE_SIMULATION
        assert budget.source_reference["scenario_id"] == str(scenario.id)
        axis_values = {line["axis_value"] for line in budget.lines}
        assert axis_values == {"resultat_net", "ebe"}
        assert all(line["metric_code"] == "" for line in budget.lines)


def test_create_budget_from_simulation_scenario_unknown_id_raises() -> None:
    tenant = Tenant.objects.create(code="STG-BUD11", name="Budget Tenant 11")
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        create_budget_from_simulation_scenario(
            tenant,
            scenario_id="00000000-0000-0000-0000-000000000000",
            name="Budget",
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )


def test_create_budget_from_forecast_publication_maps_canal_to_compte_axis() -> None:
    tenant = Tenant.objects.create(code="STG-BUD12", name="Budget Tenant 12")
    with use_tenant(tenant.id):
        user = UserFactory()
        publication = ForPublicationFactory(
            tenant=tenant,
            snapshot=[
                {
                    "dimension_type": "canal",
                    "dimension_value": "pos",
                    "period": "2026-01-01",
                    "value": "5000",
                }
            ],
        )

        budget = create_budget_from_forecast_publication(
            tenant, name="Budget prevision", created_by=user
        )

        assert budget.source_type == budget.SOURCE_FORECAST
        assert budget.source_reference["publication_version"] == publication.version
        assert budget.lines[0]["axis_type"] == "compte"
        assert budget.lines[0]["axis_value"] == "pos"


def test_create_budget_from_forecast_publication_no_publication_raises() -> None:
    tenant = Tenant.objects.create(code="STG-BUD13", name="Budget Tenant 13")
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        create_budget_from_forecast_publication(tenant, name="Budget")


def test_budget_factory_smoke() -> None:
    tenant = Tenant.objects.create(code="STG-BUD14", name="Budget Tenant 14")
    with use_tenant(tenant.id):
        budget = StgBudgetFactory(tenant=tenant)
        assert budget.version == 1
        assert budget.is_locked is False
