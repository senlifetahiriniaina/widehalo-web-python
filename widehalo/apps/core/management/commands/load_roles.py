from __future__ import annotations

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from apps.core.models.rbac import RoleProfile


class Command(BaseCommand):
    help = "Cree les 11 roles standards V1 (settings.CORE_STANDARD_ROLES) comme Group+RoleProfile."

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
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(settings.CORE_STANDARD_ROLES)} rôles vérifiés, {created} créés."
            )
        )
