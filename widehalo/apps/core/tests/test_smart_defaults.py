from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_create_tenant_command_applies_madagascar_smart_defaults() -> None:
    call_command("create_tenant", "--code", "MG-DEMO", "--name", "Demo SARL", "--country", "MG")

    tenant = Tenant.objects.get(code="MG-DEMO")
    assert tenant.base_currency == "MGA"
    assert tenant.default_language == "fr"
    assert tenant.timezone == "Indian/Antananarivo"
    assert tenant.retention_policy["country_defaults"]["vat_rate"] == "20.00"
    assert "mvola" in tenant.retention_policy["country_defaults"]["payment_methods"]


def test_create_tenant_command_preloads_helpdesk_ticket_type_catalog() -> None:
    """Le catalogue de types de tickets helpdesk ne doit plus jamais etre
    vide pour un nouveau tenant (signalement utilisateur — cf. plan section
    "catalogue de tickets helpdesk vide par defaut")."""
    from apps.helpdesk.models import HlpTicketTypeCatalog

    call_command(
        "create_tenant", "--code", "MG-DEMO-HLP", "--name", "Demo Helpdesk", "--country", "MG"
    )

    tenant = Tenant.objects.get(code="MG-DEMO-HLP")
    with use_tenant(tenant.id):
        assert HlpTicketTypeCatalog.objects.filter(tenant=tenant).count() > 30


def test_create_tenant_command_preloads_chart_of_accounts_and_default_journals() -> None:
    """Un nouveau tenant a deja son plan comptable (generique + sectoriel)
    et ses 7 journaux par defaut sans aucune action manuelle (UXR7)."""
    from apps.accounting.models import AccAccount, AccJournal

    call_command(
        "create_tenant", "--code", "MG-DEMO-ACC", "--name", "Demo Accounting", "--country", "MG"
    )

    tenant = Tenant.objects.get(code="MG-DEMO-ACC")
    with use_tenant(tenant.id):
        assert AccAccount.objects.filter(tenant=tenant).count() >= 54
        assert AccJournal.objects.filter(tenant=tenant).count() == 7
        bank_journal = AccJournal.objects.get(tenant=tenant, code="BQ")
        assert bank_journal.default_account is not None
        assert bank_journal.default_account.code.startswith("512")
        cash_journal = AccJournal.objects.get(tenant=tenant, code="CAI")
        assert cash_journal.default_account is not None
        assert cash_journal.default_account.code.startswith("530")


def test_create_tenant_command_preloads_default_crm_pipeline() -> None:
    """Un nouveau tenant a deja son pipeline commercial par defaut (HubSpot,
    7 etapes — cf. analyse comparative des 5 principaux CRM mondiaux) sans
    aucune action manuelle."""
    from apps.crm.models import CrmPipeline, CrmStage

    call_command(
        "create_tenant", "--code", "MG-DEMO-CRM", "--name", "Demo Commercial", "--country", "MG"
    )

    tenant = Tenant.objects.get(code="MG-DEMO-CRM")
    with use_tenant(tenant.id):
        pipeline = CrmPipeline.objects.get(tenant=tenant, is_default=True)
        assert CrmStage.objects.filter(tenant=tenant, pipeline=pipeline).count() == 7


def test_unknown_country_leaves_tenant_defaults_unchanged() -> None:
    from apps.core.services.smart_defaults import apply_country_defaults

    tenant = Tenant.objects.create(code="ZZ-T", name="Unknown Country Tenant", country_code="ZZ")
    apply_country_defaults(tenant, "ZZ")
    tenant.refresh_from_db()
    # Pas de profil pour "ZZ" -> aucune modification, pas d'erreur.
    assert tenant.base_currency == "MGA"  # valeur par defaut du modele Tenant
