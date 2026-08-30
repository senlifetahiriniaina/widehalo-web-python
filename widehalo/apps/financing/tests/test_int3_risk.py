"""INT3 (chantier interactivite native inter-modules) : `flag_guarantee_
coverage_risk` transforme un dossier de financement REELLEMENT sous-couvert
(< `GUARANTEE_COVERAGE_RATIO`, meme diagnostic que l'advisor `financing.
guarantee_coverage_advisor`, INT2) en `RiskItem` generique reel."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.core.models.risk import CATEGORY_FINANCIAL, RiskItem
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.financing.models import FinGuarantee
from apps.financing.services.guarantees import add_guarantee, flag_guarantee_coverage_risk
from apps.financing.services.loan_applications import create_loan_application

pytestmark = pytest.mark.django_db


def _application(tenant: Tenant, amount: Decimal = Decimal("10000000")):
    return create_loan_application(
        tenant,
        type="fonctionnement",
        amount_requested_mga=amount,
        duration_months=12,
    )


def test_flag_guarantee_coverage_risk_creates_risk_item_when_undercovered() -> None:
    tenant = Tenant.objects.create(code="FIN-INT3-1", name="Financing INT3 Tenant 1")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="fin-int3-1@example.com", password="Str0ngPassw0rd!23"
        )
        application = _application(tenant)
        add_guarantee(
            application,
            type=FinGuarantee.GUARANTEE_TYPE_MORTGAGE,
            estimated_value_mga=Decimal("5000000"),
        )

        risk_item = flag_guarantee_coverage_risk(application, owner=user)

        assert risk_item is not None
        assert risk_item.category == CATEGORY_FINANCIAL
        assert risk_item.content_object == application
        assert risk_item.owner_id == user.id
        assert RiskItem.objects.filter(tenant=tenant).count() == 1


def test_flag_guarantee_coverage_risk_returns_none_when_covered() -> None:
    """Cas normal (couverture >= 120%) : AUCUN `RiskItem` ne doit etre
    cree."""
    tenant = Tenant.objects.create(code="FIN-INT3-2", name="Financing INT3 Tenant 2")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="fin-int3-2@example.com", password="Str0ngPassw0rd!23"
        )
        application = _application(tenant)
        add_guarantee(
            application,
            type=FinGuarantee.GUARANTEE_TYPE_MORTGAGE,
            estimated_value_mga=Decimal("8000000"),
        )
        add_guarantee(
            application,
            type=FinGuarantee.GUARANTEE_TYPE_PLEDGE,
            estimated_value_mga=Decimal("4200000"),
        )

        risk_item = flag_guarantee_coverage_risk(application, owner=user)

        assert risk_item is None
        assert RiskItem.objects.filter(tenant=tenant).count() == 0
