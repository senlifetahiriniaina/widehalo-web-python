"""Motifs de perte d'opportunite par defaut (7 categories metier) charges
automatiquement a l'initialisation d'une entreprise — cf.
`apps.crm.services.lost_reasons`."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.crm.models import CrmLostReason
from apps.crm.services.lost_reasons import DEFAULT_LOST_REASONS, ensure_default_lost_reasons

pytestmark = pytest.mark.django_db


def test_ensure_default_lost_reasons_creates_seven_reasons() -> None:
    tenant = Tenant.objects.create(code="CRM-LOST-1", name="CRM Lost 1", country_code="MG")
    with use_tenant(tenant.id):
        reasons = ensure_default_lost_reasons(tenant)

        assert len(reasons) == 7
        assert len(DEFAULT_LOST_REASONS) == 7
        names = set(CrmLostReason.objects.filter(tenant=tenant).values_list("name", flat=True))
        assert names == set(DEFAULT_LOST_REASONS)


def test_ensure_default_lost_reasons_is_idempotent() -> None:
    tenant = Tenant.objects.create(code="CRM-LOST-2", name="CRM Lost 2", country_code="MG")
    with use_tenant(tenant.id):
        ensure_default_lost_reasons(tenant)
        ensure_default_lost_reasons(tenant)

        assert CrmLostReason.objects.filter(tenant=tenant).count() == 7


def test_ensure_default_lost_reasons_never_overwrites_a_tenant_edit() -> None:
    tenant = Tenant.objects.create(code="CRM-LOST-3", name="CRM Lost 3", country_code="MG")
    with use_tenant(tenant.id):
        ensure_default_lost_reasons(tenant)
        edited = CrmLostReason.objects.get(tenant=tenant, name=DEFAULT_LOST_REASONS[0])
        edited.name = "Prix (renomme par le tenant)"
        edited.save(update_fields=["name"])

        ensure_default_lost_reasons(tenant)

        # Le motif renomme n'est jamais ecrase, et un nouveau motif reprenant
        # le libelle par defaut d'origine est cree a la place (get_or_create
        # par nom) — comportement attendu, disclosed dans le docstring du
        # service.
        assert CrmLostReason.objects.filter(
            tenant=tenant, name="Prix (renomme par le tenant)"
        ).exists()
        assert CrmLostReason.objects.filter(tenant=tenant).count() == 8


def test_load_default_lost_reasons_command_is_idempotent() -> None:
    tenant = Tenant.objects.create(code="CRM-LOST-4", name="CRM Lost 4", country_code="MG")
    call_command("load_default_lost_reasons", tenant=tenant.code)
    call_command("load_default_lost_reasons", tenant=tenant.code)

    with use_tenant(tenant.id):
        assert CrmLostReason.objects.filter(tenant=tenant).count() == 7
