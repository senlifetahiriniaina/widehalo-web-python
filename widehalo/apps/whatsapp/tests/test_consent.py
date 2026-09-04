"""WA-1/WA-2 (cahier Phase 2 §13.4) : consentement/opt-in et révocation."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.whatsapp.services.consent import grant_consent, has_active_consent, revoke_consent

pytestmark = pytest.mark.django_db


def test_grant_consent_requires_a_source() -> None:
    tenant = Tenant.objects.create(code="WA-C1", name="WhatsApp Consent Tenant 1")
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        grant_consent(tenant, phone_number="+261340000001", source="")


def test_grant_then_has_active_consent() -> None:
    tenant = Tenant.objects.create(code="WA-C2", name="WhatsApp Consent Tenant 2")
    with use_tenant(tenant.id):
        user = UserFactory()
        assert has_active_consent(tenant, "+261340000002") is False

        grant_consent(
            tenant, phone_number="+261340000002", source="formulaire_web", granted_by=user
        )
        assert has_active_consent(tenant, "+261340000002") is True


def test_revoke_consent_deactivates_it() -> None:
    tenant = Tenant.objects.create(code="WA-C3", name="WhatsApp Consent Tenant 3")
    with use_tenant(tenant.id):
        grant_consent(tenant, phone_number="+261340000003", source="opt_in_sms")
        assert has_active_consent(tenant, "+261340000003") is True

        revoke_consent(tenant, phone_number="+261340000003")
        assert has_active_consent(tenant, "+261340000003") is False


def test_revoke_consent_is_idempotent_without_prior_grant() -> None:
    tenant = Tenant.objects.create(code="WA-C4", name="WhatsApp Consent Tenant 4")
    with use_tenant(tenant.id):
        # Ne doit jamais lever d'exception meme sans consentement prealable.
        revoke_consent(tenant, phone_number="+261340000004")
        assert has_active_consent(tenant, "+261340000004") is False


def test_regrant_after_revocation_reactivates_consent() -> None:
    tenant = Tenant.objects.create(code="WA-C5", name="WhatsApp Consent Tenant 5")
    with use_tenant(tenant.id):
        grant_consent(tenant, phone_number="+261340000005", source="formulaire_web")
        revoke_consent(tenant, phone_number="+261340000005")
        assert has_active_consent(tenant, "+261340000005") is False

        grant_consent(tenant, phone_number="+261340000005", source="opt_in_sms")
        assert has_active_consent(tenant, "+261340000005") is True
