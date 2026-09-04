"""WA-5 (cahier Phase 2 §13.4) : plafond de coût mensuel PAR TENANT."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.core.models.notification import WhatsAppMessage
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.whatsapp.services.usage import (
    check_budget,
    current_month_cost_ariary,
    is_alert_threshold_exceeded,
    remaining_budget_ariary,
)

pytestmark = pytest.mark.django_db


def _outbound_message(tenant: Tenant, cost: Decimal) -> WhatsAppMessage:
    return WhatsAppMessage.objects.create(
        tenant_id=tenant.id,
        direction=WhatsAppMessage.DIRECTION_OUTBOUND,
        phone_number="+261340000099",
        status=WhatsAppMessage.STATUS_SENT,
        cost_ariary=cost,
    )


def test_no_cap_configured_never_blocks() -> None:
    tenant = Tenant.objects.create(code="WA-U1", name="WhatsApp Usage Tenant 1")
    with use_tenant(tenant.id):
        assert tenant.whatsapp_monthly_cost_cap_ariary is None
        assert check_budget(tenant, additional_cost_ariary=Decimal("999999")) is True
        assert remaining_budget_ariary(tenant) is None


def test_current_month_cost_sums_outbound_messages_only() -> None:
    tenant = Tenant.objects.create(code="WA-U2", name="WhatsApp Usage Tenant 2")
    with use_tenant(tenant.id):
        _outbound_message(tenant, Decimal("100"))
        _outbound_message(tenant, Decimal("50"))
        WhatsAppMessage.objects.create(
            tenant_id=tenant.id,
            direction=WhatsAppMessage.DIRECTION_INBOUND,
            phone_number="+261340000099",
            status=WhatsAppMessage.STATUS_RECEIVED,
            cost_ariary=Decimal("9999"),
        )
        assert current_month_cost_ariary(tenant) == Decimal("150")


def test_check_budget_blocks_once_cap_reached_with_hard_stop() -> None:
    tenant = Tenant.objects.create(code="WA-U3", name="WhatsApp Usage Tenant 3")
    tenant.whatsapp_monthly_cost_cap_ariary = Decimal("100")
    tenant.whatsapp_cost_cap_hard_stop = True
    tenant.save(update_fields=["whatsapp_monthly_cost_cap_ariary", "whatsapp_cost_cap_hard_stop"])
    with use_tenant(tenant.id):
        _outbound_message(tenant, Decimal("90"))
        assert check_budget(tenant, additional_cost_ariary=Decimal("5")) is True
        assert check_budget(tenant, additional_cost_ariary=Decimal("20")) is False


def test_check_budget_never_blocks_when_hard_stop_disabled() -> None:
    tenant = Tenant.objects.create(code="WA-U4", name="WhatsApp Usage Tenant 4")
    tenant.whatsapp_monthly_cost_cap_ariary = Decimal("100")
    tenant.whatsapp_cost_cap_hard_stop = False
    tenant.save(update_fields=["whatsapp_monthly_cost_cap_ariary", "whatsapp_cost_cap_hard_stop"])
    with use_tenant(tenant.id):
        _outbound_message(tenant, Decimal("500"))
        assert check_budget(tenant, additional_cost_ariary=Decimal("1000")) is True


def test_remaining_budget_can_go_negative_when_over_cap() -> None:
    tenant = Tenant.objects.create(code="WA-U5", name="WhatsApp Usage Tenant 5")
    tenant.whatsapp_monthly_cost_cap_ariary = Decimal("100")
    tenant.save(update_fields=["whatsapp_monthly_cost_cap_ariary"])
    with use_tenant(tenant.id):
        _outbound_message(tenant, Decimal("150"))
        assert remaining_budget_ariary(tenant) == Decimal("-50")


def test_alert_threshold_exceeded() -> None:
    tenant = Tenant.objects.create(code="WA-U6", name="WhatsApp Usage Tenant 6")
    tenant.whatsapp_monthly_cost_cap_ariary = Decimal("100")
    tenant.whatsapp_cost_alert_threshold_pct = 80
    tenant.save(
        update_fields=["whatsapp_monthly_cost_cap_ariary", "whatsapp_cost_alert_threshold_pct"]
    )
    with use_tenant(tenant.id):
        _outbound_message(tenant, Decimal("70"))
        assert is_alert_threshold_exceeded(tenant) is False

        _outbound_message(tenant, Decimal("15"))
        assert is_alert_threshold_exceeded(tenant) is True
