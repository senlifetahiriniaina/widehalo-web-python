"""Canal de notification WhatsApp bidirectionnel — envoi sortant via l'API
WhatsApp Business (Meta Cloud API) et reception entrante via webhook
(cf. api_notifications.py::whatsapp_webhook). Necessite un compte WhatsApp
Business, un token d'acces et des templates de message approuves par Meta
pour l'envoi sortant — non configure par defaut dans ce lot
(`settings.WHATSAPP_ENABLED=False`) : `StubWhatsAppClient` journalise
l'intention d'envoi sans appel reseau, l'interface reste identique une
fois de vrais identifiants renseignes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class WhatsAppSendResult:
    status: str  # "sent" | "failed" | "stubbed"
    provider_message_id: str = ""
    details: str = ""


class WhatsAppClient(ABC):
    @abstractmethod
    def send_template(
        self, phone_number: str, template_name: str, params: dict[str, Any]
    ) -> WhatsAppSendResult: ...


class StubWhatsAppClient(WhatsAppClient):
    def send_template(
        self, phone_number: str, template_name: str, params: dict[str, Any]
    ) -> WhatsAppSendResult:
        return WhatsAppSendResult(status="stubbed", details="WHATSAPP_ENABLED=False — envoi simulé")


class MetaCloudAPIClient(WhatsAppClient):
    """Implementation reelle — necessite settings.WHATSAPP_PHONE_NUMBER_ID
    et settings.WHATSAPP_ACCESS_TOKEN. Ecrite pour que l'activation future
    se limite a renseigner ces identifiants, sans changement de code
    appelant (meme pattern que ClamAVScanner, cf. services/antivirus.py)."""

    def __init__(self, phone_number_id: str, access_token: str) -> None:
        self.phone_number_id = phone_number_id
        self.access_token = access_token

    def send_template(
        self, phone_number: str, template_name: str, params: dict[str, Any]
    ) -> WhatsAppSendResult:
        try:
            import requests

            response = requests.post(
                f"https://graph.facebook.com/v20.0/{self.phone_number_id}/messages",
                headers={"Authorization": f"Bearer {self.access_token}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": phone_number,
                    "type": "template",
                    "template": {
                        "name": template_name,
                        "language": {"code": "fr"},
                        "components": [{"type": "body", "parameters": params.get("body", [])}],
                    },
                },
                timeout=10,
            )
            response.raise_for_status()
            message_id = response.json()["messages"][0]["id"]
            return WhatsAppSendResult(status="sent", provider_message_id=message_id)
        except Exception as exc:  # noqa: BLE001 — degrade en echec de canal, jamais un crash
            return WhatsAppSendResult(status="failed", details=str(exc))


def get_whatsapp_client() -> WhatsAppClient:
    from django.conf import settings

    if getattr(settings, "WHATSAPP_ENABLED", False):
        return MetaCloudAPIClient(
            phone_number_id=settings.WHATSAPP_PHONE_NUMBER_ID,
            access_token=settings.WHATSAPP_ACCESS_TOKEN,
        )
    return StubWhatsAppClient()
