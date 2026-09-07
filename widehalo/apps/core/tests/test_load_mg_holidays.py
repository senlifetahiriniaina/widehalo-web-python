"""FOR-5 — la table des jours feries n'etait peuplee par rien.

La docstring de `apps.core.services.calendar` renvoyait a
`management/commands/load_mg_holidays.py` depuis la livraison du critere, et
ce fichier n'existait pas : le module proprietaire de l'epoque
(`apps/forecast/`, avant le deplacement du calendrier vers `core` en S5)
n'avait meme aucun repertoire `management/`. Aucune ligne `Holiday` n'etait
donc creee par autre chose qu'une saisie manuelle, et sur une instance neuve
`is_business_day` tenait tout jour de semaine pour ouvre.

Ces tests couvrent donc le manque lui-meme, pas seulement la commande : que
le chargement produise des jours feries, qu'il soit rejouable, et surtout
que `business_days_in_month` en tienne compte — sans cette derniere
assertion, on prouverait qu'on a rempli une table sans prouver qu'elle sert
a quelque chose."""

from __future__ import annotations

import datetime as dt

import pytest
from django.core.management import CommandError, call_command

from apps.core.management.commands.load_mg_holidays import (
    available_years,
    holidays_for_year,
)
from apps.core.models.calendar import Holiday
from apps.core.models.tenant import Tenant
from apps.core.services.calendar import business_days_in_month, is_business_day
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db

YEAR = 2026


@pytest.fixture
def holiday_tenant() -> Tenant:
    return Tenant.objects.create(code="FOR-HOL", name="Forecast Holidays Tenant")


def test_the_command_populates_the_reference_table(holiday_tenant: Tenant) -> None:
    call_command("load_mg_holidays", f"--year={YEAR}", f"--tenant={holiday_tenant.code}")

    with use_tenant(holiday_tenant.id):
        loaded = set(Holiday.objects.values_list("date", flat=True))

    assert loaded, "Aucun jour ferie charge."
    assert dt.date(YEAR, 1, 1) in loaded
    assert dt.date(YEAR, 6, 26) in loaded
    assert dt.date(YEAR, 12, 25) in loaded


def test_the_command_is_idempotent(holiday_tenant: Tenant) -> None:
    call_command("load_mg_holidays", f"--year={YEAR}", f"--tenant={holiday_tenant.code}")
    with use_tenant(holiday_tenant.id):
        first = Holiday.objects.count()

    call_command("load_mg_holidays", f"--year={YEAR}", f"--tenant={holiday_tenant.code}")
    with use_tenant(holiday_tenant.id):
        assert Holiday.objects.count() == first


def test_a_manual_correction_is_never_overwritten(holiday_tenant: Tenant) -> None:
    """L'exploitant doit rester maitre de son calendrier : le calendrier legal
    ajoute des journees chomees ponctuelles qui ne figureront jamais dans la
    fixture, et une relance de la commande ne doit pas defaire sa correction."""
    with use_tenant(holiday_tenant.id):
        Holiday.objects.create(
            tenant=holiday_tenant, date=dt.date(YEAR, 1, 1), name="Libelle corrige a la main"
        )

    call_command("load_mg_holidays", f"--year={YEAR}", f"--tenant={holiday_tenant.code}")

    with use_tenant(holiday_tenant.id):
        kept = Holiday.objects.get(date=dt.date(YEAR, 1, 1))
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


# ---------------------------------------------------------------------------
# Les quatre fetes qui manquaient, et le jour d'election qui ne peut pas
# figurer dans une livraison
# ---------------------------------------------------------------------------
#
# Le calendrier livre ne portait que trois fetes mobiles — Lundi de Paques,
# Ascension, Lundi de Pentecote. Quatre manquaient : Paques, la Pentecote, et
# les deux Aid. Ce n'est pas une omission esthetique : la majoration d'un
# ferie travaille est de 100 %, et une date absente du calendrier est une
# journee payee au tarif ordinaire.


def test_the_calendar_carries_all_seven_movable_feasts() -> None:
    """Les sept fetes mobiles de la liste du commanditaire, pour CHAQUE annee
    couverte. Le test lit les libelles plutot que des dates en dur — une
    date en dur dans un test serait exactement ce que FOR-5 interdit dans le
    code."""
    for annee in available_years():
        libelles = {nom for _date, nom in holidays_for_year(annee)}
        for attendu in (
            "Paques",
            "Lundi de Paques",
            "Ascension",
            "Pentecote",
            "Lundi de Pentecote",
        ):
            assert any(nom == attendu for nom in libelles), (
                f"{annee} : « {attendu} » absent du calendrier. Les sept fetes mobiles "
                "sont attendues chaque annee."
            )
        assert any("Aid" in nom for nom in libelles), (
            f"{annee} : aucun Aid. Les deux Aid suivent le calendrier lunaire et "
            "peuvent tomber a une ou deux occurrences par annee gregorienne, mais "
            "jamais zero sur la fenetre couverte."
        )


def test_every_aid_says_it_is_an_estimate() -> None:
    """La date opposable d'un Aid est fixee par decret apres observation
    lunaire. Le calendrier n'en porte qu'une estimation, mesuree a +/- 1 jour
    — le libelle doit le dire, sinon un exploitant la prendra pour acquise et
    ne la corrigera jamais."""
    for annee in available_years():
        for _date, nom in holidays_for_year(annee):
            if "Aid" in nom:
                assert "estime" in nom.lower(), (
                    f"« {nom} » ne signale pas qu'il s'agit d'une estimation."
                )


def test_easter_and_pentecost_are_sundays_and_change_no_business_day_count(
    holiday_tenant: Tenant,
) -> None:
    """**Pourquoi les ajouter change quelque chose alors qu'elles ne changent
    rien.**

    Paques et la Pentecote tombent toujours un dimanche, deja exclu par la
    regle du week-end : le nombre de jours ouvres est identique avant et
    apres. Elles ne sont pas inutiles pour autant — un dimanche ferie se
    paie 2,00 et un dimanche ordinaire 1,40, et sans ces lignes rien ne
    permettrait de les distinguer.

    Ce test fige les deux moities : le dimanche reste non ouvre, ET la ligne
    existe pour que la paie puisse la voir."""
    paques_2026 = dt.date(2026, 4, 5)
    assert paques_2026.isoweekday() == 7

    with use_tenant(holiday_tenant.id):
        avril_avant = business_days_in_month(holiday_tenant, 2026, 4)

    call_command("load_mg_holidays", "--year=2026", f"--tenant={holiday_tenant.code}")

    with use_tenant(holiday_tenant.id):
        avril_apres = business_days_in_month(holiday_tenant, 2026, 4)
        assert Holiday.objects.filter(date=paques_2026).exists(), (
            "Paques n'est pas enregistre : la paie ne pourra pas distinguer ce "
            "dimanche d'un dimanche ordinaire."
        )
    # Le lundi de Paques (6 avril, un lundi) retire UN jour ouvre ; Paques
    # elle-meme n'en retire aucun puisqu'elle tombe un dimanche.
    assert avril_apres == avril_avant - 1


def test_the_command_reports_a_collision_distinctly_from_a_replay(holiday_tenant: Tenant) -> None:
    """Une collision etait fondue dans le compteur « deja present », donc
    indiscernable d'une seconde execution. La docstring affirmait pourtant
    que « la commande le signale ». Elle ne le signalait pas."""
    from io import StringIO

    sortie = StringIO()
    call_command(
        "load_mg_holidays", "--year=2027", f"--tenant={holiday_tenant.code}", stdout=sortie
    )
    texte = sortie.getvalue()
    assert "2027-03-29" in texte, (
        "La collision du 29 mars 2027 (commemoration de 1947 et lundi de Paques) "
        f"n'est pas signalee :\n{texte}"
    )
    assert "meme jour" in texte


def test_an_election_day_can_be_declared_and_withdrawn(holiday_tenant: Tenant) -> None:
    """Ce qu'aucune livraison logicielle ne peut connaitre.

    Une date d'election est fixee quelques semaines a l'avance. Avant ce lot,
    `Holiday` n'avait qu'un seul ecrivain dans tout le depot — la commande de
    chargement — et deux docstrings promettaient un ecran de saisie qui
    n'existait pas."""
    from apps.core.services.calendar import declare_holiday, remove_holiday

    scrutin = dt.date(2026, 11, 12)
    with use_tenant(holiday_tenant.id):
        assert is_business_day(holiday_tenant, scrutin)

        declare_holiday(holiday_tenant, date=scrutin, name="Journee electorale")
        assert not is_business_day(holiday_tenant, scrutin)

        # Idempotente, et corrige le libelle plutot que de lever : un
        # exploitant qui rectifie une orthographe ne doit pas supprimer.
        declare_holiday(holiday_tenant, date=scrutin, name="Second tour")
        assert Holiday.objects.get(date=scrutin).name == "Second tour"
        assert Holiday.objects.filter(date=scrutin).count() == 1

        # Scrutin reporte : sans retrait, la journee resterait majoree a 100 %.
        assert remove_holiday(holiday_tenant, date=scrutin) is True
        assert is_business_day(holiday_tenant, scrutin)
        assert remove_holiday(holiday_tenant, date=scrutin) is False


def test_a_holiday_must_carry_a_name(holiday_tenant: Tenant) -> None:
    """Une date sans nom serait indechiffrable six mois plus tard, quand il
    faudra dire pourquoi la paie a double ce jour-la."""
    from django.core.exceptions import ValidationError

    from apps.core.services.calendar import declare_holiday

    with use_tenant(holiday_tenant.id), pytest.raises(ValidationError):
        declare_holiday(holiday_tenant, date=dt.date(2026, 11, 12), name="   ")
