from __future__ import annotations

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.partners.models import Partner
from django.test import Client

pytestmark = pytest.mark.django_db


def test_two_step_wizard_creates_a_partner_without_full_page_reload() -> None:
    tenant = Tenant.objects.create(code="UI-WIZ", name="UI Wizard Tenant")
    user = User.objects.create_user(email="ui-wiz@example.com", password="Str0ngPassw0rd!23")
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    step1 = client.post("/partners/new/", {"step": "1", "name": "Wizard Partner", "nif": "NIF-WIZ"})
    assert step1.status_code == 200
    assert "Étape 2" in step1.content.decode()

    with use_tenant(tenant.id):
        assert not Partner.objects.filter(name="Wizard Partner").exists()

    step2 = client.post(
        "/partners/new/",
        {"step": "2", "roles": ["client"], "credit_limit_mga": "50000"},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert step2.status_code == 302

    with use_tenant(tenant.id):
        assert Partner.objects.filter(name="Wizard Partner").exists()
