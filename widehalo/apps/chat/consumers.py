"""Consumer WebSocket du chat. Isolation stricte par tenant : le nom du
groupe Channels inclut le tenant_id (pas seulement le channel_id), et
l'appartenance au canal est revalidee cote serveur a la connexion — un
utilisateur d'un tenant B ne peut donc pas rejoindre un canal du tenant A
meme en forgeant l'id du canal dans l'URL (il ne sera jamais membre).
En cas d'echec du WebSocket cote client, l'ecran doit basculer sur le
polling HTMX 10s de `apps/chat/api.py::list_messages` (repli obligatoire,
cf. cahier des charges)."""

from __future__ import annotations

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.chat.models import ChatChannel
from apps.chat.services.messaging import is_channel_member, post_message
from apps.core.tenant_context import activate_tenant


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self) -> None:
        self.channel_id_param = self.scope["url_route"]["kwargs"]["channel_id"]
        user = self.scope.get("user")
        # Le tenant courant n'est pas resolu par TenantMiddleware (HTTP
        # uniquement) : on le reprend de la session, exactement comme
        # TenantMiddleware._resolve_tenant_id le fait cote HTTP.
        session = self.scope.get("session") or {}
        tenant_id = session.get("tenant_id")

        if user is None or not user.is_authenticated or not tenant_id:
            await self.close(code=4001)
            return

        channel = await self._get_membership_channel(str(tenant_id), user)
        if channel is None:
            await self.close(code=4003)
            return

        self.chat_channel = channel
        self.tenant_id = str(tenant_id)
        self.group_name = f"chat_{channel.tenant_id}_{channel.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code: int) -> None:
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content: dict, **kwargs) -> None:
        body = content.get("body", "")
        user = self.scope["user"]
        message = await self._post_message(self.tenant_id, user, body)
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat.message",
                "message": {
                    "id": str(message.id),
                    "sender_id": str(message.sender_id) if message.sender_id else None,
                    "body": message.body,
                    "created_at": message.created_at.isoformat(),
                },
            },
        )

    async def chat_message(self, event: dict) -> None:
        await self.send_json(event["message"])

    @database_sync_to_async
    def _get_membership_channel(self, tenant_id: str, user) -> ChatChannel | None:
        with activate_tenant(tenant_id):
            channel = ChatChannel.objects.filter(id=self.channel_id_param).first()
            if channel is None or not is_channel_member(channel, user):
                return None
            return channel

    @database_sync_to_async
    def _post_message(self, tenant_id: str, user, body: str):
        with activate_tenant(tenant_id):
            return post_message(channel=self.chat_channel, sender=user, body=body)
