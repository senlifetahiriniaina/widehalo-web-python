"""Tests du service `apps.core.services.quality` (QLT1-2) : calcul de
`passed` derive de `results`, notification des roles pertinents en cas
d'echec."""

from __future__ import annotations

import datetime

import pytest

from apps.core.models.notification import Notification
from apps.core.services.quality import (
    FAILURE_NOTIFICATION_ROLES,
    create_checklist_template,
    create_inspection,
    list_inspections_for,
)
from apps.core.tests.factories import TenantFactory, UserFactory
from apps.core.tests.utils import grant_role, use_tenant

pytestmark = pytest.mark.django_db


def test_create_inspection_passes_when_no_nonconformity() -> None:
    tenant = TenantFactory()
    inspector = UserFactory()

    with use_tenant(tenant.id):
        template = create_checklist_template(
            tenant=tenant,
            name="Controle couture",
            items=[{"code": "C1", "label": "Solidite", "expected": "OK"}],
        )
        inspection = create_inspection(
            tenant=tenant,
            template=template,
            inspector=inspector,
            results=[{"code": "C1", "status": "conforme", "comment": ""}],
            inspected_at=datetime.datetime.now(tz=datetime.UTC),
        )

    assert inspection.passed is True


def test_create_inspection_observation_alone_does_not_fail() -> None:
    tenant = TenantFactory()
    inspector = UserFactory()

    with use_tenant(tenant.id):
        template = create_checklist_template(tenant=tenant, name="Controle")
        inspection = create_inspection(
            tenant=tenant,
            template=template,
            inspector=inspector,
            results=[{"code": "C1", "status": "observation", "comment": "RAS"}],
            inspected_at=datetime.datetime.now(tz=datetime.UTC),
        )

    assert inspection.passed is True


def test_create_inspection_fails_when_any_nonconformity() -> None:
    tenant = TenantFactory()
    inspector = UserFactory()

    with use_tenant(tenant.id):
        template = create_checklist_template(tenant=tenant, name="Controle")
        inspection = create_inspection(
            tenant=tenant,
            template=template,
            inspector=inspector,
            results=[
                {"code": "C1", "status": "conforme", "comment": ""},
                {"code": "C2", "status": "non_conforme", "comment": "Defaut"},
            ],
            inspected_at=datetime.datetime.now(tz=datetime.UTC),
        )

    assert inspection.passed is False


def test_create_inspection_failure_notifies_relevant_roles() -> None:
    tenant = TenantFactory()
    inspector = UserFactory()
    resp_production = UserFactory()
    direction = UserFactory()
    grant_role(resp_production, "resp_production")
    grant_role(direction, "direction")

    with use_tenant(tenant.id):
        from apps.core.models.user import UserTenantMembership

        UserTenantMembership.objects.create(tenant=tenant, user=resp_production)
        UserTenantMembership.objects.create(tenant=tenant, user=direction)

        template = create_checklist_template(tenant=tenant, name="Controle")
        create_inspection(
            tenant=tenant,
            template=template,
            inspector=inspector,
            results=[{"code": "C1", "status": "non_conforme", "comment": ""}],
            inspected_at=datetime.datetime.now(tz=datetime.UTC),
        )

    assert set(FAILURE_NOTIFICATION_ROLES) == {"resp_production", "direction"}
    assert Notification.objects.filter(
        user=resp_production, notification_type="quality.inspection_failed"
    ).exists()
    assert Notification.objects.filter(
        user=direction, notification_type="quality.inspection_failed"
    ).exists()


def test_create_inspection_success_does_not_notify() -> None:
    tenant = TenantFactory()
    inspector = UserFactory()
    resp_production = UserFactory()
    grant_role(resp_production, "resp_production")

    with use_tenant(tenant.id):
        from apps.core.models.user import UserTenantMembership

        UserTenantMembership.objects.create(tenant=tenant, user=resp_production)

        template = create_checklist_template(tenant=tenant, name="Controle")
        create_inspection(
            tenant=tenant,
            template=template,
            inspector=inspector,
            results=[{"code": "C1", "status": "conforme", "comment": ""}],
            inspected_at=datetime.datetime.now(tz=datetime.UTC),
        )

    assert not Notification.objects.filter(
        user=resp_production, notification_type="quality.inspection_failed"
    ).exists()


def test_list_inspections_for_filters_by_content_object() -> None:
    tenant = TenantFactory()
    inspector = UserFactory()

    with use_tenant(tenant.id):
        template = create_checklist_template(tenant=tenant, name="Controle")
        target = TenantFactory()
        other = TenantFactory()
        create_inspection(
            tenant=tenant,
            template=template,
            inspector=inspector,
            results=[{"code": "C1", "status": "conforme", "comment": ""}],
            inspected_at=datetime.datetime.now(tz=datetime.UTC),
            content_object=target,
        )
        create_inspection(
            tenant=tenant,
            template=template,
            inspector=inspector,
            results=[{"code": "C1", "status": "conforme", "comment": ""}],
            inspected_at=datetime.datetime.now(tz=datetime.UTC),
            content_object=other,
        )

        for_target = list(list_inspections_for(target))

    assert len(for_target) == 1
