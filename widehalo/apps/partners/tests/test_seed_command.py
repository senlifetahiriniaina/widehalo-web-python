"""T10 : la commande `seed_partners` cree un jeu de demonstration coherent
et est idempotente (rejouee deux fois, ne duplique pas les partenaires de
demonstration)."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.partners.models import DuplicateAlert, Partner
from apps.partners.services.public import is_over_credit_limit

pytestmark = pytest.mark.django_db


def test_seed_partners_creates_coherent_demo_dataset() -> None:
    call_command("seed_partners", tenant_code="TEST-SEED-PART")
    tenant = Tenant.objects.get(code="TEST-SEED-PART")

    with use_tenant(tenant.id):
        partners = Partner.objects.filter(tenant=tenant)
        assert partners.count() == 7

        roles_present = set()
        for partner in partners:
            roles_present.update(partner.roles)
        assert {
            Partner.ROLE_CLIENT,
            Partner.ROLE_SUPPLIER,
            Partner.ROLE_CARRIER,
            Partner.ROLE_SUBCONTRACTOR,
        }.issubset(roles_present)

        assert DuplicateAlert.objects.filter(tenant=tenant).count() == 1

        carrier = Partner.objects.get(tenant=tenant, name="Transport Rakoto & Fils")
        assert is_over_credit_limit(carrier.id, 600000) is True
        assert is_over_credit_limit(carrier.id, 100) is False

        demo_user = User.objects.get(email="admin.demo@widehalo.local")
        assert demo_user.groups.filter(name="admin").exists()


def test_seed_partners_is_idempotent() -> None:
    call_command("seed_partners", tenant_code="TEST-SEED-PART-IDEMP")
    call_command("seed_partners", tenant_code="TEST-SEED-PART-IDEMP")

    tenant = Tenant.objects.get(code="TEST-SEED-PART-IDEMP")
    with use_tenant(tenant.id):
        assert Partner.objects.filter(tenant=tenant).count() == 7
