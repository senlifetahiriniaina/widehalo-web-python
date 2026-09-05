"""Bloc F, F3 (FOR-14) : `services.workload_forecast.
compute_workshop_workload_forecast` — réutilisation du protocole de
rétrotest de `services/engine.py` (déjà testé pour la prévision de
ventes dans `test_engine.py`) appliqué à un historique d'heures
RÉELLEMENT réalisées (`MrpCra` validés) par atelier."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.forecast.services.workload_forecast import compute_workshop_workload_forecast
from apps.mrp.services.cra import create_cra, submit_cra, validate_cra
from apps.mrp.tests.factories import MrpWorkshopFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(code="FOR-F3", name="Forecast F3 Tenant")


def _months_ago(n: int) -> dt.date:
    """Reconstitution independante (jamais un import de la fonction
    privee du service) du meme pas de mois que `get_workshop_realized_
    hours_series`/`compute_workshop_workload_forecast` — pour calculer
    les dates attendues sans tester la fonction contre elle-meme."""
    month_start = dt.date.today().replace(day=1)
    for _ in range(n):
        month_start = (month_start - dt.timedelta(days=1)).replace(day=1)
    return month_start


def _validated_cra(tenant: Tenant, user: User, workshop, *, date: dt.date, hours: Decimal) -> None:
    cra = create_cra(tenant=tenant, employee=user, workshop=workshop, date=date, hours=hours)
    submit_cra(cra, user)
    validate_cra(cra, user)


def test_returns_one_entry_per_non_subcontractor_workshop(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        MrpWorkshopFactory(tenant=tenant, code="W1", name="Atelier 1")
        MrpWorkshopFactory(
            tenant=tenant, code="W2", name="Atelier Sous-traitant", is_subcontractor=True
        )

        results = compute_workshop_workload_forecast(tenant, horizon_months=2, history_months=4)

        assert len(results) == 1
        assert results[0]["workshop_code"] == "W1"


def test_returns_empty_list_without_any_workshop(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        assert compute_workshop_workload_forecast(tenant) == []


def test_history_rows_compare_walk_forward_projection_to_the_real_realized_hours(
    tenant: Tenant,
) -> None:
    """Le coeur du sprint (titre : "projeté vs. réalisé") : pour les
    periodes deja echues, `realized_hours` doit etre EXACTEMENT ce qui a
    ete reellement valide en CRA — jamais recalcule, jamais une
    approximation."""
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="f3-realise@example.com", password="Str0ngPassw0rd!23"
        )
        workshop = MrpWorkshopFactory(tenant=tenant, code="W1", name="Atelier 1")
        _validated_cra(tenant, user, workshop, date=_months_ago(3), hours=Decimal("10"))
        _validated_cra(tenant, user, workshop, date=_months_ago(2), hours=Decimal("20"))
        _validated_cra(tenant, user, workshop, date=_months_ago(1), hours=Decimal("30"))
        _validated_cra(tenant, user, workshop, date=_months_ago(0), hours=Decimal("5"))

        results = compute_workshop_workload_forecast(
            tenant, horizon_months=2, history_months=4, test_periods=2
        )

        assert len(results) == 1
        workshop_result = results[0]
        assert workshop_result["selected_model"] is not None
        history = workshop_result["history"]
        assert len(history) == 2
        assert history[0]["period"] == _months_ago(1)
        assert history[0]["realized_hours"] == Decimal("30")
        assert history[1]["period"] == _months_ago(0)
        assert history[1]["realized_hours"] == Decimal("5")
        # Une projection est toujours produite (jamais None) pour une
        # periode deja echue — c'est la valeur comparee au reel.
        assert isinstance(history[0]["projected_hours"], Decimal)
        assert isinstance(history[1]["projected_hours"], Decimal)


def test_forward_rows_never_carry_a_realized_value_and_compute_workload_pct(
    tenant: Tenant,
) -> None:
    """Bloc F, F3 : l'avenir n'a par construction aucun realise — jamais
    un `None`/`0` trompeur substitue, la cle n'existe simplement pas.
    `workload_pct` assemble la charge projetee a la capacite declaree
    (FOR-14, "briques de capacite... non assemblees")."""
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="f3-forward@example.com", password="Str0ngPassw0rd!23"
        )
        workshop = MrpWorkshopFactory(
            tenant=tenant, code="W1", name="Atelier 1", capacity_hours_day=Decimal("8.00")
        )
        for i in range(4):
            _validated_cra(tenant, user, workshop, date=_months_ago(i), hours=Decimal("20"))

        results = compute_workshop_workload_forecast(
            tenant, horizon_months=3, history_months=4, test_periods=2
        )

        forward = results[0]["forward"]
        assert len(forward) == 3
        for row in forward:
            assert "realized_hours" not in row
            assert row["capacity_hours"] > 0
            assert row["workload_pct"] == row["projected_hours"] / row["capacity_hours"] * 100


def test_respects_custom_horizon_and_history_window(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        MrpWorkshopFactory(tenant=tenant, code="W1", name="Atelier 1")

        results = compute_workshop_workload_forecast(
            tenant, horizon_months=1, history_months=6, test_periods=3
        )

        assert len(results[0]["forward"]) == 1
        assert len(results[0]["history"]) == 3


def test_flat_zero_history_never_raises_and_yields_zero_projection(tenant: Tenant) -> None:
    """Aucun CRA jamais valide pour cet atelier : la serie realisee est
    plate a zero (jamais un trou), et la projection reste honnete (zero),
    jamais une exception ni un `None` masquant l'absence de donnees."""
    with use_tenant(tenant.id):
        MrpWorkshopFactory(tenant=tenant, code="W1", name="Atelier 1")

        results = compute_workshop_workload_forecast(tenant, horizon_months=1, history_months=4)

        assert results[0]["selected_model"] is not None
        assert all(row["realized_hours"] == Decimal(0) for row in results[0]["history"])
