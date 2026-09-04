"""Calendrier de référence (`services/calendar.py`) — cahier Phase 2
§13.2, FOR-5 : jours ouvrés/fériés lus en table, jamais codés en dur."""

from __future__ import annotations

import datetime as dt
import inspect

import pytest
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.forecast.services import calendar as calendar_service
from apps.forecast.services.calendar import business_days_in_month, is_business_day
from apps.forecast.tests.factories import ForHolidayFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def calendar_tenant() -> Tenant:
    return Tenant.objects.create(code="FOR-CAL", name="Forecast Calendar Tenant")


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

        ForHolidayFactory(tenant=calendar_tenant, date=holiday_date, name="Fête de l'Indépendance")

        assert is_business_day(calendar_tenant, holiday_date) is False


def test_business_days_in_month_excludes_weekends_and_holidays(calendar_tenant: Tenant) -> None:
    with use_tenant(calendar_tenant.id):
        # Septembre 2026 : 30 jours, 8 jours de weekend (4 samedis + 4 dimanches).
        ForHolidayFactory(tenant=calendar_tenant, date=dt.date(2026, 9, 15), name="Jour test")
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
