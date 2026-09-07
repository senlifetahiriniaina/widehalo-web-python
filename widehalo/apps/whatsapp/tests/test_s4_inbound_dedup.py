"""S4 — la protection contre le rejeu entrant, qui n'existait pas.

Le cahier (§8.2) : « Horodatage dans une fenêtre courte, identifiant
d'événement conservé, second passage ignoré et journalisé comme doublon.
Sans cela, un même paiement peut être enregistré deux fois — **c'est le
défaut le plus coûteux de cette famille.** »

L'identifiant de message du fournisseur était **stocké et jamais
interrogé** : aucun `filter`, aucun `exists`, aucune contrainte, pas même
un index. Or un fournisseur re-livre son webhook tant qu'il ne reçoit pas
un 2xx — une réponse lente, un déploiement, une erreur applicative — et le
même message entrant produisait alors deux lignes **et deux traitements**.

Deux traitements, c'est ce qui coûte : un « STOP » re-livré révoquerait
deux fois, et une notification de paiement serait rapprochée deux fois. La
déduplication à l'écriture ne suffit donc pas ; il faut aussi ne pas
retraiter.
"""

from __future__ import annotations

import json

import pytest
from django.db import IntegrityError

from apps.core.models.notification import WhatsAppMessage
from apps.core.models.tenant import Tenant
from apps.core.services.notifications import record_inbound_whatsapp_message

pytestmark = pytest.mark.django_db


@pytest.fixture
def societe():
    return Tenant.objects.create(code="S4-IN", name="Entrant SARL")


def test_a_redelivered_message_creates_only_one_row(societe) -> None:
    """La re-livraison est le cas NORMAL d'un webhook, pas une anomalie."""
    premier = record_inbound_whatsapp_message(
        phone_number="+261340000001",
        body="bonjour",
        provider_message_id="wamid.ABC",
        tenant_id=societe.id,
    )
    second = record_inbound_whatsapp_message(
        phone_number="+261340000001",
        body="bonjour",
        provider_message_id="wamid.ABC",
        tenant_id=societe.id,
    )

    assert second.pk == premier.pk
    assert WhatsAppMessage.objects.filter(provider_message_id="wamid.ABC").count() == 1


def test_the_database_refuses_a_duplicate_even_without_the_service(societe) -> None:
    """Ce qui tient RÉELLEMENT la promesse. Un service peut être contourné
    par un second point d'entrée — il y en avait justement deux dans ce
    dépôt jusqu'au lot précédent — une contrainte non."""
    record_inbound_whatsapp_message(
        phone_number="+261340000001",
        body="bonjour",
        provider_message_id="wamid.XYZ",
        tenant_id=societe.id,
    )
    with pytest.raises(IntegrityError):
        WhatsAppMessage.objects.create(
            tenant_id=societe.id,
            direction=WhatsAppMessage.DIRECTION_INBOUND,
            phone_number="+261340000001",
            body="bonjour",
            provider_message_id="wamid.XYZ",
            status=WhatsAppMessage.STATUS_RECEIVED,
        )


def test_two_tenants_may_receive_the_same_provider_id(societe) -> None:
    """La contrainte porte sur le COUPLE (tenant, identifiant). Deux
    sociétés sur la même instance ne doivent jamais se bloquer l'une
    l'autre — et un identifiant de fournisseur reste, en pratique, unique
    par numéro."""
    autre = Tenant.objects.create(code="S4-IN2", name="Entrant bis SARL")
    record_inbound_whatsapp_message(
        phone_number="+261340000001",
        body="bonjour",
        provider_message_id="wamid.PARTAGE",
        tenant_id=societe.id,
    )
    record_inbound_whatsapp_message(
        phone_number="+261340000002",
        body="bonjour",
        provider_message_id="wamid.PARTAGE",
        tenant_id=autre.id,
    )
    assert WhatsAppMessage.objects.filter(provider_message_id="wamid.PARTAGE").count() == 2


def test_a_message_without_a_provider_id_is_never_dropped(societe) -> None:
    """Sans identifiant, aucune déduplication n'est possible — et perdre un
    message entrant serait pire qu'en garder deux."""
    record_inbound_whatsapp_message(
        phone_number="+261340000003", body="un", provider_message_id="", tenant_id=societe.id
    )
    record_inbound_whatsapp_message(
        phone_number="+261340000003", body="deux", provider_message_id="", tenant_id=societe.id
    )
    assert WhatsAppMessage.objects.filter(phone_number="+261340000003").count() == 2


def test_an_outbound_message_is_not_constrained(societe) -> None:
    """Les sortants portent l'identifiant rendu par le fournisseur, vide
    avec le client de repli : une contrainte non conditionnelle les
    bloquerait dès le second envoi."""
    for _ in range(3):
        WhatsAppMessage.objects.create(
            tenant_id=societe.id,
            direction=WhatsAppMessage.DIRECTION_OUTBOUND,
            phone_number="+261340000004",
            provider_message_id="",
            status=WhatsAppMessage.STATUS_SENT,
        )
    assert WhatsAppMessage.objects.filter(phone_number="+261340000004").count() == 3


def test_the_webhook_does_not_reprocess_a_redelivered_message(societe, client, settings) -> None:
    """La moitié qui coûte. Dédupliquer l'écriture sans empêcher le
    RETRAITEMENT laisserait un « STOP » re-livré révoquer deux fois.

    Le webhook rend le nombre de doublons ignorés : un webhook qui ignore
    silencieusement ressemble exactement à un webhook qui traite."""
    settings.WHATSAPP_DEFAULT_TENANT_ID = str(societe.id)
    charge = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "+261340000005",
                                    "id": "wamid.REJEU",
                                    "text": {"body": "bonjour"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    premiere = client.post(
        "/api/v1/whatsapp/webhook", data=json.dumps(charge), content_type="application/json"
    )
    seconde = client.post(
        "/api/v1/whatsapp/webhook", data=json.dumps(charge), content_type="application/json"
    )

    assert premiere.status_code == 200
    assert seconde.status_code == 200, (
        "La re-livraison renvoie une erreur : le fournisseur la lirait comme un échec "
        "et re-livrerait de nouveau — une boucle d'amplification."
    )
    assert premiere.json()["processed"] == 1
    assert seconde.json()["processed"] == 0
    assert seconde.json()["duplicates_ignored"] == 1
    assert WhatsAppMessage.objects.filter(provider_message_id="wamid.REJEU").count() == 1
