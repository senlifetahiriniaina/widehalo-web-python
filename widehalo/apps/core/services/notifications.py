from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

from apps.core.models.notification import Notification, WhatsAppMessage
from apps.core.models.user import User
from apps.core.services.whatsapp import get_whatsapp_client

GROUPING_WINDOW = timedelta(hours=1)


def dispatch_notification(
    user: User,
    notification_type: str,
    payload: dict[str, Any],
    *,
    tenant_id: str,
    channel: str = Notification.CHANNEL_APP,
    grouped_key: str = "",
) -> Notification:
    """Cree la notification et publie un evenement pour le temps reel
    (consomme par le futur canal WebSocket de l'app chat, etape 12) —
    l'envoi e-mail groupe se fait separement via `group_hourly()`."""
    from apps.core.events import publish_event

    notification = Notification.objects.create(
        tenant_id=tenant_id,
        user=user,
        notification_type=notification_type,
        payload=payload,
        channel=channel,
        grouped_key=grouped_key or notification_type,
    )
    publish_event(
        "notification.created",
        {"notification_id": str(notification.id), "user_id": str(user.id)},
        tenant_id=tenant_id,
    )
    return notification


def notify_role(
    tenant_id: str, role_code: str, notification_type: str, payload: dict[str, Any]
) -> list[Notification]:
    """Notifie TOUS les utilisateurs d'un role donne pour ce tenant — lacune
    identifiee par le chantier RG-QUALIF (`dispatch_notification` ne
    notifie jusqu'ici qu'un seul `User`). Un role est porte par un `Group`
    Django global (nomme par son code, cf. `load_roles`) ; les utilisateurs
    concernes sont ceux appartenant a ce groupe ET ayant une
    `UserTenantMembership` pour ce tenant (un role est global au compte
    mais la notification reste scopee au tenant courant, comme toute
    donnee metier).

    Retourne la liste des `Notification` creees (une par utilisateur
    notifie, jamais un envoi groupe implicite) — liste vide si aucun
    utilisateur de ce role n'est rattache a ce tenant, jamais une
    exception."""
    users = User.objects.filter(
        groups__name=role_code, tenant_memberships__tenant_id=tenant_id
    ).distinct()
    return [
        dispatch_notification(user, notification_type, payload, tenant_id=tenant_id)
        for user in users
    ]


def send_whatsapp_notification(
    user: User, phone_number: str, template_name: str, params: dict[str, Any], *, tenant_id: str
) -> WhatsAppMessage:
    notification = dispatch_notification(
        user,
        f"whatsapp.{template_name}",
        params,
        tenant_id=tenant_id,
        channel=Notification.CHANNEL_WHATSAPP,
    )
    client = get_whatsapp_client()
    result = client.send_template(phone_number, template_name, params)

    return WhatsAppMessage.objects.create(
        tenant_id=tenant_id,
        notification=notification,
        direction=WhatsAppMessage.DIRECTION_OUTBOUND,
        phone_number=phone_number,
        template_name=template_name,
        provider_message_id=result.provider_message_id,
        status=WhatsAppMessage.STATUS_SENT
        if result.status == "sent"
        else WhatsAppMessage.STATUS_FAILED,
    )


def record_inbound_whatsapp_message(
    phone_number: str, body: str, provider_message_id: str
) -> WhatsAppMessage:
    """Enregistre un message entrant recu via le webhook WhatsApp — le
    rattachement a un utilisateur/tenant precis (via le numero de
    telephone) relevera des futurs modules metier qui stockent des
    coordonnees telephoniques (Partenaires, RH...)."""
    return WhatsAppMessage.objects.create(
        direction=WhatsAppMessage.DIRECTION_INBOUND,
        phone_number=phone_number,
        body=body,
        provider_message_id=provider_message_id,
        status=WhatsAppMessage.STATUS_RECEIVED,
    )


def group_hourly(user: User) -> list[Notification]:
    """Regroupe les notifications non lues de la derniere heure par
    `grouped_key`, pour n'envoyer qu'un seul e-mail par groupe plutot
    qu'un e-mail par notification individuelle."""
    since = timezone.now() - GROUPING_WINDOW
    candidates = Notification.objects.filter(
        user=user, created_at__gte=since, email_sent_at__isnull=True
    )

    seen_keys: set[str] = set()
    to_send: list[Notification] = []
    for notification in candidates:
        if notification.grouped_key in seen_keys:
            continue
        seen_keys.add(notification.grouped_key)
        to_send.append(notification)

    Notification.objects.filter(id__in=[n.id for n in candidates]).update(
        email_sent_at=timezone.now()
    )
    return to_send
