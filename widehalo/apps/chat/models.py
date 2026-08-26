"""Messagerie contextualisee : un `ChatChannel` peut etre rattache a
n'importe quelle entite metier via content-type generique (ex. une facture,
une commande, un ticket de production) sans que `chat` importe le moindre
modele d'une autre app metier — seul `object_id`/`content_type` (generiques)
transitent, jamais une FK typee. `get_or_create_document_channel()`, expose
en `services/public.py`, est le point d'entree que les futurs modules
utiliseront pour ouvrir une conversation liee a un de leurs objets."""

from __future__ import annotations

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.models.base import BaseModel


class ChatChannel(BaseModel):
    KIND_DIRECT = "direct"
    KIND_CONTEXT = "context"
    KIND_CHOICES = [
        (KIND_DIRECT, "Direct"),
        (KIND_CONTEXT, "Contextuel"),
    ]

    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_CONTEXT)
    title = models.CharField(max_length=200, blank=True)

    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=64, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta:
        db_table = "chat_channel"
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self) -> str:
        return self.title or f"Canal {self.kind} {self.id}"


class ChatChannelMembership(BaseModel):
    channel = models.ForeignKey(ChatChannel, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="+")

    class Meta:
        db_table = "chat_channel_membership"
        constraints = [
            models.UniqueConstraint(fields=["channel", "user"], name="uniq_chat_membership")
        ]


class ChatMessage(BaseModel):
    channel = models.ForeignKey(ChatChannel, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    body = models.TextField(blank=True)
    attachment = models.ForeignKey(
        "core.Document", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "chat_message"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.sender_id}@{self.channel_id}: {self.body[:30]}"
