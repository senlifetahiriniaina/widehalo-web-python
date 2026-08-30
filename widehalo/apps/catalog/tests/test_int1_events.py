"""INT1 (chantier interactivite native inter-modules) : evenement
`catalog.variants_generated` (`services/variants.py::generate_variants`) et
action `catalog.notify_role_of_catalog_issue` enregistree dans
`core.services.automation_registry`."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group

from apps.catalog.models import Attribute, AttributeValue, ProductTemplate, UnitOfMeasure
from apps.catalog.services.variants import generate_variants, set_variant_attributes
from apps.core.models.event import EventLog
from apps.core.models.notification import Notification
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.services.automation_registry import get_registered_action
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def template_with_attributes():
    tenant = Tenant.objects.create(code="CAT-INT1-VAR", name="Catalog INT1 Variants Tenant")
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(
            tenant=tenant, name="T-Shirt", base_uom=uom, reference="TPL-INT1-0001"
        )
        color = Attribute.objects.create(tenant=tenant, name="Couleur")
        size = Attribute.objects.create(tenant=tenant, name="Taille")
        return tenant, template, color, size


def test_generate_variants_publishes_variants_generated(template_with_attributes) -> None:
    tenant, template, color, size = template_with_attributes
    with use_tenant(tenant.id):
        AttributeValue.objects.create(tenant=tenant, attribute=color, value="rouge")
        AttributeValue.objects.create(tenant=tenant, attribute=size, value="M")
        set_variant_attributes(template, [color.id, size.id])

        variants = generate_variants(template)
        assert len(variants) == 1

    event = EventLog.objects.get(event_type="catalog.variants_generated", tenant_id=str(tenant.id))
    assert event.payload["template_id"] == str(template.id)
    assert event.payload["count"] == 1
    assert event.payload["variant_ids"] == [str(variants[0].id)]


def test_generate_variants_without_attributes_does_not_publish(
    template_with_attributes,
) -> None:
    tenant, template, _color, _size = template_with_attributes
    with use_tenant(tenant.id):
        variants = generate_variants(template)
        assert variants == []

    assert not EventLog.objects.filter(
        event_type="catalog.variants_generated", tenant_id=str(tenant.id)
    ).exists()


def test_notify_role_of_catalog_issue_action_is_registered() -> None:
    action = get_registered_action("catalog.notify_role_of_catalog_issue")
    assert action is not None
    assert action.module == "catalog"


def test_notify_role_of_catalog_issue_action_notifies_role_members() -> None:
    tenant = Tenant.objects.create(code="CAT-INT1-NOTIF", name="Catalog INT1 Notify Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="cat-int1-notify@example.com", password="Str0ngPassw0rd!23"
        )
        group, _ = Group.objects.get_or_create(name="resp_production")
        user.groups.add(group)
        UserTenantMembership.objects.create(tenant=tenant, user=user)

        action = get_registered_action("catalog.notify_role_of_catalog_issue")
        assert action is not None
        action.function(
            str(tenant.id),
            {"role_code": "resp_production", "note": "Anomalie de referentiel"},
        )

        assert Notification.objects.filter(
            user=user, notification_type="catalog.automation_alert"
        ).exists()
