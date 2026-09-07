"""S5 — planification adossée au calendrier malgache (axe A4).

**Le défaut d'abord, parce qu'il explique tout le reste.**
`FlwSchedule.next_run_at` est déclaré depuis S1, avec une docstring qui
annonce « écrit par le répartiteur, jamais saisi à la main ». Il n'y avait
pas de répartiteur. Une planification créée gardait donc `next_run_at`
NUL — jamais due, jamais exécutée, et rien pour le signaler. Une
fonctionnalité complète, documentée, et inerte : le motif exact que ce
dépôt corrige depuis le premier lot.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.core.tests.factories import HolidayFactory
from apps.core.tests.utils import use_tenant
from apps.flows.models import FlwExchange, FlwLink, FlwSchedule
from apps.flows.services.scheduling import (
    arm_schedule,
    compute_next_run_at,
    due_schedules,
    run_due_schedules,
    run_schedule,
)
from apps.flows.tests.factories import FlwLinkFactory, FlwScheduleFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def societe():
    return Tenant.objects.create(code="S5-PLAN", name="Planification SARL")


@pytest.fixture
def liaison(societe):
    with use_tenant(societe.id):
        return FlwLinkFactory(tenant=societe, state=FlwLink.STATE_ACTIVE)


def _moment(annee: int, mois: int, jour: int, heure: int = 12) -> dt.datetime:
    """Un instant LOCAL — l'heure d'une planification est celle de
    l'exploitant, pas celle du serveur."""
    return timezone.make_aware(
        dt.datetime(annee, mois, jour, heure), timezone.get_current_timezone()
    )


# --- Le calcul de l'échéance --------------------------------------------------


def test_a_daily_schedule_lands_on_its_hour_the_next_day(societe, liaison) -> None:
    with use_tenant(societe.id):
        planification = FlwScheduleFactory(
            tenant=societe,
            link=liaison,
            frequency=FlwSchedule.FREQUENCY_DAILY,
            hour=2,
            skip_public_holidays=False,
        )
        # Mercredi 9 septembre 2026, midi : 2 h est déjà passée.
        echeance = compute_next_run_at(planification, after=_moment(2026, 9, 9, 12))
    assert timezone.localtime(echeance) == _moment(2026, 9, 10, 2)


def test_a_daily_schedule_lands_today_when_the_hour_is_still_ahead(societe, liaison) -> None:
    """Le cas symétrique, et celui qu'on oublie : à 1 h du matin, la
    prochaine échéance de 2 h est dans une heure, pas demain."""
    with use_tenant(societe.id):
        planification = FlwScheduleFactory(
            tenant=societe,
            link=liaison,
            frequency=FlwSchedule.FREQUENCY_DAILY,
            hour=2,
            skip_public_holidays=False,
        )
        echeance = compute_next_run_at(planification, after=_moment(2026, 9, 9, 1))
    assert timezone.localtime(echeance) == _moment(2026, 9, 9, 2)


def test_an_hourly_schedule_lands_on_the_next_round_hour(societe, liaison) -> None:
    with use_tenant(societe.id):
        planification = FlwScheduleFactory(
            tenant=societe,
            link=liaison,
            frequency=FlwSchedule.FREQUENCY_HOURLY,
            skip_public_holidays=False,
        )
        depart = _moment(2026, 9, 9, 12) + dt.timedelta(minutes=37)
        echeance = compute_next_run_at(planification, after=depart)
    assert timezone.localtime(echeance) == _moment(2026, 9, 9, 13)


def test_a_monthly_schedule_never_skips_a_month(societe, liaison) -> None:
    """Le 31 janvier n'existe pas en février. Le CLAMP au dernier jour du
    mois est ce qui évite qu'une planification mensuelle saute février —
    un débordement au 3 mars aurait sauté le mois entier."""
    with use_tenant(societe.id):
        planification = FlwScheduleFactory(
            tenant=societe,
            link=liaison,
            frequency=FlwSchedule.FREQUENCY_MONTHLY,
            hour=3,
            skip_public_holidays=False,
        )
        echeance = compute_next_run_at(planification, after=_moment(2026, 1, 31, 12))
    assert timezone.localtime(echeance).date() == dt.date(2026, 2, 28)


def test_a_weekly_schedule_lands_seven_days_later(societe, liaison) -> None:
    with use_tenant(societe.id):
        planification = FlwScheduleFactory(
            tenant=societe,
            link=liaison,
            frequency=FlwSchedule.FREQUENCY_WEEKLY,
            hour=4,
            skip_public_holidays=False,
        )
        echeance = compute_next_run_at(planification, after=_moment(2026, 9, 9, 12))
    assert timezone.localtime(echeance) == _moment(2026, 9, 16, 4)


# --- Le calendrier malgache ---------------------------------------------------


def test_an_deadline_falling_on_a_holiday_slides_to_the_next_business_day(societe, liaison) -> None:
    """Le critère de l'axe A4. Elle GLISSE : elle ne saute pas (le relevé du
    mois n'aurait jamais lieu) et elle n'échoue pas (un jour férié
    deviendrait un incident)."""
    with use_tenant(societe.id):
        HolidayFactory(tenant=societe, date=dt.date(2026, 9, 10), name="Journée chômée")
        planification = FlwScheduleFactory(
            tenant=societe,
            link=liaison,
            frequency=FlwSchedule.FREQUENCY_DAILY,
            hour=2,
            skip_public_holidays=True,
        )
        echeance = compute_next_run_at(planification, after=_moment(2026, 9, 9, 12))
    assert timezone.localtime(echeance) == _moment(2026, 9, 11, 2), (
        "L'échéance n'a pas glissé sur le jour ouvré suivant."
    )


def test_a_saturday_deadline_slides_to_the_monday(societe, liaison) -> None:
    with use_tenant(societe.id):
        planification = FlwScheduleFactory(
            tenant=societe,
            link=liaison,
            frequency=FlwSchedule.FREQUENCY_DAILY,
            hour=2,
            skip_public_holidays=True,
        )
        # Vendredi 4 septembre midi -> samedi 5 -> glisse au lundi 7.
        echeance = compute_next_run_at(planification, after=_moment(2026, 9, 4, 12))
    assert timezone.localtime(echeance) == _moment(2026, 9, 7, 2)


def test_a_link_that_asks_for_no_shift_never_slides(societe, liaison) -> None:
    """La contrepartie : `skip_public_holidays` est un réglage, pas une
    règle. Un relevé bancaire peut vouloir tourner un dimanche."""
    with use_tenant(societe.id):
        HolidayFactory(tenant=societe, date=dt.date(2026, 9, 10), name="Journée chômée")
        planification = FlwScheduleFactory(
            tenant=societe,
            link=liaison,
            frequency=FlwSchedule.FREQUENCY_DAILY,
            hour=2,
            skip_public_holidays=False,
        )
        echeance = compute_next_run_at(planification, after=_moment(2026, 9, 9, 12))
    assert timezone.localtime(echeance) == _moment(2026, 9, 10, 2)


# --- Le répartiteur -----------------------------------------------------------


def test_a_schedule_is_never_due_before_being_armed(societe, liaison) -> None:
    """L'état dans lequel se trouvait TOUT le dépôt avant ce sprint."""
    with use_tenant(societe.id):
        planification = FlwScheduleFactory(tenant=societe, link=liaison)
        assert planification.next_run_at is None
        assert due_schedules(_moment(2030, 1, 1)) == []

        arm_schedule(planification, after=_moment(2026, 9, 9, 12))
        planification.refresh_from_db()
        assert planification.next_run_at is not None
        assert due_schedules(_moment(2030, 1, 1)) == [planification]


def test_running_a_schedule_queues_an_exchange_and_rearms(societe, liaison) -> None:
    with use_tenant(societe.id):
        planification = FlwScheduleFactory(
            tenant=societe,
            link=liaison,
            operation="RELEVE",
            frequency=FlwSchedule.FREQUENCY_DAILY,
            hour=2,
            skip_public_holidays=False,
        )
        arm_schedule(planification, after=_moment(2026, 9, 9, 12))
        echange = run_schedule(planification, now=_moment(2026, 9, 10, 2))

        assert echange.state == FlwExchange.STATE_QUEUED, (
            "Le répartiteur a émis lui-même : il aurait contourné le "
            "disjoncteur et l'espacement de réessai de la file (S3)."
        )
        assert echange.operation == "RELEVE"
        planification.refresh_from_db()
        assert planification.last_run_at == _moment(2026, 9, 10, 2)
        assert timezone.localtime(planification.next_run_at) == _moment(2026, 9, 11, 2)


def test_two_runs_of_the_same_schedule_do_not_collide(societe, liaison) -> None:
    """**Le défaut trouvé en écrivant le répartiteur, pas en relisant le
    code.**

    La clef d'idempotence était calculée sur (liaison, pièce, opération,
    rang de rejeu). Une planification n'a PAS de pièce : deux passages
    successifs produisaient donc la même clef, et le second violait
    `uniq_flw_exchange_idempotency_key`. La planification serait morte au
    deuxième jour, en silence.

    Le passage entre désormais dans la clef — deux passages différents sont
    deux échanges légitimes, deux tentatives d'un même passage n'en font
    qu'un."""
    with use_tenant(societe.id):
        planification = FlwScheduleFactory(
            tenant=societe,
            link=liaison,
            operation="RELEVE",
            frequency=FlwSchedule.FREQUENCY_DAILY,
            hour=2,
            skip_public_holidays=False,
        )
        arm_schedule(planification, after=_moment(2026, 9, 9, 12))

        premier = run_schedule(planification, now=_moment(2026, 9, 10, 2))
        second = run_schedule(planification, now=_moment(2026, 9, 11, 2))

        assert premier.idempotency_key and second.idempotency_key
        assert premier.idempotency_key != second.idempotency_key, (
            "Deux passages portent la même clef : le second serait refusé par "
            "la contrainte d'unicité et la planification mourrait au deuxième jour."
        )
        assert FlwExchange.objects.filter(link=liaison).count() == 2


def test_a_draft_link_never_produces_an_exchange(societe) -> None:
    """Une liaison non activée ne doit rien émettre — c'est le sens même de
    l'état « brouillon », et une planification créée pendant la
    configuration ne doit pas partir avant l'activation."""
    with use_tenant(societe.id):
        brouillon = FlwLinkFactory(tenant=societe, state=FlwLink.STATE_DRAFT)
        planification = FlwScheduleFactory(tenant=societe, link=brouillon)
        arm_schedule(planification, after=_moment(2026, 9, 9, 12))
        assert due_schedules(_moment(2030, 1, 1)) == []


def test_an_inactive_schedule_is_never_due(societe, liaison) -> None:
    with use_tenant(societe.id):
        planification = FlwScheduleFactory(tenant=societe, link=liaison, is_active=False)
        arm_schedule(planification, after=_moment(2026, 9, 9, 12))
        assert due_schedules(_moment(2030, 1, 1)) == []


def test_one_company_s_schedules_never_run_for_another(societe, liaison) -> None:
    """`run_due_schedules` boucle sur toutes les sociétés — c'est
    précisément la boucle où une erreur d'isolation ne se voit pas, puisque
    tout finit par tourner."""
    autre = Tenant.objects.create(code="S5-PLAN-B", name="Autre SARL")
    with use_tenant(societe.id):
        planification = FlwScheduleFactory(tenant=societe, link=liaison, operation="CHEZ-A")
        arm_schedule(planification, after=_moment(2026, 9, 9, 12))

    totaux = run_due_schedules(_moment(2030, 1, 1))

    assert totaux == {"queued": 1, "failed": 0}
    with use_tenant(societe.id):
        assert FlwExchange.objects.filter(operation="CHEZ-A").count() == 1
    with use_tenant(autre.id):
        assert FlwExchange.objects.count() == 0
