from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.core.services.sandbox import purge_expired_sandboxes


class Command(BaseCommand):
    help = "Supprime les tenants sandbox expirés (is_sandbox=True, sandbox_expires_at <= now)."

    def handle(self, *args, **options) -> None:
        count = purge_expired_sandboxes()
        self.stdout.write(self.style.SUCCESS(f"{count} sandbox(es) purgé(s)."))
