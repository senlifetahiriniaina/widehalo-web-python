"""Factories factory_boy pour les modeles du module `pos`."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import factory
from django.utils import timezone

from apps.pos.models import (
    PosCashMovement,
    PosOrder,
    PosOrderLine,
    PosPayment,
    PosPaymentMethod,
    PosRegister,
    PosSession,
    PosSyncLog,
)


class PosRegisterFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PosRegister

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"CAISSE-{n}")
    name = factory.Sequence(lambda n: f"Caisse {n}")


class PosPaymentMethodFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PosPaymentMethod

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"PAY-{n}")
    name = factory.Sequence(lambda n: f"Moyen {n}")
    type = PosPaymentMethod.TYPE_CASH
    default_account_type = PosPaymentMethod.ACCOUNT_TYPE_CASH


class PosSessionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PosSession

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    register = factory.SubFactory(PosRegisterFactory, tenant=factory.SelfAttribute("..tenant"))
    cashier = factory.SubFactory("apps.core.tests.factories.UserFactory")
    opened_at = factory.LazyFunction(timezone.now)
    opening_cash_amount = Decimal("0")


class PosCashMovementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PosCashMovement

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    session = factory.SubFactory(PosSessionFactory, tenant=factory.SelfAttribute("..tenant"))
    direction = PosCashMovement.DIRECTION_IN
    amount = Decimal("1000")
    reason = "Appoint"


class PosOrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PosOrder

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    session = factory.SubFactory(PosSessionFactory, tenant=factory.SelfAttribute("..tenant"))
    register = factory.SelfAttribute("session.register")
    client_uuid = factory.LazyFunction(uuid.uuid4)
    local_sequence = factory.Sequence(lambda n: n + 1)


class PosOrderLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PosOrderLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    order = factory.SubFactory(PosOrderFactory, tenant=factory.SelfAttribute("..tenant"))
    description = "Article"
    qty = Decimal("1")
    unit_price = Decimal("1000")
    subtotal = Decimal("1000")
    total = Decimal("1000")


class PosPaymentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PosPayment

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    order = factory.SubFactory(PosOrderFactory, tenant=factory.SelfAttribute("..tenant"))
    method = factory.SubFactory(PosPaymentMethodFactory, tenant=factory.SelfAttribute("..tenant"))
    amount = Decimal("1000")
    received_at = factory.LazyFunction(timezone.now)


class PosSyncLogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PosSyncLog

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    register = factory.SubFactory(PosRegisterFactory, tenant=factory.SelfAttribute("..tenant"))
    client_uuid = factory.LazyFunction(uuid.uuid4)
    outcome = PosSyncLog.OUTCOME_ACCEPTED
    synced_at = factory.LazyFunction(timezone.now)
