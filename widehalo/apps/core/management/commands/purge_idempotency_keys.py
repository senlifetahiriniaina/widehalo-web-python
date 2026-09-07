"""Commande ops (S4) : purge des clefs d'idempotence perimees.

Le TTL de 24 h existait sur le modele depuis l'origine et n'etait applique
nulle part : la table conservait une ligne par appel idempotent, avec le
corps complet de la reponse, indefiniment. Meme patron que
`purge_expired_sandboxes` et `purge_expired_report_jobs` — la commande ne
porte aucune logique, elle delegue a un service qui renvoie un compte.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.core.services.idempotency_purge import purge_expired_idempotency_keys


class Command(BaseCommand):
    help = "Supprime les clefs d'idempotence expirees (expires_at <= now, TTL 24 h)."

    def handle(self, *args, **options) -> None:
        count = purge_expired_idempotency_keys()
        self.stdout.write(self.style.SUCCESS(f"{count} clé(s) d'idempotence purgée(s)."))
