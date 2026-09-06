"""Notifications transversales — modele generique, regroupement horaire
avant envoi e-mail (cf. services/notifications.py).

**Le webhook WhatsApp historique a ete RETIRE d'ici (bloquants 4/4).** Il
vivait sous `/notifications/whatsapp/webhook`, restait monte et joignable,
et appelait `record_inbound_whatsapp_message` **sans `tenant_id`** : tout
message recu par cette porte etait ecrit avec `tenant_id = NULL`, donc
invisible de tous les ecrans — exactement le defaut ferme quelques jours
plus tot sur le webhook gouverne. Il n'appelait pas davantage
`handle_inbound_message`, donc « STOP » n'y desabonnait personne et aucune
conversation n'y progressait.

Le garder « par compatibilite ascendante » revenait donc a garder une
seconde entree qui reintroduit integralement un defaut repare a cote. Le
webhook GOUVERNE de `apps.whatsapp.api` (`/whatsapp/webhook`, verification
Meta comprise) est desormais le seul.

**Note d'exploitation** : une instance dont la plateforme Meta pointe
encore l'ancienne URL cessera de recevoir ses messages tant que l'URL n'aura
pas ete repointee (cf. `docs/DEPLOYMENT_HETZNER.md`)."""

from ninja import Router

from apps.core.models.notification import Notification

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
