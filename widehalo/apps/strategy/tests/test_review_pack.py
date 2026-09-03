"""Pack de revue de performance (cahier §13.3, STR-6/STR-7) — génération
figée, gate sur les écarts non commentés, immuabilité en base."""

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
from apps.strategy.services.budget import add_variance_comment, create_budget, line_key
from apps.strategy.services.objectives import add_key_result, create_objective
from apps.strategy.services.review_pack import generate_review_pack
from apps.strategy.services.risks import create_risk

pytestmark = pytest.mark.django_db


def _line(value: str = "1000", metric_code: str = "sales.ca_ht") -> dict:
    return {
        "axis_type": "compte",
        "axis_value": "compte1",
        "metric_code": metric_code,
        "period": datetime.date(2026, 1, 1),
        "budgeted_value": value,
    }


def test_generate_review_pack_blocked_by_uncommented_significant_variance() -> None:
    tenant = Tenant.objects.create(code="STG-RP1", name="Review Pack Tenant 1")
    with use_tenant(tenant.id):
        user = UserFactory()
        register_metric(
            tenant,
            code="sales.ca_ht",
            libelle="CA HT",
            module_source="sales",
            statut=AnMetricDefinition.STATUT_PUBLIE,
        )
        AnFactVenteFactory(tenant=tenant, montant_ht_mga=Decimal("5000"))
        budget = create_budget(
            tenant,
            name="Budget revue",
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
            lines=[_line()],
        )

        with pytest.raises(ValidationError):
            generate_review_pack(
                tenant,
                budget=budget,
                period_start=datetime.date(2026, 1, 1),
                period_end=datetime.date(2026, 3, 31),
                user=user,
            )


def test_generate_review_pack_succeeds_once_variance_commented() -> None:
    tenant = Tenant.objects.create(code="STG-RP2", name="Review Pack Tenant 2")
    with use_tenant(tenant.id):
        user = UserFactory()
        register_metric(
            tenant,
            code="sales.ca_ht",
            libelle="CA HT",
            module_source="sales",
            statut=AnMetricDefinition.STATUT_PUBLIE,
        )
        AnFactVenteFactory(tenant=tenant, montant_ht_mga=Decimal("5000"))
        budget = create_budget(
            tenant,
            name="Budget revue OK",
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
            lines=[_line()],
        )
        key = line_key("compte", "compte1", datetime.date(2026, 1, 1))
        add_variance_comment(budget, line_key_value=key, text="Ecart explique", user=user)

        pack = generate_review_pack(
            tenant,
            budget=budget,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 3, 31),
            user=user,
        )

        assert Decimal(pack.snapshot["variance_lines"][0]["actual_value"]) == Decimal("5000")
        assert pack.snapshot["variance_lines"][0]["comments"][0]["text"] == "Ecart explique"


def test_generate_review_pack_without_budget_skips_variance_gate() -> None:
    tenant = Tenant.objects.create(code="STG-RP3", name="Review Pack Tenant 3")
    with use_tenant(tenant.id):
        user = UserFactory()
        pack = generate_review_pack(
            tenant,
            budget=None,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 3, 31),
            user=user,
        )
        assert pack.snapshot["variance_lines"] == []


def test_generate_review_pack_freezes_objective_and_risk_snapshot() -> None:
    """STR-7 : le pack affiche exactement les mêmes valeurs/définitions/
    commentaires qu'à sa génération, même si les données bougent ensuite."""
    tenant = Tenant.objects.create(code="STG-RP4", name="Review Pack Tenant 4")
    with use_tenant(tenant.id):
        user = UserFactory()
        register_metric(
            tenant,
            code="sales.ca_ht",
            libelle="CA HT",
            module_source="sales",
            statut=AnMetricDefinition.STATUT_PUBLIE,
        )
        objective = create_objective(
            tenant,
            title="Objectif figé",
            level="company",
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        add_key_result(
            objective, metric_name="CA MGA", target_value=Decimal("1000"), metric_code="sales.ca_ht"
        )
        risk = create_risk(tenant, title="Risque figé", probability=2, impact=2)

        pack = generate_review_pack(
            tenant,
            budget=None,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 3, 31),
            user=user,
        )
        frozen_title = pack.snapshot["objectives"][0]["title"]
        frozen_risk_score = pack.snapshot["risks"][0]["risk_score"]

        objective.title = "Titre modifie apres coup"
        objective.save(update_fields=["title"])
        risk.probability = 5
        risk.save(update_fields=["probability"])

        pack.refresh_from_db()
        assert pack.snapshot["objectives"][0]["title"] == frozen_title == "Objectif figé"
        assert pack.snapshot["risks"][0]["risk_score"] == frozen_risk_score == 4


def test_review_pack_immutable_at_db_level() -> None:
    tenant = Tenant.objects.create(code="STG-RP5", name="Review Pack Tenant 5")
    with use_tenant(tenant.id):
        user = UserFactory()
        pack = generate_review_pack(
            tenant,
            budget=None,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 3, 31),
            user=user,
        )

        with (
            pytest.raises(Exception, match="immuable"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE stg_review_pack SET snapshot = '{}' WHERE id = %s", [str(pack.id)]
            )


def test_review_pack_cannot_be_deleted() -> None:
    tenant = Tenant.objects.create(code="STG-RP6", name="Review Pack Tenant 6")
    with use_tenant(tenant.id):
        user = UserFactory()
        pack = generate_review_pack(
            tenant,
            budget=None,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 3, 31),
            user=user,
        )

        with (
            pytest.raises(Exception, match="immuable"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute("DELETE FROM stg_review_pack WHERE id = %s", [str(pack.id)])
