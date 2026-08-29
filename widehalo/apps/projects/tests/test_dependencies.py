"""Tests de `services/dependencies.py` (PJ2) — creation de dependance et
detection de cycle (differenciateur documente au plan comme absent
d'Asana/Monday/Jira/ClickUp)."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.core.tests.utils import use_tenant
from apps.projects.models import PrjTaskDependency
from apps.projects.services.dependencies import add_dependency
from apps.projects.services.projects import create_project
from apps.projects.services.tasks import create_task

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant_project(db):
    from apps.core.tests.factories import TenantFactory

    tenant = TenantFactory()
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet dependances")
    return tenant, project


def test_add_dependency_creates_record(tenant_project) -> None:
    tenant, project = tenant_project
    with use_tenant(tenant.id):
        task_a = create_task(tenant, project=project)
        task_b = create_task(tenant, project=project)
        dependency = add_dependency(task_a, task_b)

    assert dependency.from_task_id == task_a.id
    assert dependency.to_task_id == task_b.id
    assert dependency.dependency_type == PrjTaskDependency.TYPE_FINISH_TO_START


def test_add_dependency_rejects_self_dependency(tenant_project) -> None:
    tenant, project = tenant_project
    with use_tenant(tenant.id):
        task_a = create_task(tenant, project=project)
        with pytest.raises(ValidationError):
            add_dependency(task_a, task_a)


def test_add_dependency_rejects_cross_project(tenant_project) -> None:
    tenant, project = tenant_project
    with use_tenant(tenant.id):
        other_project = create_project(tenant, name="Autre projet")
        task_a = create_task(tenant, project=project)
        task_x = create_task(tenant, project=other_project)
        with pytest.raises(ValidationError):
            add_dependency(task_a, task_x)


def test_add_dependency_rejects_duplicate(tenant_project) -> None:
    tenant, project = tenant_project
    with use_tenant(tenant.id):
        task_a = create_task(tenant, project=project)
        task_b = create_task(tenant, project=project)
        add_dependency(task_a, task_b)
        with pytest.raises(ValidationError):
            add_dependency(task_a, task_b)


def test_add_dependency_rejects_direct_cycle(tenant_project) -> None:
    """Cycle direct : A -> B puis B -> A doit etre refuse explicitement."""
    tenant, project = tenant_project
    with use_tenant(tenant.id):
        task_a = create_task(tenant, project=project)
        task_b = create_task(tenant, project=project)
        add_dependency(task_a, task_b)
        with pytest.raises(ValidationError) as excinfo:
            add_dependency(task_b, task_a)

    assert "cycle" in str(excinfo.value).lower()
    with use_tenant(tenant.id):
        assert PrjTaskDependency.objects.filter(from_task=task_b, to_task=task_a).count() == 0


def test_add_dependency_rejects_indirect_cycle(tenant_project) -> None:
    """Cycle indirect : A -> B -> C puis C -> A doit etre refuse."""
    tenant, project = tenant_project
    with use_tenant(tenant.id):
        task_a = create_task(tenant, project=project)
        task_b = create_task(tenant, project=project)
        task_c = create_task(tenant, project=project)
        add_dependency(task_a, task_b)
        add_dependency(task_b, task_c)
        with pytest.raises(ValidationError) as excinfo:
            add_dependency(task_c, task_a)

    assert "cycle" in str(excinfo.value).lower()
    with use_tenant(tenant.id):
        assert PrjTaskDependency.objects.filter(from_task=task_c, to_task=task_a).count() == 0


def test_add_dependency_allows_diamond_shape_without_cycle(tenant_project) -> None:
    """Un graphe en losange (A -> B, A -> C, B -> D, C -> D) n'est PAS un
    cycle et doit etre accepte sans erreur — non-regression pour verifier
    que la detection ne rejette pas a tort un graphe convergent legitime."""
    tenant, project = tenant_project
    with use_tenant(tenant.id):
        task_a = create_task(tenant, project=project)
        task_b = create_task(tenant, project=project)
        task_c = create_task(tenant, project=project)
        task_d = create_task(tenant, project=project)
        add_dependency(task_a, task_b)
        add_dependency(task_a, task_c)
        add_dependency(task_b, task_d)
        add_dependency(task_c, task_d)

        assert PrjTaskDependency.objects.filter(tenant=tenant).count() == 4
