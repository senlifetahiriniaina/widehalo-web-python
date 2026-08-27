"""Jeu de demonstration `chat` (T10, couche 14 CDC — TST-3) : un canal
contextuel rattache au `Tenant` demo lui-meme (content-type generique —
n'importe quel objet metier convient, le tenant est le choix le plus
simple qui ne depend d'aucun autre module) avec deux utilisateurs membres
et deux messages postes via `services/messaging.py::post_message`.

Note d'implementation : `services/public.py::get_or_create_document_channel`
fait exactement ce dont ce seed a besoin, mais l'appeler DEPUIS l'app
`chat` elle-meme (plutot que depuis un module metier tiers, son public
normal) declencherait a tort le garde-fou d'architecture
`test_declared_dependencies_match_module_spec` (qui ne fait pas
d'exception pour un import "public" d'une app vers elle-meme — cf.
`tests/architecture/test_module_boundaries.py`). On reproduit donc ici,
avec les memes modeles `chat` (autorises, on est dans l'app elle-meme),
la meme logique idempotente plutot que d'importer la surface publique.

`chat` est deliberement exclu de la politique RBAC par app
(`apps.core.services.rbac_policy`, cf. sa docstring) — tout utilisateur
authentifie y a acces, seule l'appartenance au canal (deja verifiee cote
service) protege son contenu. Les utilisateurs demo crees ici recoivent
neanmoins un role metier (`resp_production`/`commercial`) pour rester
utilisables sur les autres endpoints de la campagne Schemathesis.

**Idempotence** : le canal est retrouve par content-type+object_id (ne
cree que les membres manquants). Les deux messages de demo ne sont postes
que si le canal n'en contient encore aucun — une relance ne duplique donc
rien."""

from __future__ import annotations

from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandParser

from apps.chat.models import ChatChannel, ChatChannelMembership
from apps.chat.services.messaging import post_message
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.rbac_policy import sync_group_permissions
from apps.core.tenant_context import activate_tenant


class Command(BaseCommand):
    help = "Jeu de demonstration chat (canal contextuel + messages) — prealable Schemathesis (T10)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant-code", default="DEMO")

    def handle(self, *args, **options) -> None:
        tenant_code = options["tenant_code"]

        tenant, _ = Tenant.objects.get_or_create(
            code=tenant_code, defaults={"name": "WideHalo Demo", "country_code": "MG"}
        )

        with activate_tenant(tenant.id):
            self._seed(tenant, tenant_code)

    def _seed(self, tenant: Tenant, tenant_code: str) -> None:
        user_one = self._demo_user(tenant_code, "demo.production", "resp_production")
        user_two = self._demo_user(tenant_code, "demo.commercial", "commercial")

        content_type = ContentType.objects.get_for_model(Tenant)
        channel, _created = ChatChannel.objects.get_or_create(
            tenant=tenant,
            content_type=content_type,
            object_id=str(tenant.id),
            defaults={"kind": ChatChannel.KIND_CONTEXT, "title": "Discussion demo"},
        )
        for user in (user_one, user_two):
            ChatChannelMembership.objects.get_or_create(tenant=tenant, channel=channel, user=user)

        if not channel.messages.exists():
            post_message(
                channel=channel, sender=user_one, body="Bonjour, ceci est un jeu de demonstration."
            )
            post_message(
                channel=channel, sender=user_two, body="Bien recu, message de demonstration."
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"chat: canal={channel.id} ({channel.memberships.count()} membre(s), "
                f"{channel.messages.count()} message(s))."
            )
        )

    @staticmethod
    def _demo_user(tenant_code: str, local_part: str, role_code: str) -> User:
        user, was_created = User.objects.get_or_create(
            email=f"{local_part}@{tenant_code.lower()}.widehalo.local",
            defaults={"is_staff": False, "is_superuser": False},
        )
        if was_created:
            user.set_password("Str0ngPassw0rd!23")
            user.save(update_fields=["password"])
        group, _ = Group.objects.get_or_create(name=role_code)
        sync_group_permissions(group, role_code)
        user.groups.add(group)
        return user
