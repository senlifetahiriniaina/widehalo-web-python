"""Helpers de test du module `payroll`. Les tests de CALCUL (RG-PAY-1..5,
acceptance §5.10.10) construisent leurs objets explicitement — plus lisible
pour un montant verifie a la main, meme choix que `apps.accounting.tests`.
Les factories `factory_boy` ci-dessous (une par des 11 modeles concrets du
module) existent pour satisfaire T1 (`apps.core.tests.
test_tenant_portability_per_entity`, round-trip export/import generique) —
utilisees SEULEMENT par ce garde-fou transversal, pas par les tests de
calcul de ce module."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import factory
from django.contrib.auth.models import Group
from django.test import Client
from django_otp.oath import totp

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services import mfa as mfa_service
from apps.payroll.models import (
    PayAdvance,
    PayBatch,
    PayContract,
    PayContractBenefit,
    PayContractType,
    PayDeclaration,
    PayPayslip,
    PayPayslipLine,
    PayPeriod,
    PaySalaryRule,
    PaySalaryStructure,
)
from apps.payroll.services.seed import seed_payroll_regulatory_params
from apps.payroll.services.structures import load_madagascar_structure
from apps.presence.tests.factories import PrsEmployeeFactory


def setup_payroll_reference_data(tenant: Tenant) -> None:
    seed_payroll_regulatory_params(tenant)
    load_madagascar_structure(tenant)


def staff_client(tenant: Tenant, *, role: str = "rh") -> tuple[Client, User]:
    """Client HTTP connecte comme membre d'un role soumis a MFA obligatoire
    (`rh`/`admin`/`direction` appartiennent a `settings.
    CORE_MFA_REQUIRED_ROLES`) — un simple `force_login` ne suffit pas
    (`MFAEnforcementMiddleware` redirigerait vers `/mfa/`) : connexion
    reelle via `/login/`, puis enrolement + verification TOTP pour marquer
    la SESSION verifiee, meme patron que `apps.core.tests.test_mfa_web.
    _logged_in_client`."""
    user = User.objects.create_user(email=f"{role}@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name=role)
    user.groups.add(group)
    client = Client()
    response = client.post("/login/", {"email": user.email, "password": "Str0ngPassw0rd!23"})
    assert response.status_code == 302, response.content

    device = mfa_service.enroll_device(user)
    device.confirmed = True
    device.save(update_fields=["confirmed"])
    token = str(totp(device.bin_key)).zfill(6)
    verify_response = client.post("/mfa/", {"token": token})
    assert verify_response.status_code == 302, verify_response.content

    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, user


def employee_client(tenant: Tenant, employee_id: uuid.UUID) -> Client:
    """Client HTTP connecte comme un simple employe (aucun role
    `CORE_MFA_REQUIRED_ROLES` — jamais soumis a MFA)."""
    user = User.objects.create_user(
        email=f"emp-{employee_id}@example.com", password="Str0ngPassw0rd!23"
    )
    PrsEmployeeFactory(tenant=tenant, id=employee_id, user=user)
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def make_contract_type(tenant: Tenant, *, code: str = "CDI") -> PayContractType:
    return PayContractType.objects.create(
        tenant=tenant, code=code, name="CDI", category=PayContractType.CATEGORY_CDI
    )


def make_period(
    tenant: Tenant,
    *,
    code: str = "2026-03",
    date_from: dt.date = dt.date(2026, 3, 1),
    date_to: dt.date = dt.date(2026, 3, 31),
    payment_date: dt.date = dt.date(2026, 3, 31),
) -> PayPeriod:
    return PayPeriod.objects.create(
        tenant=tenant, code=code, date_from=date_from, date_to=date_to, payment_date=payment_date
    )


def make_active_contract(
    tenant: Tenant,
    *,
    employee_id,
    wage_base: Decimal,
    date_start: dt.date = dt.date(2020, 1, 1),
) -> PayContract:
    from apps.payroll.models import PaySalaryStructure

    contract_type = PayContractType.objects.filter(
        tenant=tenant, code="CDI"
    ).first() or make_contract_type(tenant)
    structure = PaySalaryStructure.objects.get(tenant=tenant, code="MG_BASE")
    contract = PayContract.objects.create(
        tenant=tenant,
        employee_id=employee_id,
        type=contract_type,
        date_start=date_start,
        wage_base=wage_base,
        salary_structure=structure,
    )
    contract.state = PayContract.STATE_ACTIVE
    contract.save(update_fields=["state"])
    return contract


class PayContractTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PayContractType

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"CTYPE-{n}")
    name = "CDI"
    category = PayContractType.CATEGORY_CDI


class PaySalaryStructureFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PaySalaryStructure

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"STRUCT-{n}")
    name = "Structure de test"
    country = "MG"


class PaySalaryRuleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PaySalaryRule

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    structure = factory.SubFactory(
        PaySalaryStructureFactory, tenant=factory.SelfAttribute("..tenant")
    )
    sequence = 10
    code = factory.Sequence(lambda n: f"RULE-{n}")
    name = "Regle de test"
    category = PaySalaryRule.CATEGORY_BASE
    amount_type = PaySalaryRule.AMOUNT_FIXED
    amount = "0"


class PayContractFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PayContract

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    reference = factory.Sequence(lambda n: f"PAYC-2026-{n:04d}")
    employee_id = factory.LazyFunction(uuid.uuid4)
    type = factory.SubFactory(PayContractTypeFactory, tenant=factory.SelfAttribute("..tenant"))
    date_start = dt.date(2026, 1, 1)
    wage_base = Decimal("1000000")
    salary_structure = factory.SubFactory(
        PaySalaryStructureFactory, tenant=factory.SelfAttribute("..tenant")
    )


class PayContractBenefitFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PayContractBenefit

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    contract = factory.SubFactory(PayContractFactory, tenant=factory.SelfAttribute("..tenant"))
    type = PayContractBenefit.TYPE_TRANSPORT
    amount = Decimal("20000")


class PayPeriodFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PayPeriod

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"2026-{(n % 12) + 1:02d}")
    date_from = dt.date(2026, 3, 1)
    date_to = dt.date(2026, 3, 31)
    payment_date = dt.date(2026, 3, 31)


class PayPayslipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PayPayslip

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    reference = factory.Sequence(lambda n: f"BULL-2026-{n:04d}")
    employee_id = factory.LazyFunction(uuid.uuid4)
    contract = factory.SubFactory(PayContractFactory, tenant=factory.SelfAttribute("..tenant"))
    period = factory.SubFactory(PayPeriodFactory, tenant=factory.SelfAttribute("..tenant"))
    date_from = dt.date(2026, 3, 1)
    date_to = dt.date(2026, 3, 31)


class PayPayslipLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PayPayslipLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    payslip = factory.SubFactory(PayPayslipFactory, tenant=factory.SelfAttribute("..tenant"))
    sequence = 10
    code = "BRUT"
    label = "Salaire brut"
    category = PaySalaryRule.CATEGORY_GROSS
    amount = Decimal("1000000")


class PayBatchFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PayBatch

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    reference = factory.Sequence(lambda n: f"LOT-2026-{n:04d}")
    period = factory.SubFactory(PayPeriodFactory, tenant=factory.SelfAttribute("..tenant"))


class PayDeclarationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PayDeclaration

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    reference = factory.Sequence(lambda n: f"DECL-2026-{n:04d}")
    period = factory.SubFactory(PayPeriodFactory, tenant=factory.SelfAttribute("..tenant"))
    type = PayDeclaration.TYPE_IRSA


class PayAdvanceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PayAdvance

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    reference = factory.Sequence(lambda n: f"AVAN-2026-{n:04d}")
    employee_id = factory.LazyFunction(uuid.uuid4)
    date = dt.date(2026, 3, 1)
    amount = Decimal("100000")
