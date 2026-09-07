"""Calendrier de référence (`core/services/calendar.py`) — cahier Phase 2
§13.2, FOR-5 : jours ouvrés/fériés lus en table, jamais codés en dur.

Déplacé de `forecast` vers `core` en S5 avec le modèle et le service (cf.
`apps/core/models/calendar.py` pour le motif). Les quatre premiers tests
sont repris à l'identique ; les suivants couvrent `next_business_day` et
`business_day_on_or_after`, écrits pour la planification des flux (axe A4)
et qui n'existaient pas."""

from __future__ import annotations

import datetime as dt
import inspect

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services import calendar as calendar_service
from apps.core.services.calendar import (
    MAX_LOOKAHEAD_DAYS,
    NoBusinessDayFoundError,
    business_day_on_or_after,
    business_days_in_month,
    is_business_day,
    next_business_day,
)
from apps.core.tests.factories import HolidayFactory
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def calendar_tenant() -> Tenant:
    return Tenant.objects.create(code="CAL", name="Calendar Tenant")


def test_weekend_is_never_a_business_day(calendar_tenant: Tenant) -> None:
    with use_tenant(calendar_tenant.id):
        saturday = dt.date(2026, 9, 5)
        sunday = dt.date(2026, 9, 6)
        assert saturday.isoweekday() == 6
        assert is_business_day(calendar_tenant, saturday) is False
        assert is_business_day(calendar_tenant, sunday) is False


def test_a_registered_holiday_is_not_a_business_day(calendar_tenant: Tenant) -> None:
    with use_tenant(calendar_tenant.id):
        holiday_date = dt.date(2026, 6, 26)  # un mardi ordinaire hors weekend
        assert holiday_date.isoweekday() not in (6, 7)
        assert is_business_day(calendar_tenant, holiday_date) is True

        HolidayFactory(tenant=calendar_tenant, date=holiday_date, name="Fête de l'Indépendance")

        assert is_business_day(calendar_tenant, holiday_date) is False


def test_business_days_in_month_excludes_weekends_and_holidays(calendar_tenant: Tenant) -> None:
    with use_tenant(calendar_tenant.id):
        # Septembre 2026 : 30 jours, 8 jours de weekend (4 samedis + 4 dimanches).
        HolidayFactory(tenant=calendar_tenant, date=dt.date(2026, 9, 15), name="Jour test")
        count = business_days_in_month(calendar_tenant, 2026, 9)
        assert count == 30 - 8 - 1


def test_calendar_logic_never_hardcodes_a_holiday_date() -> None:
    """FOR-5 : « un test vérifie qu'aucune date fériée n'est écrite dans le
    code » — inspecte le SOURCE de `services/calendar.py` à la recherche
    d'un littéral `dt.date(<annee numerique>, <mois numerique>, <jour
    numerique>)` (une date figée). `dt.date(year, month, 1)`/`dt.date(year
    + 1, 1, 1)` (construits à partir des PARAMETRES de la fonction, jamais
    une date fixe) restent autorisés — seule une vraie date en dur (ex.
    `dt.date(2026, 6, 26)`) ferait échouer ce test."""
    import re

    source = inspect.getsource(calendar_service)
    literal_date_pattern = re.compile(r"dt\.date\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)")
    matches = literal_date_pattern.findall(source)
    assert matches == [], f"date(s) en dur trouvee(s) : {matches}"


def test_a_business_day_does_not_move(calendar_tenant: Tenant) -> None:
    """`business_day_on_or_after` ne décale JAMAIS une date déjà ouvrée.

    C'est la moitié qu'on oublie : une échéance qui tombe un mardi doit
    rester le mardi. La confondre avec « le jour ouvré suivant » décale
    silencieusement toute une planification d'un jour."""
    with use_tenant(calendar_tenant.id):
        mardi = dt.date(2026, 9, 8)
        assert mardi.isoweekday() == 2
        assert business_day_on_or_after(calendar_tenant, mardi) == mardi


def test_a_saturday_slides_to_the_monday(calendar_tenant: Tenant) -> None:
    with use_tenant(calendar_tenant.id):
        samedi = dt.date(2026, 9, 5)
        assert business_day_on_or_after(calendar_tenant, samedi) == dt.date(2026, 9, 7)


def test_a_bridge_is_crossed_in_one_go(calendar_tenant: Tenant) -> None:
    """Un pont de quatre jours — vendredi et lundi fériés, week-end au
    milieu. La date doit atterrir sur le mardi, pas sur le premier jour
    non-férié venu."""
    with use_tenant(calendar_tenant.id):
        vendredi = dt.date(2026, 9, 4)
        lundi = dt.date(2026, 9, 7)
        HolidayFactory(tenant=calendar_tenant, date=vendredi, name="Pont, vendredi")
        HolidayFactory(tenant=calendar_tenant, date=lundi, name="Pont, lundi")

        assert business_day_on_or_after(calendar_tenant, vendredi) == dt.date(2026, 9, 8)


def test_next_business_day_is_strictly_after(calendar_tenant: Tenant) -> None:
    """La différence entre les deux fonctions, exercée sur le cas où elle
    se voit : un mardi ouvré. `business_day_on_or_after` le rend tel quel,
    `next_business_day` rend le mercredi."""
    with use_tenant(calendar_tenant.id):
        mardi = dt.date(2026, 9, 8)
        assert business_day_on_or_after(calendar_tenant, mardi) == mardi
        assert next_business_day(calendar_tenant, mardi) == dt.date(2026, 9, 9)


def test_next_business_day_jumps_the_weekend_from_a_friday(calendar_tenant: Tenant) -> None:
    with use_tenant(calendar_tenant.id):
        vendredi = dt.date(2026, 9, 11)
        assert vendredi.isoweekday() == 5
        assert next_business_day(calendar_tenant, vendredi) == dt.date(2026, 9, 14)


def test_one_company_s_holidays_never_move_another_s_dates(calendar_tenant: Tenant) -> None:
    """Le calendrier est par société — une entreprise franche peut chômer
    des jours qu'une autre travaille. Sans ce test, une lecture qui
    oublierait le filtre `tenant` passerait inaperçue tant qu'une seule
    société existe en base."""
    autre = Tenant.objects.create(code="CAL-B", name="Autre société")
    mardi = dt.date(2026, 9, 8)
    with use_tenant(autre.id):
        HolidayFactory(tenant=autre, date=mardi, name="Chômé chez B seulement")

    with use_tenant(calendar_tenant.id):
        assert business_day_on_or_after(calendar_tenant, mardi) == mardi
    with use_tenant(autre.id):
        assert business_day_on_or_after(autre, mardi) == dt.date(2026, 9, 9)


def test_a_calendar_that_never_ends_raises_instead_of_looping(
    calendar_tenant: Tenant, monkeypatch
) -> None:
    """La borne, et pourquoi elle n'est pas décorative.

    Une société qui marquerait par erreur une année entière comme fériée
    ferait tourner cette recherche indéfiniment — dans un worker, sans
    trace, sans fin. La borne transforme une boucle infinie en une erreur
    qui nomme la cause.

    Le test ne remplit pas 366 lignes : il rend TOUT jour férié, ce qui est
    le même état vu depuis la fonction."""
    jours = {dt.date(2026, 9, 1) + dt.timedelta(days=n) for n in range(MAX_LOOKAHEAD_DAYS + 2)}
    monkeypatch.setattr(calendar_service, "_holidays_in_window", lambda tenant, start: jours)

    with use_tenant(calendar_tenant.id), pytest.raises(NoBusinessDayFoundError):
        business_day_on_or_after(calendar_tenant, dt.date(2026, 9, 1))
