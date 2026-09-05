"""Seul point d'appel a Django-Q2 dans tout le projet — permet de basculer
vers un autre backend (Celery) sans modifier le reste du code. Verifie par
`tests/architecture/test_no_direct_task_queue_usage.py`."""

from __future__ import annotations

import logging
from typing import Any


def enqueue(func: Any, *args: Any, task_name: str | None = None, **kwargs: Any) -> str:
    from django_q.tasks import async_task

    task_id: str = async_task(func, *args, task_name=task_name, **kwargs)
    return task_id


# Prefixe des planifications gerees par le registre. Il isole ce que ce depot
# possede de ce qu'un operateur aurait pu creer a la main : la synchronisation
# ne supprime jamais une planification qui ne porte pas ce prefixe.
logger = logging.getLogger(__name__)

_SCHEDULE_NAME_PREFIX = "widehalo:"


def run_scheduled_command(code: str) -> None:
    """Point d'entree appele par l'ordonnanceur pour une commande periodique.

    Passe par le registre plutot que par un nom de commande fige dans l'objet
    `Schedule` : la cadence vit en base, la definition reste dans le code de
    l'app proprietaire, et une commande retiree du registre cesse d'etre
    executee meme si sa planification survit en base."""
    from django.core.management import call_command

    from apps.core.services.scheduled_commands import get_scheduled_command

    entry = get_scheduled_command(code)
    if entry is None:
        logger.warning(
            "Planification %r declenchee alors que la commande n'est plus "
            "enregistree — execution ignoree.",
            code,
        )
        return
    call_command(entry.command)


def sync_schedules() -> dict[str, int]:
    """Aligne les objets `Schedule` de django-q2 sur le registre.

    **Seul endroit du depot qui ecrit une planification**, et seul fichier
    autorise a importer `django_q` (garde
    `tests/architecture/test_no_direct_task_queue_usage.py`).

    Volontairement appelee par une commande de deploiement et non depuis
    `AppConfig.ready()` : toucher la base au chargement des applications
    casserait `migrate` sur une base neuve et ferait dependre le demarrage du
    serveur de l'etat de la base. Les `ready()` DECLARENT, le deploiement
    SYNCHRONISE.

    Retourne le nombre de planifications creees, mises a jour et supprimees —
    une planification orpheline (commande retiree du registre) est supprimee,
    sans quoi le registre cesserait d'etre la source de verite."""
    import datetime as dt

    from django.utils import timezone
    from django_q.models import Schedule

    from apps.core.services.scheduled_commands import (
        FREQUENCY_DAILY,
        FREQUENCY_HOURLY,
        FREQUENCY_MONTHLY,
        FREQUENCY_WEEKLY,
        list_scheduled_commands,
    )

    schedule_type_by_frequency = {
        FREQUENCY_HOURLY: Schedule.HOURLY,
        FREQUENCY_DAILY: Schedule.DAILY,
        FREQUENCY_WEEKLY: Schedule.WEEKLY,
        FREQUENCY_MONTHLY: Schedule.MONTHLY,
    }

    now = timezone.localtime()
    created = updated = 0
    known_names: set[str] = set()

    for entry in list_scheduled_commands():
        name = f"{_SCHEDULE_NAME_PREFIX}{entry.code}"
        known_names.add(name)
        if entry.frequency == FREQUENCY_HOURLY:
            next_run = (now + dt.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        else:
            next_run = now.replace(hour=entry.hour, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += dt.timedelta(days=1)

        _, was_created = Schedule.objects.update_or_create(
            name=name,
            defaults={
                "func": "apps.core.tasks.run_scheduled_command",
                "args": repr((entry.code,)),
                "schedule_type": schedule_type_by_frequency[entry.frequency],
                "repeats": -1,
                "next_run": next_run,
            },
        )
        created += int(was_created)
        updated += int(not was_created)

    deleted, _ = (
        Schedule.objects.filter(name__startswith=_SCHEDULE_NAME_PREFIX)
        .exclude(name__in=known_names)
        .delete()
    )
    return {"created": created, "updated": updated, "deleted": deleted}
