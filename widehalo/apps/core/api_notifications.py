"""Notifications transversales — modele generique, regroupement horaire
avant envoi e-mail (cf. services/notifications.py). Le webhook WhatsApp
est public (verifie par jeton, pas par JWT applicatif — c'est Meta qui
l'appelle)."""

from django.conf import settings
from django.http import HttpResponse
from ninja import Router

from apps.core.models.notification import Notification
from apps.core.services.notifications import record_inbound_whatsapp_message

router = Router(tags=["notifications"])


@router.get("/notifications")
def list_notifications(request):
    notifications = Notification.objects.filter(user=request.auth)[:50]
    return {
        "results": [
            {
                "id": str(n.id),
                "type": n.notification_type,
                "payload": n.payload,
                "read": n.read_at is not None,
                "created_at": n.created_at.isoformat(),
            }
            for n in notifications
        ]
    }


@router.post("/notifications/{notification_id}/read")
def mark_notification_read(request, notification_id: str):
    from django.utils import timezone

    updated = Notification.objects.filter(id=notification_id, user=request.auth).update(
        read_at=timezone.now()
    )
    return {"status": "ok" if updated else "not_found"}


@router.get("/notifications/whatsapp/webhook", auth=None)
def whatsapp_webhook_verify(request):
    """Poignee de main de verification exigee par Meta a la configuration
    du webhook (hub.mode/hub.verify_token/hub.challenge en query string)."""
    mode = request.GET.get("hub.mode")
    token = request.GET.get("hub.verify_token")
    challenge = request.GET.get("hub.challenge", "")
    if mode == "subscribe" and token == settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN:
        return HttpResponse(challenge)
    return HttpResponse(status=403)


@router.post("/notifications/whatsapp/webhook", auth=None)
def whatsapp_webhook_receive(request):
    """Reception des messages entrants WhatsApp — journalises pour
    rattachement ulterieur par les futurs modules metier (Partenaires, RH)
    qui connaissent les numeros de telephone de leurs contacts."""
    import json

    body = json.loads(request.body or b"{}")
    entries = body.get("entry", [])
    processed = 0

    for entry in entries:
        for change in entry.get("changes", []):
            for message in change.get("value", {}).get("messages", []):
                record_inbound_whatsapp_message(
                    phone_number=message.get("from", ""),
                    body=message.get("text", {}).get("body", ""),
                    provider_message_id=message.get("id", ""),
                )
                processed += 1

    return {"status": "ok", "processed": processed}
