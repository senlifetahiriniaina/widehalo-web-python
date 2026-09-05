from __future__ import annotations

import hashlib
import hmac

import pytest
from django.db import connection

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.logistics.models import LogServiceProvider
from apps.logistics.services.freight import create_service_provider
from apps.logistics.services.webhooks import verify_carrier_webhook_signature

pytestmark = pytest.mark.django_db


@pytest.fixture
def provider_setup():
    tenant = Tenant.objects.create(code="LOG-WH-T", name="Logistics Webhook Tenant")
    with use_tenant(tenant.id):
        provider = create_service_provider(tenant, code="CAR-WH", name="Transporteur Webhook")
        provider.webhook_secret = "s3cr3t"
        provider.save(update_fields=["webhook_secret"])
        return tenant, provider


def test_verify_carrier_webhook_signature_accepts_valid_signature(provider_setup) -> None:
    tenant, provider = provider_setup
    with use_tenant(tenant.id):
        payload = b'{"event":"shipment.updated"}'
        signature = hmac.new(b"s3cr3t", payload, hashlib.sha256).hexdigest()
        assert verify_carrier_webhook_signature(provider, payload=payload, signature=signature)


def test_verify_carrier_webhook_signature_rejects_wrong_signature(provider_setup) -> None:
    tenant, provider = provider_setup
    with use_tenant(tenant.id):
        payload = b'{"event":"shipment.updated"}'
        assert not verify_carrier_webhook_signature(provider, payload=payload, signature="deadbeef")


def test_verify_carrier_webhook_signature_rejects_when_no_secret_configured(
    provider_setup,
) -> None:
    tenant, provider = provider_setup
    with use_tenant(tenant.id):
        provider.webhook_secret = ""
        provider.save(update_fields=["webhook_secret"])
        payload = b'{"event":"shipment.updated"}'
        signature = hmac.new(b"s3cr3t", payload, hashlib.sha256).hexdigest()
        assert not verify_carrier_webhook_signature(provider, payload=payload, signature=signature)


def test_the_database_never_holds_the_plaintext_webhook_secret() -> None:
    """L15 — le secret partage est chiffre au repos.

    L'API n'exposait deja que `has_webhook_secret: bool`, ce qui limitait la
    fuite par l'application. Ce test porte sur l'autre voie, celle que le
    booleen ne couvrait pas : ce qu'une lecture directe de la base — ou d'une
    SAUVEGARDE — restitue."""
    tenant = Tenant.objects.create(code="LOG-SEC", name="Logistics Secret")
    with use_tenant(tenant.id):
        provider = create_service_provider(tenant, code="CAR-SEC", name="Transporteur Secret")
        provider.webhook_secret = "s3cr3t-partage"
        provider.save(update_fields=["webhook_secret"])

        # Relu par l'ORM : le service voit toujours la valeur en clair.
        assert LogServiceProvider.objects.get(id=provider.id).webhook_secret == "s3cr3t-partage"

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT webhook_secret FROM log_service_provider WHERE id = %s",
                [str(provider.id)],
            )
            (stored,) = cursor.fetchone()

    assert stored != "s3cr3t-partage"
    assert "s3cr3t" not in stored
