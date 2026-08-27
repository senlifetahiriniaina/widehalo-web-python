"""T10 : la commande `seed_crm` cree un jeu de demonstration coherent et
est idempotente (rejouee deux fois, ne duplique pas les 5 opportunites de
demonstration)."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.crm.models import CrmActivity, CrmLead, CrmPipeline, CrmStage

pytestmark = pytest.mark.django_db


def test_seed_crm_creates_coherent_demo_dataset() -> None:
    call_command("seed_crm", tenant_code="TEST-SEED-CRM")
    tenant = Tenant.objects.get(code="TEST-SEED-CRM")

    with use_tenant(tenant.id):
        pipeline = CrmPipeline.objects.get(tenant=tenant, is_default=True)
        assert CrmStage.objects.filter(tenant=tenant, pipeline=pipeline).count() == 5

        leads = CrmLead.objects.filter(tenant=tenant, pipeline=pipeline)
        assert leads.count() == 5

        lost_leads = leads.filter(stage__is_lost=True)
        assert lost_leads.count() == 1
        assert lost_leads.first().lost_reason is not None

        lead_with_line = leads.get(name="Chaine boutiques mode")
        assert lead_with_line.lines.count() == 1

        assert CrmActivity.objects.filter(tenant=tenant).count() == 2

        demo_user = User.objects.get(email="commercial.demo@widehalo.local")
        assert demo_user.groups.filter(name="commercial").exists()


def test_seed_crm_is_idempotent() -> None:
    call_command("seed_crm", tenant_code="TEST-SEED-CRM-IDEMP")
    call_command("seed_crm", tenant_code="TEST-SEED-CRM-IDEMP")

    tenant = Tenant.objects.get(code="TEST-SEED-CRM-IDEMP")
    with use_tenant(tenant.id):
        assert CrmPipeline.objects.filter(tenant=tenant).count() == 1
        assert CrmLead.objects.filter(tenant=tenant).count() == 5
