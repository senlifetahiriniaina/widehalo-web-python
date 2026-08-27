from __future__ import annotations

from decimal import Decimal

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.partners.models import DuplicateAlert
from apps.partners.services.onboarding import create_partner
from django.test import Client

pytestmark = pytest.mark.django_db


def _login_with_tenant(tenant: Tenant, user: User) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_duplicate_alert_list_and_resolve() -> None:
    tenant = Tenant.objects.create(code="UI-DUP", name="UI Duplicate Tenant")
    user = User.objects.create_user(email="ui-dup@example.com", password="Str0ngPassw0rd!23")
    client = _login_with_tenant(tenant, user)

    with use_tenant(tenant.id):
        first = create_partner(tenant=tenant, name="Alpha SARL", roles=["client"], nif="NIF-DUP")
        create_partner(tenant=tenant, name="Alpha Bis SARL", roles=["client"], nif="NIF-DUP")
        alert = DuplicateAlert.objects.get()

    response = client.get("/partners/duplicates/")
    assert response.status_code == 200
    assert "Alpha SARL" in response.content.decode()

    resolve = client.post("/partners/duplicates/", {"alert_id": str(alert.id)})
    assert resolve.status_code == 302

    with use_tenant(tenant.id):
        alert.refresh_from_db()
        assert alert.resolved_at is not None
    assert first.name == "Alpha SARL"


def test_merge_partners_screen() -> None:
    tenant = Tenant.objects.create(code="UI-MRG", name="UI Merge Tenant")
    user = User.objects.create_user(email="ui-mrg@example.com", password="Str0ngPassw0rd!23")
    client = _login_with_tenant(tenant, user)

    with use_tenant(tenant.id):
        primary = create_partner(tenant=tenant, name="Primaire SARL", roles=["client"])
        duplicate = create_partner(tenant=tenant, name="Doublon SARL", roles=["client"])

    form_response = client.get(f"/partners/merge/?primary={primary.id}&duplicate={duplicate.id}")
    assert form_response.status_code == 200
    assert "Doublon SARL" in form_response.content.decode()

    response = client.post(
        "/partners/merge/",
        {"primary_id": str(primary.id), "duplicate_id": str(duplicate.id)},
    )
    assert response.status_code == 302
    assert response.url == f"/partners/{primary.id}/"

    with use_tenant(tenant.id):
        duplicate.refresh_from_db()
        assert duplicate.merged_into_id == primary.id
        assert duplicate.is_active is False


def test_merge_rejects_identical_primary_and_duplicate() -> None:
    tenant = Tenant.objects.create(code="UI-MRG2", name="UI Merge Tenant 2")
    user = User.objects.create_user(email="ui-mrg2@example.com", password="Str0ngPassw0rd!23")
    client = _login_with_tenant(tenant, user)

    with use_tenant(tenant.id):
        partner = create_partner(tenant=tenant, name="Solo SARL", roles=["client"])

    response = client.post(
        "/partners/merge/",
        {"primary_id": str(partner.id), "duplicate_id": str(partner.id)},
    )
    assert response.status_code == 200
    assert "differer" in response.content.decode()


def test_partner_edit_updates_credit_limit() -> None:
    tenant = Tenant.objects.create(code="UI-EDT", name="UI Edit Tenant")
    user = User.objects.create_user(email="ui-edt@example.com", password="Str0ngPassw0rd!23")
    client = _login_with_tenant(tenant, user)

    with use_tenant(tenant.id):
        partner = create_partner(tenant=tenant, name="Editable SARL", roles=["client"])

    response = client.post(
        f"/partners/{partner.id}/edit/",
        {
            "name": "Editable SARL Renommee",
            "nif": "NIF-EDT",
            "roles": ["client", "supplier"],
            "credit_limit_mga": "150000",
        },
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        partner.refresh_from_db()
        assert partner.name == "Editable SARL Renommee"
        assert partner.credit_limit_mga == Decimal("150000")
        assert set(partner.roles) == {"client", "supplier"}
