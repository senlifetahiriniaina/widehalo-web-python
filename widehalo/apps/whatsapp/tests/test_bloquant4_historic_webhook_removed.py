"""Bloquants (4/4) — la seconde porte d'entree WhatsApp, qui reintroduisait
un defaut deja ferme.

`apps/core/api_notifications.py` exposait, sous
`/api/v1/notifications/whatsapp/webhook`, un webhook historique conserve
« par compatibilite ascendante ». Il appelait `record_inbound_whatsapp_
message` **sans `tenant_id`** : tout message recu par cette porte etait
ecrit avec `tenant_id = NULL`, donc invisible de tous les ecrans — c'est
exactement le defaut ferme quelques jours plus tot sur le webhook gouverne.
Il n'appelait pas non plus `handle_inbound_message`, donc « STOP » n'y
desabonnait personne.

Une compatibilite ascendante qui reintroduit integralement le defaut
repare a cote n'en est pas une : la porte est retiree, et ce test empeche
qu'elle revienne."""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.core.models.notification import WhatsAppMessage
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db

HISTORIC_PATH = "/api/v1/notifications/whatsapp/webhook"
GOVERNED_PATH = "/api/v1/whatsapp/webhook"

_PAYLOAD = {
    "entry": [
        {
            "changes": [
                {
                    "value": {
                        "messages": [
                            {
                                "from": "+261340000099",
                                "text": {"body": "Bonjour"},
                                "id": "wamid.historique",
                            }
                        ]
                    }
                }
            ]
        }
    ]
}


def test_the_historic_webhook_no_longer_exists() -> None:
    """404, et surtout AUCUN message ecrit.

    Le 404 seul ne suffirait pas : une route qui repondrait 404 tout en
    ayant deja journalise le message laisserait le defaut entier."""
    client = Client()
    response = client.post(
        HISTORIC_PATH, data=json.dumps(_PAYLOAD), content_type="application/json"
    )
    assert response.status_code == 404
    assert not WhatsAppMessage.objects.filter(phone_number="+261340000099").exists()


def test_the_historic_verify_handshake_no_longer_exists(settings) -> None:
    """La poignee de main Meta aussi : la laisser seule permettrait de
    reconfigurer la plateforme sur une URL qui n'accepte plus rien, ce qui
    est pire qu'une URL absente (l'operateur croirait la configuration
    valide)."""
    settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN = "jeton-de-test"
    client = Client()
    response = client.get(
        HISTORIC_PATH,
        {
            "hub.mode": "subscribe",
            "hub.verify_token": "jeton-de-test",
            "hub.challenge": "12345",
        },
    )
    assert response.status_code == 404


def test_the_governed_webhook_is_the_one_that_answers(settings) -> None:
    """La falsification : le remplacant repond, lui, et ecrit AVEC son
    tenant. Sans cette moitie, « la porte est fermee » et « les deux portes
    sont fermees » seraient indiscernables."""
    tenant = Tenant.objects.create(code="WA-B4", name="Webhook gouverne SARL")
    settings.WHATSAPP_DEFAULT_TENANT_ID = str(tenant.id)
    settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN = "jeton-de-test"
    client = Client()

    verify = client.get(
        GOVERNED_PATH,
        {
            "hub.mode": "subscribe",
            "hub.verify_token": "jeton-de-test",
            "hub.challenge": "12345",
        },
    )
    assert verify.status_code == 200

    response = client.post(
        GOVERNED_PATH, data=json.dumps(_PAYLOAD), content_type="application/json"
    )
    assert response.status_code == 200
    assert response.json()["processed"] == 1

    with use_tenant(tenant.id):
        message = WhatsAppMessage.objects.filter(phone_number="+261340000099").first()
    assert message is not None
    assert message.tenant_id == tenant.id
