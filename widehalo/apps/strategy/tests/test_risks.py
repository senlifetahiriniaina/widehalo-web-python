"""Cartographie des risques d'entreprise (cahier §13.3, STR-8)."""

from __future__ import annotations

import pytest

from apps.core.models.audit import AuditLog
from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.strategy.services.risks import create_risk, reassess_risk

pytestmark = pytest.mark.django_db


def test_create_risk_computes_risk_score() -> None:
    tenant = Tenant.objects.create(code="STG-RSK1", name="Risk Tenant 1")
    with use_tenant(tenant.id):
        risk = create_risk(tenant, title="Rupture fournisseur", probability=4, impact=3)
        assert risk.risk_score == 12


def test_reassess_risk_updates_fields_and_timestamp() -> None:
    tenant = Tenant.objects.create(code="STG-RSK2", name="Risk Tenant 2")
    with use_tenant(tenant.id):
        user = UserFactory()
        risk = create_risk(tenant, title="Risque change", probability=2, impact=2)
        assert risk.last_reassessed_at is None

        reassess_risk(
            risk, probability=5, impact=4, control_measure="Plan de secours active", user=user
        )

        risk.refresh_from_db()
        assert risk.probability == 5
        assert risk.impact == 4
        assert risk.risk_score == 20
        assert risk.control_measure == "Plan de secours active"
        assert risk.last_reassessed_at is not None
        assert risk.last_reassessed_by_id == user.id


def test_reassess_risk_is_captured_by_audit_log() -> None:
    """STR-8 : « toute réévaluation apparaît au journal d'audit » — capturé
    automatiquement par `apps.core.audit_signals`, aucun code dédié requis
    dans `services/risks.py`."""
    tenant = Tenant.objects.create(code="STG-RSK3", name="Risk Tenant 3")
    with use_tenant(tenant.id):
        user = UserFactory()
        risk = create_risk(tenant, title="Risque audite", probability=1, impact=1)

        reassess_risk(risk, probability=3, impact=3, control_measure="", user=user)

        assert AuditLog.objects.filter(
            action=AuditLog.ACTION_UPDATED, object_id=str(risk.id)
        ).exists()
