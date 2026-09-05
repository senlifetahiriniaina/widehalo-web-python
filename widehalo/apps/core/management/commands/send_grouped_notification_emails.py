from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models.notification import Notification
from apps.core.models.user import User
from apps.core.services.notifications import GROUPING_WINDOW, send_grouped_email_notifications


class Command(BaseCommand):
    help = (
        "Envoie le resume horaire groupe des notifications par e-mail "
        "(cahier des charges Phase 1 §9) — planifiee TOUTES LES HEURES par "
        "le registre des traitements periodiques : la fenetre est calculee "
        "comme `now - 1 h - GROUPING_WINDOW`, une cadence plus lache "
        "laisserait des notifications hors fenetre, jamais envoyees. Jamais "
        "depuis le cycle de requete HTTP qui cree une notification."
    )

    def handle(self, *args: object, **options: object) -> None:
        since = timezone.now() - timedelta(hours=1) - GROUPING_WINDOW
        user_ids = (
            Notification.objects.filter(created_at__gte=since, email_sent_at__isnull=True)
            .values_list("user_id", flat=True)
            .distinct()
        )
        users = User.objects.filter(id__in=list(user_ids))

        total_emails = 0
        total_notifications = 0
        for user in users:
            sent = send_grouped_email_notifications(user)
            if sent:
                total_emails += 1
                total_notifications += sent

        self.stdout.write(
            self.style.SUCCESS(
                f"{total_emails} e-mail(s) envoyé(s), "
                f"{total_notifications} notification(s) au total."
            )
        )
