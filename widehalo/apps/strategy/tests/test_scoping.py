from __future__ import annotations

import datetime

import pytest
from django.core.exceptions import PermissionDenied

from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import grant_role, use_tenant
from apps.presence.services.employees import create_department
from apps.strategy.models import StgObjective
from apps.strategy.services.objectives import create_objective
from apps.strategy.services.scoping import assert_can_manage_level, scope_objectives_for_user

pytestmark = pytest.mark.django_db


def test_admin_and_direction_see_all_objectives() -> None:
    tenant = Tenant.objects.create(code="STG-SC1", name="Scoping Tenant 1")
    with use_tenant(tenant.id):
        admin = UserFactory()
        grant_role(admin, "admin")
        other_user = UserFactory()
        objective = create_objective(
            tenant,
            title="Objectif quelconque",
            level=StgObjective.LEVEL_INDIVIDUAL,
            owner=other_user,
            created_by=other_user,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        visible = scope_objectives_for_user(
            StgObjective.objects.filter(is_active=True), admin, tenant
        )
        assert objective in visible


def test_collaborateur_sees_only_own_or_owned_objectives() -> None:
    tenant = Tenant.objects.create(code="STG-SC2", name="Scoping Tenant 2")
    with use_tenant(tenant.id):
        collaborateur = UserFactory()
        grant_role(collaborateur, "collaborateur")
        colleague = UserFactory()

        own_objective = create_objective(
            tenant,
            title="Mon objectif",
            level=StgObjective.LEVEL_INDIVIDUAL,
            owner=collaborateur,
            created_by=collaborateur,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        colleague_objective = create_objective(
            tenant,
            title="Objectif du collegue",
            level=StgObjective.LEVEL_INDIVIDUAL,
            owner=colleague,
            created_by=colleague,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )

        visible = scope_objectives_for_user(
            StgObjective.objects.filter(is_active=True), collaborateur, tenant
        )
        assert own_objective in visible
        assert colleague_objective not in visible


def test_department_head_sees_own_department_objectives_only() -> None:
    tenant = Tenant.objects.create(code="STG-SC3", name="Scoping Tenant 3")
    with use_tenant(tenant.id):
        head = UserFactory()
        grant_role(head, "resp_commercial")
        other_head = UserFactory()
        grant_role(other_head, "resp_commercial")

        own_department = create_department(tenant, code="COM", name="Commercial", manager=head)
        other_department = create_department(tenant, code="ACH", name="Achats", manager=other_head)

        own_department_objective = create_objective(
            tenant,
            title="Objectif departement commercial",
            level=StgObjective.LEVEL_DEPARTMENT,
            department_id=own_department.id,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )
        other_department_objective = create_objective(
            tenant,
            title="Objectif departement achats",
            level=StgObjective.LEVEL_DEPARTMENT,
            department_id=other_department.id,
            period_start=datetime.date(2026, 1, 1),
            period_end=datetime.date(2026, 12, 31),
        )

        visible = scope_objectives_for_user(
            StgObjective.objects.filter(is_active=True), head, tenant
        )
        assert own_department_objective in visible
        assert other_department_objective not in visible

        assert_can_manage_level(
            head,
            level=StgObjective.LEVEL_DEPARTMENT,
            department_id=own_department.id,
            tenant=tenant,
        )
        with pytest.raises(PermissionDenied):
            assert_can_manage_level(
                head,
                level=StgObjective.LEVEL_DEPARTMENT,
                department_id=other_department.id,
                tenant=tenant,
            )


def test_collaborateur_cannot_create_company_objective() -> None:
    tenant = Tenant.objects.create(code="STG-SC4", name="Scoping Tenant 4")
    with use_tenant(tenant.id):
        collaborateur = UserFactory()
        grant_role(collaborateur, "collaborateur")
        with pytest.raises(PermissionDenied):
            assert_can_manage_level(
                collaborateur, level=StgObjective.LEVEL_COMPANY, department_id=None, tenant=tenant
            )
