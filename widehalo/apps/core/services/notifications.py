from __future__ import annotations

import datetime as dt
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.mail import send_mail
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


def notify_role_once(
    tenant_id: str,
    role_code: str,
    notification_type: str,
    payload: dict[str, Any],
    *,
    dedup_keys: tuple[str, ...],
    window: dt.timedelta = dt.timedelta(days=1),
) -> list[Notification]:
    """Variante DEDOUBLONNEE de `notify_role`, pour les alertes periodiques.

    L0-1 : plusieurs commandes de gestion notifient une situation qui DURE —
    un lot qui approche de sa peremption, un controle qualite en retard.
    Tant que rien ne les ordonnancait, le probleme restait theorique ; le jour
    ou un ordonnanceur les execute quotidiennement, la meme situation produit
    une notification par execution jusqu'a ce qu'elle soit traitee. C'est la
    difference entre une alerte et du bruit.

    `dedup_keys` designe les champs du `payload` qui identifient la situation
    (`("lot_id",)` pour une peremption). Si une notification du meme type et
    de la meme situation existe deja dans la fenetre, rien n'est emis.

    Retourne les notifications creees — liste vide quand le doublon est
    supprime, donc indiscernable pour l'appelant du cas « personne a
    notifier », ce qui est voulu : aucune des deux situations n'est une
    erreur."""
    users = User.objects.filter(
        groups__name=role_code, tenant_memberships__tenant_id=tenant_id
    ).distinct()
    if not users:
        return []

    fingerprint = {key: payload[key] for key in dedup_keys if key in payload}
    already_notified = set(
        Notification.objects.filter(
            tenant_id=tenant_id,
            notification_type=notification_type,
            payload__contains=fingerprint,
            created_at__gte=timezone.now() - window,
            user__in=users,
        ).values_list("user_id", flat=True)
    )
    # Le dedoublonnage est PAR DESTINATAIRE, jamais global : deux roles
    # notifies de la meme situation doivent tous deux la recevoir, et un
    # utilisateur qui rejoint le role apres coup ne doit pas etre prive de
    # l'alerte parce qu'un collegue l'a deja recue.
    return [
        dispatch_notification(user, notification_type, payload, tenant_id=tenant_id)
        for user in users
        if user.id not in already_notified
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
    qu'un e-mail par notification individuelle.

    Selection UNIQUEMENT : marque `email_sent_at` sur TOUTES les
    notifications du groupe (candidates ET representants), mais n'envoie
    rien elle-meme — c'est `send_grouped_email_notifications()` ci-dessous
    qui envoie reellement, pour que cette fonction reste testable sans
    backend e-mail (deja le comportement avant ce correctif, conserve a
    l'identique pour ne pas casser `test_notifications_grouping.py`)."""
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


def _render_email_body(notifications: list[Notification]) -> str:
    lines: list[str] = []
    for notification in notifications:
        message = notification.payload.get("message") or notification.notification_type
        lines.append(f"- {message}")
        action_url = notification.payload.get("action_url")
        if action_url:
            label = notification.payload.get("action_label") or "Voir"
            lines.append(f"  {label} : {settings.SITE_URL.rstrip('/')}{action_url}")
    return "\n".join(lines)


def send_grouped_email_notifications(user: User) -> int:
    """Cahier des charges Phase 1 §9 (« Serveur d'envoi d'e-mail ») : envoie
    reellement, via le backend e-mail Django configure (console en dev,
    SMTP en prod — `config/settings/{dev,prod}.py::EMAIL_BACKEND`), le
    resume horaire groupe des notifications de `user` — ecart confirme par
    l'audit (docs/audit/2026-09-cahier-des-charges-v3-audit.md, §9) :
    `group_hourly()` marquait `email_sent_at` sans jamais appeler
    `django.core.mail.send_mail`, donc aucun e-mail ne partait jamais
    reellement.

    A appeler periodiquement (toutes les heures, cf. `GROUPING_WINDOW` et
    la commande de management `send_grouped_notification_emails`) pour
    chaque utilisateur ayant des notifications en attente — jamais depuis
    le cycle de requete HTTP qui a cree la notification (l'envoi groupe
    n'aurait alors plus aucun sens).

    Renvoie le nombre de notifications effectivement incluses dans
    l'e-mail (0 si rien a envoyer — n'envoie alors aucun e-mail vide)."""
    to_send = group_hourly(user)
    if not to_send:
        return 0

    send_mail(
        subject=f"WideHalo — {len(to_send)} notification(s)",
        message=_render_email_body(to_send),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )
    return len(to_send)
