from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.projects.models import PrjProject
from apps.projects.services.projects import create_project

pytestmark = pytest.mark.django_db


def test_create_project_generates_reference() -> None:
    tenant = Tenant.objects.create(code="PRJ-T1", name="Projects Tenant 1")
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Refonte site web")
        assert project.reference.startswith("PRJ-PROJET-")
        assert project.methodology == PrjProject.METHODOLOGY_WATERFALL
        assert project.status == PrjProject.STATUS_ON_TRACK


def test_create_project_agile_methodology() -> None:
    tenant = Tenant.objects.create(code="PRJ-T2", name="Projects Tenant 2")
    with use_tenant(tenant.id):
        project = create_project(
            tenant, name="Sprint produit", methodology=PrjProject.METHODOLOGY_AGILE
        )
        assert project.methodology == PrjProject.METHODOLOGY_AGILE


def test_project_client_partner_id_is_a_plain_uuid_never_a_fk() -> None:
    """Non-regression de la regle de couplage n1 : `client_partner_id`
    reste un simple UUID, jamais resolu via une FK Django vers `partners`
    (cf. docstring de `apps/projects/models.py`)."""
    tenant = Tenant.objects.create(code="PRJ-T3", name="Projects Tenant 3")
    fake_partner_id = tenant.id  # n'importe quel UUID convient au test
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet client", client_partner_id=fake_partner_id)
        assert project.client_partner_id == fake_partner_id
        assert "partner" not in [f.name for f in PrjProject._meta.get_fields() if f.is_relation]
