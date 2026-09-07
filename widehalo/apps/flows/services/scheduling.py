"""S5 (Phase 4, bloc A) — planification adossée au calendrier malgache.

**Le champ était déclaré et écrit par personne.** `FlwSchedule.next_run_at`
existe depuis S1, avec une docstring qui annonce « écrit par le répartiteur,
jamais saisi à la main » — et aucun répartiteur. Une planification créée
gardait donc `next_run_at = NULL` pour toujours : jamais due, jamais
exécutée, et rien pour le signaler. C'est le même motif que la file
WhatsApp du lot L10, et que `FlwSchedule` lui-même documentait sans le voir.

**Le calendrier.** Le cahier (axe A4) veut une planification « adossée au
calendrier malgache ». Ce calendrier vit désormais dans `core`
(`core.Holiday`, remonté de `forecast` par ce même sprint) : `flows` le lit
sans rompre la règle de couplage n°1.

**Ce que « décaler » veut dire, précisément.** Une échéance qui tombe un
jour non ouvré GLISSE, elle n'échoue pas et elle ne saute pas. Sauter
signifierait qu'un relevé mensuel tombant un 1er mai n'aurait jamais lieu
ce mois-là ; échouer transformerait un jour férié en incident.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import TYPE_CHECKING

from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.services.calendar import business_day_on_or_after
from apps.core.tenant_context import activate_tenant
from apps.flows.models import FlwExchange, FlwLink, FlwSchedule

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

#: Nombre de jours d'un « mois » de planification quand le quantième
#: n'existe pas dans le mois suivant (un 31 en février). On CLAMPE au
#: dernier jour du mois plutôt que de déborder sur le mois d'après : une
#: planification du 31 qui glisserait au 3 mars aurait sauté février.
_LAST_DAY_SENTINEL = 31


def _local_midnight(moment: dt.datetime) -> dt.datetime:
    local = timezone.localtime(moment)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def _at_hour(date: dt.date, hour: int) -> dt.datetime:
    """Une date locale + une heure locale, rendue en datetime conscient.

    L'heure d'une planification est celle de l'exploitant, pas celle du
    serveur : un relevé « à 2 h » doit tomber à 2 h à Antananarivo, quel
    que soit le fuseau de la machine qui exécute le répartiteur."""
    naive = dt.datetime.combine(date, dt.time(hour=hour))
    return timezone.make_aware(naive, timezone.get_current_timezone())


def _add_one_month(date: dt.date) -> dt.date:
    """Même quantième le mois suivant, ramené au dernier jour du mois quand
    il n'existe pas (31 janvier -> 28 ou 29 février)."""
    year = date.year + (1 if date.month == 12 else 0)
    month = 1 if date.month == 12 else date.month + 1
    for day in range(date.day, 0, -1):
        try:
            return dt.date(year, month, day)
        except ValueError:
            continue
    raise AssertionError("un mois a toujours un premier jour")


def compute_next_run_at(schedule: FlwSchedule, *, after: dt.datetime | None = None) -> dt.datetime:
    """La prochaine échéance, décalée sur un jour ouvré si la liaison le
    demande.

    STRICTEMENT après `after` : une planification qui rendrait l'instant
    courant serait immédiatement due à nouveau, et le répartiteur
    boucherait la file d'un même échange à chaque passage."""
    reference = timezone.localtime(after or timezone.now())

    if schedule.frequency == FlwSchedule.FREQUENCY_HOURLY:
        candidate = reference.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
    else:
        candidate = _at_hour(reference.date(), schedule.hour)
        if candidate <= reference:
            candidate = _at_hour(reference.date() + dt.timedelta(days=1), schedule.hour)
        if schedule.frequency == FlwSchedule.FREQUENCY_WEEKLY:
            candidate = _at_hour(candidate.date() + dt.timedelta(days=6), schedule.hour)
        elif schedule.frequency == FlwSchedule.FREQUENCY_MONTHLY:
            candidate = _at_hour(_add_one_month(reference.date()), schedule.hour)
            if candidate <= reference:
                candidate = _at_hour(_add_one_month(candidate.date()), schedule.hour)

    if not schedule.skip_public_holidays:
        return candidate

    jour_ouvre = business_day_on_or_after(schedule.tenant, candidate.date())
    if jour_ouvre == candidate.date():
        return candidate
    # Le report change de JOUR : une planification horaire reprend au début
    # du jour ouvré suivant, une planification datée y retrouve son heure.
    heure = 0 if schedule.frequency == FlwSchedule.FREQUENCY_HOURLY else schedule.hour
    return _at_hour(jour_ouvre, heure)


def arm_schedule(schedule: FlwSchedule, *, after: dt.datetime | None = None) -> FlwSchedule:
    """Pose la première échéance d'une planification qui n'en a pas.

    À appeler à la CRÉATION. Sans elle, `next_run_at` reste nul et la
    planification n'est jamais due — c'est exactement l'état dans lequel le
    dépôt se trouvait avant ce sprint."""
    if schedule.next_run_at is None:
        schedule.next_run_at = compute_next_run_at(schedule, after=after)
        schedule.save(update_fields=["next_run_at"])
    return schedule


def due_schedules(now: dt.datetime | None = None) -> list[FlwSchedule]:
    """Les planifications dues dans le contexte de société ACTIF.

    `next_run_at__isnull=False` est explicite plutôt qu'implicite : une
    planification jamais armée ne doit pas être due, et le dire ici évite
    de dépendre du fait que `NULL <= now` est faux en SQL — vrai, mais
    invisible à la lecture."""
    moment = now or timezone.now()
    return list(
        FlwSchedule.objects.filter(
            is_active=True,
            next_run_at__isnull=False,
            next_run_at__lte=moment,
            link__state=FlwLink.STATE_ACTIVE,
        ).select_related("link")
    )


def occurrence_key(schedule: FlwSchedule, moment: dt.datetime) -> str:
    """Ce qui distingue DEUX PASSAGES d'une même planification.

    Entre dans la clef d'idempotence (cf. `services/idempotency.py`). Sans
    elle, deux relevés quotidiens sans pièce porteraient la même clef et le
    second serait refusé par la contrainte d'unicité — la planification
    mourrait au deuxième jour, sans trace."""
    return f"{schedule.id}@{timezone.localtime(moment).isoformat(timespec='minutes')}"


def scope_body(schedule: FlwSchedule, moment: dt.datetime) -> str:
    """Le corps d'un échange planifié : LA DEMANDE, pas la donnée.

    **Ce qui manquait.** `run_schedule` appelait `prepare_exchange` sans
    corps : chaque passage produisait un échange à empreinte vide, ce que
    FLX-1 interdit expressément (« ou si un échange est écrit sans
    empreinte de contenu »). Une planification née un lundi et une née un
    mardi étaient, dans le registre, deux lignes rigoureusement
    indiscernables par leur contenu.

    **Pourquoi la fenêtre, et pas les données.** La planification ne
    possède aucune donnée métier, et `flows` n'a pas le droit d'aller la
    chercher : la règle de couplage n°1 lui interdit d'importer le modèle
    d'un module métier. Ce qu'elle possède, en revanche, c'est la DEMANDE —
    quelle opération, sur quelle fenêtre, à quel passage. Le cahier la
    nomme d'ailleurs comme la contrainte propre d'OP2 : « fenêtre de
    portée, différentiel depuis le dernier envoi, sinon le volume
    explose ». La planification porte la demande, l'adaptateur la sert.

    `window_start` est le passage PRÉCÉDENT — c'est ce qui fait du
    différentiel un différentiel. Nul au premier passage, et c'est
    l'information juste : il n'y a pas d'envoi précédent dont se
    différencier.
    """
    return json.dumps(
        {
            "occurrence": occurrence_key(schedule, moment),
            "operation": schedule.operation,
            "window_start": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
            "window_end": moment.isoformat(),
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def run_schedule(schedule: FlwSchedule, *, now: dt.datetime | None = None) -> FlwExchange:
    """Fait naître l'échange d'un passage, puis réarme la planification.

    Ne rend jamais un échange PARTI : il est mis en file, et c'est
    `process_outbound_queue` qui l'émet. Deux raisons, et la seconde est la
    plus importante : la file porte le disjoncteur et l'espacement de
    réessai (S3), et un répartiteur qui appellerait le tiers lui-même les
    contournerait tous les deux."""
    from apps.flows.services.exchange import prepare_exchange
    from apps.flows.services.queue import queue_exchange

    moment = now or timezone.now()
    exchange = prepare_exchange(
        schedule.tenant,
        schedule.link,
        operation=schedule.operation,
        document_type="",
        document_id=None,
        body=scope_body(schedule, moment),
    )
    queue_exchange(exchange, occurrence=occurrence_key(schedule, moment))

    schedule.last_run_at = moment
    schedule.next_run_at = compute_next_run_at(schedule, after=moment)
    schedule.save(update_fields=["last_run_at", "next_run_at"])
    return exchange


def run_due_schedules(now: dt.datetime | None = None) -> dict[str, int]:
    """Boucle par société, un échec de société n'en prive jamais une autre.

    Même discipline que `core.services.scheduled_commands.tenant_step` et
    que `reporting.services.scheduling.run_due_schedules` — reprise plutôt
    qu'inventée."""
    moment = now or timezone.now()
    totaux = {"queued": 0, "failed": 0}
    for tenant_id in Tenant.objects.values_list("id", flat=True):
        try:
            with activate_tenant(tenant_id):
                for schedule in due_schedules(moment):
                    run_schedule(schedule, now=moment)
                    totaux["queued"] += 1
        except Exception:  # noqa: BLE001 — une société en échec n'en prive jamais une autre
            totaux["failed"] += 1
            logger.exception("Planification de flux en échec pour la société %s", tenant_id)
    return totaux
