from __future__ import annotations

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from apps.core.models.rbac import RoleProfile
from apps.core.services.rbac_policy import sync_group_permissions


class Command(BaseCommand):
    help = (
        "Cree les roles standards (settings.CORE_STANDARD_ROLES) comme "
        "Group+RoleProfile, et (re)synchronise leurs permissions Django selon "
        "apps.core.services.rbac_policy.ROLE_APP_PERMISSIONS — idempotent, a "
        "relancer si cette politique est modifiee."
    )

    def handle(self, *args, **options) -> None:
        created = 0
        for code in settings.CORE_STANDARD_ROLES:
            group, _ = Group.objects.get_or_create(name=code)
            _, was_created = RoleProfile.objects.get_or_create(
                group=group,
                defaults={
                    "code": code,
                    "simple_mode_default": code in settings.CORE_SIMPLE_MODE_ROLES,
                },
            )
            created += int(was_created)
            sync_group_permissions(group, code)
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(settings.CORE_STANDARD_ROLES)} rôles vérifiés, {created} créés, "
                f"permissions synchronisées."
            )
        )
