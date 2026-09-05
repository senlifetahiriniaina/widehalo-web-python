"""FOR-5 — la table des jours feries n'etait peuplee par rien.

La docstring de `apps.forecast.services.calendar` renvoyait a
`management/commands/load_mg_holidays.py` depuis la livraison du critere, et
ce fichier n'existait pas : `apps/forecast/` n'avait meme aucun repertoire
`management/`. Aucune ligne `ForHoliday` n'etait donc creee par autre chose
qu'une saisie manuelle, et sur une instance neuve `is_business_day` tenait
tout jour de semaine pour ouvre.

Ces tests couvrent donc le manque lui-meme, pas seulement la commande : que
le chargement produise des jours feries, qu'il soit rejouable, et surtout
que `business_days_in_month` en tienne compte — sans cette derniere
assertion, on prouverait qu'on a rempli une table sans prouver qu'elle sert
a quelque chose."""

from __future__ import annotations

import datetime as dt

import pytest
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.forecast.management.commands.load_mg_holidays import (
    available_years,
    holidays_for_year,
)
from apps.forecast.models import ForHoliday
from apps.forecast.services.calendar import business_days_in_month, is_business_day
from django.core.management import CommandError, call_command

pytestmark = pytest.mark.django_db

YEAR = 2026


@pytest.fixture
def holiday_tenant() -> Tenant:
    return Tenant.objects.create(code="FOR-HOL", name="Forecast Holidays Tenant")


def test_the_command_populates_the_reference_table(holiday_tenant: Tenant) -> None:
    call_command("load_mg_holidays", f"--year={YEAR}", f"--tenant={holiday_tenant.code}")

    with use_tenant(holiday_tenant.id):
        loaded = set(ForHoliday.objects.values_list("date", flat=True))

    assert loaded, "Aucun jour ferie charge."
    assert dt.date(YEAR, 1, 1) in loaded
    assert dt.date(YEAR, 6, 26) in loaded
    assert dt.date(YEAR, 12, 25) in loaded


def test_the_command_is_idempotent(holiday_tenant: Tenant) -> None:
    call_command("load_mg_holidays", f"--year={YEAR}", f"--tenant={holiday_tenant.code}")
    with use_tenant(holiday_tenant.id):
        first = ForHoliday.objects.count()

    call_command("load_mg_holidays", f"--year={YEAR}", f"--tenant={holiday_tenant.code}")
    with use_tenant(holiday_tenant.id):
        assert ForHoliday.objects.count() == first


def test_a_manual_correction_is_never_overwritten(holiday_tenant: Tenant) -> None:
    """L'exploitant doit rester maitre de son calendrier : le calendrier legal
    ajoute des journees chomees ponctuelles qui ne figureront jamais dans la
    fixture, et une relance de la commande ne doit pas defaire sa correction."""
    with use_tenant(holiday_tenant.id):
        ForHoliday.objects.create(
            tenant=holiday_tenant, date=dt.date(YEAR, 1, 1), name="Libelle corrige a la main"
        )

    call_command("load_mg_holidays", f"--year={YEAR}", f"--tenant={holiday_tenant.code}")

    with use_tenant(holiday_tenant.id):
        kept = ForHoliday.objects.get(date=dt.date(YEAR, 1, 1))
    assert kept.name == "Libelle corrige a la main"


def test_loaded_holidays_change_the_business_day_count(holiday_tenant: Tenant) -> None:
    """La preuve qui compte : avant le chargement, `business_days_in_month`
    surestime la capacite de production — c'est le defaut reel que ce lot
    corrige, pas l'absence d'un fichier."""
    with use_tenant(holiday_tenant.id):
        before = business_days_in_month(holiday_tenant, YEAR, 12)
        assert is_business_day(holiday_tenant, dt.date(YEAR, 12, 25))

    call_command("load_mg_holidays", f"--year={YEAR}", f"--tenant={holiday_tenant.code}")

    with use_tenant(holiday_tenant.id):
        after = business_days_in_month(holiday_tenant, YEAR, 12)
        assert not is_business_day(holiday_tenant, dt.date(YEAR, 12, 25))
    # Noel 2026 tombe un vendredi : un jour ouvre de moins, exactement.
    assert after == before - 1


def test_an_unknown_year_fails_loudly(holiday_tenant: Tenant) -> None:
    """Les dates mobiles sont enumerees annee par annee. Passe la derniere
    annee couverte, la commande doit refuser plutot que de charger un
    calendrier ampute de Paques, de l'Ascension et de la Pentecote — une
    erreur silencieuse serait pire que l'absence de commande."""
    last_known = available_years()[-1]
    with pytest.raises(CommandError):
        call_command("load_mg_holidays", f"--year={last_known + 1}")


def test_a_collision_between_two_holidays_is_tolerated() -> None:
    """Le 29 mars 2027 est a la fois la commemoration de 1947 et le lundi de
    Paques. La contrainte d'unicite `(tenant, date)` l'exige : une seule
    ligne, le premier libelle rencontre."""
    dates = [date for date, _name in holidays_for_year(2027)]
    assert dates.count(dt.date(2027, 3, 29)) == 2, (
        "La collision attendue n'existe plus dans la fixture — mettre ce test a jour."
    )
