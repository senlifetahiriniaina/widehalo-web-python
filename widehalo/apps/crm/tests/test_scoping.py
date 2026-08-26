from __future__ import annotations

import pytest
from django.contrib.auth.models import Group

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.crm.models import CrmLead, CrmPipeline, CrmStage, CrmTeam
from apps.crm.services.leads import create_lead_quick
from apps.crm.services.scoping import scope_leads_for_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def scoping_setup():
    tenant = Tenant.objects.create(code="CRM-SCOPE", name="CRM Scope Tenant")
    with use_tenant(tenant.id):
        pipeline = CrmPipeline.objects.create(tenant=tenant, name="Ventes", is_default=True)
        CrmStage.objects.create(
            tenant=tenant, pipeline=pipeline, code="nouveau", name="Nouveau", sequence=1
        )

        commercial_a = User.objects.create_user(email="a@example.com", password="Str0ngPassw0rd!23")
        commercial_b = User.objects.create_user(email="b@example.com", password="Str0ngPassw0rd!23")
        resp = User.objects.create_user(email="resp@example.com", password="Str0ngPassw0rd!23")
        direction = User.objects.create_user(email="dir@example.com", password="Str0ngPassw0rd!23")
        Group.objects.get_or_create(name="commercial")[0].user_set.add(commercial_a, commercial_b)
        Group.objects.get_or_create(name="resp_commercial")[0].user_set.add(resp)
        Group.objects.get_or_create(name="direction")[0].user_set.add(direction)

        team = CrmTeam.objects.create(tenant=tenant, name="Equipe Nord", leader=resp)
        team.members.add(commercial_a)

        lead_a = create_lead_quick(
            tenant=tenant, name="Lead A", salesperson=commercial_a, team=team
        )
        lead_b = create_lead_quick(tenant=tenant, name="Lead B", salesperson=commercial_b)

        return tenant, commercial_a, commercial_b, resp, direction, lead_a, lead_b


def test_commercial_sees_only_own_leads(scoping_setup) -> None:
    tenant, commercial_a, _b, _resp, _dir, lead_a, lead_b = scoping_setup
    with use_tenant(tenant.id):
        scoped = scope_leads_for_user(CrmLead.objects.all(), commercial_a)
        ids = set(scoped.values_list("id", flat=True))
        assert ids == {lead_a.id}


def test_resp_commercial_sees_team_leads(scoping_setup) -> None:
    tenant, _a, _b, resp, _dir, lead_a, lead_b = scoping_setup
    with use_tenant(tenant.id):
        scoped = scope_leads_for_user(CrmLead.objects.all(), resp)
        ids = set(scoped.values_list("id", flat=True))
        assert ids == {lead_a.id}
        assert lead_b.id not in ids


def test_direction_sees_all_leads(scoping_setup) -> None:
    tenant, _a, _b, _resp, direction, lead_a, lead_b = scoping_setup
    with use_tenant(tenant.id):
        scoped = scope_leads_for_user(CrmLead.objects.all(), direction)
        ids = set(scoped.values_list("id", flat=True))
        assert ids == {lead_a.id, lead_b.id}
