from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.core.models.tenant import Tenant

pytestmark = pytest.mark.django_db


def test_create_tenant_command_applies_madagascar_smart_defaults() -> None:
    call_command("create_tenant", "--code", "MG-DEMO", "--name", "Demo SARL", "--country", "MG")

    tenant = Tenant.objects.get(code="MG-DEMO")
    assert tenant.base_currency == "MGA"
    assert tenant.default_language == "fr"
    assert tenant.timezone == "Indian/Antananarivo"
    assert tenant.retention_policy["country_defaults"]["vat_rate"] == "20.00"
    assert "mvola" in tenant.retention_policy["country_defaults"]["payment_methods"]


def test_unknown_country_leaves_tenant_defaults_unchanged() -> None:
    from apps.core.services.smart_defaults import apply_country_defaults

    tenant = Tenant.objects.create(code="ZZ-T", name="Unknown Country Tenant", country_code="ZZ")
    apply_country_defaults(tenant, "ZZ")
    tenant.refresh_from_db()
    # Pas de profil pour "ZZ" -> aucune modification, pas d'erreur.
    assert tenant.base_currency == "MGA"  # valeur par defaut du modele Tenant
