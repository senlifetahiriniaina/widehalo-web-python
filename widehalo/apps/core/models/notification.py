from __future__ import annotations

from django.db import models

from apps.core.db.uuid7 import uuid7


class Notification(models.Model):
    """Notification generique — modele et mecanisme de dispatch communs a
    tout type futur (les 7 types metier du cahier des charges concernent
    des modules pas encore construits ; ce lot pose l'infrastructure)."""

    CHANNEL_APP = "app"
    CHANNEL_EMAIL = "email"
    CHANNEL_WHATSAPP = "whatsapp"
    CHANNEL_CHOICES = [
        (CHANNEL_APP, "Application"),
        (CHANNEL_EMAIL, "E-mail"),
        (CHANNEL_WHATSAPP, "WhatsApp"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="notifications")

    notification_type = models.CharField(max_length=64, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    channel = models.CharField(max_length=16, choices=CHANNEL_CHOICES, default=CHANNEL_APP)

    read_at = models.DateTimeField(null=True, blank=True)
    grouped_key = models.CharField(max_length=128, blank=True, db_index=True)
    email_sent_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_notification"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.notification_type} -> {self.user}"


class WhatsAppMessage(models.Model):
    """Journal des echanges WhatsApp (sortants et entrants) — canal de
    notification bidirectionnel via l'API WhatsApp Business (Meta Cloud
    API). Necessite un compte WhatsApp Business et des templates approuves
    par Meta pour l'envoi sortant (limitation imposee par la plateforme,
    pas par ce lot) ; l'interface reste appelable meme sans ces identifiants
    configures — cf. services/whatsapp.py::get_whatsapp_client()."""

    DIRECTION_OUTBOUND = "outbound"
    DIRECTION_INBOUND = "inbound"
    DIRECTION_CHOICES = [
        (DIRECTION_OUTBOUND, "Sortant"),
        (DIRECTION_INBOUND, "Entrant"),
    ]

    STATUS_PENDING = "pending"
    STATUS_SENT = "sent"
    STATUS_DELIVERED = "delivered"
    STATUS_FAILED = "failed"
    STATUS_RECEIVED = "received"
    STATUS_CHOICES = [
        (STATUS_PENDING, "En attente"),
        (STATUS_SENT, "Envoyé"),
        (STATUS_DELIVERED, "Distribué"),
        (STATUS_FAILED, "Échoué"),
        (STATUS_RECEIVED, "Reçu"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tenant_id = models.UUIDField(db_index=True, null=True, blank=True)
    notification = models.ForeignKey(
        Notification,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="whatsapp_messages",
    )

    direction = models.CharField(max_length=16, choices=DIRECTION_CHOICES)
    phone_number = models.CharField(max_length=32)
    body = models.TextField(blank=True)
    template_name = models.CharField(max_length=100, blank=True)
    provider_message_id = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_whatsapp_message"

    def __str__(self) -> str:
        return f"{self.direction} {self.phone_number} ({self.status})"
