"""Bloc E, E3 (PAY-4) : disclosure des bulletins/lignes/versions dans
`templates/payroll/hr_dashboard.html` (`apps/payroll/views.py::
hr_dashboard`) — pas de nouvel ecran (budget d'ecrans quasi epuise,
238/240, cf. `apps/payroll/views.py` docstring de module), gate par role
exactement comme la colonne « Masse nette » deja existante."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.test import Client
from django_otp.oath import totp

from apps.core.models.audit import AuditLog
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services import mfa as mfa_service
from apps.core.tests.utils import use_tenant
from apps.payroll.models import PayPayslip
from apps.payroll.services.payslip import compute_payslip
from apps.payroll.tests.factories import (
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
)
from apps.presence.tests.factories import PrsEmployeeFactory

pytestmark = pytest.mark.django_db


def _staff_client(tenant: Tenant, *, role: str = "rh") -> tuple[Client, User]:
    """`role` (rh/admin/direction) appartient a `settings.
    CORE_MFA_REQUIRED_ROLES` — un simple `force_login` ne suffit pas
    (`MFAEnforcementMiddleware` redirigerait vers `/mfa/`, cf.
    `apps.core.tests.test_mfa_web._logged_in_client`, meme patron repris
    ici a l'identique) : connexion reelle via `/login/`, puis
    enrolement + verification TOTP pour marquer la SESSION verifiee."""
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


def _employee_client(tenant: Tenant, employee_id) -> Client:
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


def _computed_payslip(tenant: Tenant, employee_id) -> PayPayslip:
    contract = make_active_contract(tenant, employee_id=employee_id, wage_base=Decimal("1200000"))
    period = make_period(tenant)
    payslip = PayPayslip.objects.create(
        tenant=tenant,
        employee_id=employee_id,
        contract=contract,
        period=period,
        date_from=period.date_from,
        date_to=period.date_to,
    )
    compute_payslip(payslip)
    # Recharge depuis la base : le calcul en memoire peut porter plus de
    # decimales que la colonne DECIMAL(18,4) n'en retiendra une fois
    # persistee — le rendu template lit toujours une instance rechargee
    # depuis la base (nouvelle requete cote vue), jamais celle-ci.
    payslip.refresh_from_db()
    return payslip


def test_staff_role_sees_payslip_lines_and_regulatory_parameter_versions() -> None:
    tenant = Tenant.objects.create(code="PAY-E3-HR1", name="E3 HR staff view")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        _computed_payslip(tenant, employee_id)
        client, _user = _staff_client(tenant)

    response = client.get("/payroll/")
    content = response.content.decode()

    assert response.status_code == 200
    assert str(employee_id) in content
    assert "SAL_BASE" in content
    # Partie entiere seulement : `net_to_pay` (EncryptedDecimalField, cf.
    # apps.core.db.fields) n'est jamais quantifie a `decimal_places` au
    # rond-trip base — comparer la representation Decimal EXACTE serait
    # fragile (precision accumulee par le calcul, non garantie stable).
    assert "1033300" in content
    assert "payroll.cnaps_rate v1" in content


def test_non_staff_role_never_sees_payslip_lines_or_versions() -> None:
    """Meme discipline que la colonne « Masse nette » deja masquee : un
    role hors rh/admin/direction ne voit ni la liste des bulletins ni
    aucune version de parametre — pas seulement les montants."""
    tenant = Tenant.objects.create(code="PAY-E3-HR2", name="E3 HR employee view")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        _computed_payslip(tenant, employee_id)
        client = _employee_client(tenant, employee_id)

    response = client.get("/payroll/")
    content = response.content.decode()

    assert response.status_code == 200
    # `str(employee_id)` n'est PAS verifie ici : il apparait legitimement
    # dans l'email de l'utilisateur connecte lui-meme
    # (`emp-<employee_id>@example.com`, affiche par le menu de compte de
    # `base.html`) — sans rapport avec une fuite de detail de bulletin.
    assert "1033300" not in content
    assert "payroll.cnaps_rate" not in content
    assert "Bulletins (" not in content


def test_staff_view_logs_pii_access_per_payslip_shown() -> None:
    tenant = Tenant.objects.create(code="PAY-E3-HR3", name="E3 HR PII log")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        employee_id = uuid.uuid4()
        payslip = _computed_payslip(tenant, employee_id)
        client, user = _staff_client(tenant)

        assert not AuditLog.objects.filter(
            tenant_id=tenant.id, action=AuditLog.ACTION_PII_ACCESS
        ).exists()

        client.get("/payroll/")

        log = AuditLog.objects.get(tenant_id=tenant.id, action=AuditLog.ACTION_PII_ACCESS)
        assert log.actor_id == user.id
        assert str(log.object_id) == str(payslip.id)
        assert set(log.metadata["fields"]) == {"gross", "net_to_pay"}
