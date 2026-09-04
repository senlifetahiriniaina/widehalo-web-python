from __future__ import annotations

import uuid

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.purchase.services.substitution import create_substitute
from django.contrib.auth.models import Group
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def purchase_config_setup():
    tenant = Tenant.objects.create(code="UI-PUR-CFG", name="UI Purchase Config Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="ui-pur-cfg@example.com", password="Str0ngPassw0rd!23"
        )
        user.groups.add(Group.objects.get_or_create(name="acheteur")[0])
        variant_id = uuid.uuid4()
        degraded = create_substitute(
            tenant=tenant,
            variant_id=variant_id,
            substitute_variant_id=uuid.uuid4(),
            compatibility="degrade",
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, user, variant_id, degraded


def test_config_index_screen_renders(purchase_config_setup) -> None:
    client, *_ = purchase_config_setup
    response = client.get("/purchase/config/")
    assert response.status_code == 200


def test_create_reordering_rule_via_screen(purchase_config_setup) -> None:
    client, *_ = purchase_config_setup
    response = client.post(
        "/purchase/config/reordering-rules/",
        {"variant_id": str(uuid.uuid4()), "min_qty": "5", "max_qty": "20", "multiple_qty": "1"},
    )
    assert response.status_code == 302
    listing = client.get("/purchase/config/reordering-rules/")
    assert listing.status_code == 200


def test_substitute_list_filter_and_approve_degrade_flow(purchase_config_setup) -> None:
    """RG-PUR-2 (acceptance test §5.6.7 n°1/n°2) : un substitut `degrade`
    apparait dans la liste sans etre approuve, et le bouton "Valider"
    l'approuve reellement (`approved_by` renseigne)."""
    client, tenant, _user, variant_id, degraded = purchase_config_setup

    listing = client.get(f"/purchase/config/substitutes/?variant_id={variant_id}")
    assert listing.status_code == 200
    assert str(degraded.substitute_variant_id).encode() in listing.content

    response = client.post(
        "/purchase/config/substitutes/",
        {"action": "approve", "substitute_id": str(degraded.id)},
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        degraded.refresh_from_db()
        assert degraded.approved_by_id is not None


def test_create_substitute_via_screen(purchase_config_setup) -> None:
    client, *_ = purchase_config_setup
    response = client.post(
        "/purchase/config/substitutes/",
        {
            "action": "create",
            "variant_id": str(uuid.uuid4()),
            "substitute_variant_id": str(uuid.uuid4()),
            "compatibility": "equivalent",
            "ratio": "1",
        },
    )
    assert response.status_code == 302
