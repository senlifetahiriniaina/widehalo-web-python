from __future__ import annotations

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client
from django_otp.oath import totp

from apps.accounting.models import AccPartnerRoleAccount
from apps.accounting.tests.factories import AccAccountFactory
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services import mfa as mfa_service
from apps.core.tests.utils import use_tenant
from apps.partners.services.onboarding import create_partner

pytestmark = pytest.mark.django_db


def _login_with_tenant(tenant: Tenant, user: User) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def _login_with_tenant_mfa_verified(tenant: Tenant, user: User) -> Client:
    client = _login_with_tenant(tenant, user)
    device = mfa_service.enroll_device(user)
    token = str(totp(device.bin_key)).zfill(6)
    response = client.post("/mfa/", {"token": token})
    assert response.status_code == 302, response.content
    return client


def test_assign_account_forbidden_for_commercial_role() -> None:
    """`commercial` a `partners.change_partner` mais pas
    `accounting.manage_partneraccountassignment` — l'assignation reste
    reservee a comptable/admin/direction (PT2)."""
    tenant = Tenant.objects.create(code="PT3-1", name="PT3 Tenant 1")
    user = User.objects.create_user(email="pt3-1@example.com", password="Str0ngPassw0rd!23")
    call_command("load_roles")
    user.groups.add(Group.objects.get(name="commercial"))
    client = _login_with_tenant(tenant, user)

    with use_tenant(tenant.id):
        partner = create_partner(tenant=tenant, name="PT3 SARL", roles=["client"])
        account = AccAccountFactory(tenant=tenant)

    response = client.post(
        f"/partners/{partner.id}/assign-account/",
        {"role": "client", "account_id": str(account.id)},
    )
    assert response.status_code == 403


def test_assign_account_succeeds_for_comptable_role() -> None:
    tenant = Tenant.objects.create(code="PT3-2", name="PT3 Tenant 2")
    user = User.objects.create_user(email="pt3-2@example.com", password="Str0ngPassw0rd!23")
    call_command("load_roles")
    user.groups.add(Group.objects.get(name="comptable"))
    client = _login_with_tenant_mfa_verified(tenant, user)

    with use_tenant(tenant.id):
        partner = create_partner(tenant=tenant, name="PT3 SARL 2", roles=["client"])
        account = AccAccountFactory(tenant=tenant)

    response = client.post(
        f"/partners/{partner.id}/assign-account/",
        {"role": "client", "account_id": str(account.id)},
    )
    assert response.status_code == 302
    assert response.url == f"/partners/{partner.id}/"

    with use_tenant(tenant.id):
        mapping = AccPartnerRoleAccount.objects.get(partner_id=partner.id, role="client")
        assert mapping.account_id == account.id
