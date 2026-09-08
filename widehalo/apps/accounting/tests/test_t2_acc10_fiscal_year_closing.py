"""T2 (ACC-10) — « Un exercice clos refuse toute écriture, y compris par
appel direct de l'API et y compris pour un utilisateur administrateur. »

**Ce que la mesure a trouvé, et ce n'est pas ce que l'audit disait.**
L'audit classait ACC-10 🟡 avec pour réserve « le refus n'est pas garanti
par la base ». Cette réserve était levée depuis L3, qui a mis le refus en
base pour une PÉRIODE close. Mais le critère parle d'EXERCICE, et là :
`AccFiscalYear.state` n'était **écrit par personne**. Aucun service de
clôture, aucun endpoint, aucun bouton. L'écran de configuration affichait
même une colonne « Statut » qui disait « Ouvert » à perpétuité.

Un exercice ne pouvait donc pas être clos, et le verrou de période ne s'y
substituait pas : rien n'empêchait de créer une période neuve — donc
ouverte — dans un exercice « clos » et d'y publier.

**Les trois tests qui portent le critère sont ceux qui contournent le
service.** Un test qui se contenterait d'appeler `post_move` prouverait que
la garde applicative fonctionne, ce que personne ne conteste. Le critère
dit « par appel direct de l'API » et « pour un administrateur » : il faut
donc écrire en base SANS passer par le service, et vérifier que la base
elle-même refuse.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounting.models import AccFiscalYear, AccMove, AccPeriod
from apps.accounting.services.fiscal_years import (
    close_fiscal_year,
    closing_blockers,
    reopen_fiscal_year,
)
from apps.accounting.tests.factories import (
    AccAccountFactory,
    AccJournalFactory,
    AccMoveFactory,
    AccPeriodFactory,
)
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db

#: `pytest.raises(Exception, match=...)` : idiome deja etabli dans ce depot
#: pour les declencheurs plpgsql (`test_moves.py`, `test_l3_regulatory_and_
#: closed_period.py`). La classe exacte depend du pilote — psycopg 3 remonte
#: un `RAISE EXCEPTION` (SQLSTATE P0001) en `ProgrammingError`, pas en
#: `IntegrityError` — et c'est le MESSAGE qui porte le sens, lui stable.
#: Mesure faite ici : le premier jet de ce fichier attendait
#: `InternalError` et rougissait alors que les declencheurs faisaient
#: exactement leur travail.
MESSAGE_EXERCICE_CLOS = "exercice clos"


@pytest.fixture
def societe():
    return Tenant.objects.create(code="ACC10", name="Clôture SARL")


@pytest.fixture
def administrateur(societe):
    with use_tenant(societe.id):
        return User.objects.create_superuser(
            email="acc10-admin@example.com", password="Str0ngPassw0rd!23"
        )


def _exercice(societe, *, code="EX-2026", avec_periode=True):
    annee = AccFiscalYear.objects.create(
        tenant=societe,
        code=code,
        date_start=dt.date(2026, 1, 1),
        date_end=dt.date(2026, 12, 31),
    )
    if avec_periode:
        AccPeriodFactory(
            tenant=societe,
            fiscal_year=annee,
            code=f"{code}-01",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 1, 31),
        )
    return annee


def test_closing_a_year_closes_every_one_of_its_periods(societe, administrateur) -> None:
    """Les deux écritures dans la MÊME transaction.

    Un exercice marqué clos dont les périodes seraient restées ouvertes
    serait le pire des deux états : l'écran dirait « clos » et la base
    accepterait les écritures."""
    with use_tenant(societe.id):
        annee = _exercice(societe)
        close_fiscal_year(annee, by=administrateur)

        annee.refresh_from_db()
        assert annee.state == AccFiscalYear.STATE_CLOSED
        assert not annee.periods.filter(state=AccPeriod.STATE_OPEN).exists()


def test_the_database_refuses_a_posted_move_in_a_closed_year(societe, administrateur) -> None:
    """LE critère, et il ne s'obtient que hors du service.

    L'écriture est insérée directement à l'état `posted` — exactement ce
    que ferait un `objects.create(state="posted")`, un import, une commande
    de reprise ou un accès `psql`. Aucune garde applicative n'est
    empruntée : ce qui refuse ici est le déclencheur de base."""
    with use_tenant(societe.id):
        annee = _exercice(societe)
        periode = annee.periods.first()
        journal = AccJournalFactory(tenant=societe)
        AccAccountFactory(tenant=societe)
        close_fiscal_year(annee, by=administrateur)

        with (
            pytest.raises(Exception, match=MESSAGE_EXERCICE_CLOS),
            transaction.atomic(),
        ):
            AccMove.objects.create(
                tenant=societe,
                journal=journal,
                period=periode,
                date=dt.date(2026, 1, 15),
                state=AccMove.STATE_POSTED,
            )


def test_a_superuser_is_refused_exactly_like_anyone_else(societe, administrateur) -> None:
    """« y compris pour un utilisateur administrateur ».

    Le déclencheur ne connaît pas les rôles — c'est précisément ce qui rend
    le critère tenable. Ce test le dit explicitement plutôt que de le
    laisser déduire : un lecteur qui cherche la garantie « administrateur »
    doit la trouver écrite."""
    assert administrateur.is_superuser
    with use_tenant(societe.id):
        annee = _exercice(societe, code="EX-ADMIN")
        periode = annee.periods.first()
        journal = AccJournalFactory(tenant=societe)
        close_fiscal_year(annee, by=administrateur)

        with (
            pytest.raises(Exception, match=MESSAGE_EXERCICE_CLOS),
            transaction.atomic(),
        ):
            AccMove.objects.create(
                tenant=societe,
                journal=journal,
                period=periode,
                date=dt.date(2026, 2, 15),
                state=AccMove.STATE_POSTED,
            )


def test_a_new_open_period_cannot_be_created_in_a_closed_year(societe, administrateur) -> None:
    """Le trou que le verrou de PÉRIODE laissait ouvert.

    Rien n'empêchait de créer une treizième période, ouverte par défaut,
    dans un exercice clos — et d'y publier. Une clôture annuelle qu'on
    rouvre en ajoutant une période n'est pas une clôture."""
    with use_tenant(societe.id):
        annee = _exercice(societe, code="EX-13")
        close_fiscal_year(annee, by=administrateur)

        with (
            pytest.raises(Exception, match=MESSAGE_EXERCICE_CLOS),
            transaction.atomic(),
        ):
            AccPeriod.objects.create(
                tenant=societe,
                fiscal_year=annee,
                code="EX-13-13",
                date_start=dt.date(2026, 12, 1),
                date_end=dt.date(2026, 12, 31),
            )


def test_a_draft_move_is_still_allowed_in_a_closed_year(societe, administrateur) -> None:
    """La portée est délibérément étroite, comme celle de la migration
    `0031` : préparer une écriture reste légitime — on la publiera après
    réouverture, ou on la repositionnera. Sans ce test, quelqu'un
    élargirait le verrou aux brouillons en croyant bien faire."""
    with use_tenant(societe.id):
        annee = _exercice(societe, code="EX-BROUILLON")
        periode = annee.periods.first()
        journal = AccJournalFactory(tenant=societe)
        close_fiscal_year(annee, by=administrateur)

        brouillon = AccMove.objects.create(
            tenant=societe,
            journal=journal,
            period=periode,
            date=dt.date(2026, 3, 15),
            state=AccMove.STATE_DRAFT,
        )
        assert brouillon.pk is not None


def test_closing_refuses_to_strand_draft_moves(societe, administrateur) -> None:
    """Un brouillon laissé dans un exercice clos ne pourrait plus jamais
    être publié, et rien ne dirait pourquoi. La clôture le refuse en le
    NOMMANT, plutôt que de créer un dossier suspendu silencieux."""
    with use_tenant(societe.id):
        annee = _exercice(societe, code="EX-SUSPENS")
        periode = annee.periods.first()
        AccMoveFactory(tenant=societe, period=periode, state=AccMove.STATE_DRAFT)

        assert closing_blockers(annee)
        with pytest.raises(ValidationError) as refus:
            close_fiscal_year(annee, by=administrateur)
    assert "brouillon" in " ".join(refus.value.messages)


def test_closing_a_year_without_periods_is_refused(societe, administrateur) -> None:
    """Clore un exercice sans période ne fermerait RIEN : le déclencheur
    regarde la période de l'écriture, et une période créée après coup
    rouvrirait la porte."""
    with use_tenant(societe.id):
        annee = _exercice(societe, code="EX-VIDE", avec_periode=False)
        with pytest.raises(ValidationError):
            close_fiscal_year(annee, by=administrateur)


def test_reopening_restores_the_ability_to_post(societe, administrateur) -> None:
    """La réouverture n'est pas un contournement du critère : un exercice
    rouvert n'est plus clos. Sans elle, une clôture par erreur ne se
    répare qu'en SQL."""
    with use_tenant(societe.id):
        annee = _exercice(societe, code="EX-ROUVERT")
        periode = annee.periods.first()
        journal = AccJournalFactory(tenant=societe)
        close_fiscal_year(annee, by=administrateur)
        reopen_fiscal_year(
            annee, by=administrateur, motif="Écriture d'ajustement demandée par l'expert-comptable"
        )

        annee.refresh_from_db()
        assert annee.state == AccFiscalYear.STATE_OPEN
        periode.refresh_from_db()
        assert periode.state == AccPeriod.STATE_OPEN

        publiee = AccMove.objects.create(
            tenant=societe,
            journal=journal,
            period=periode,
            date=dt.date(2026, 4, 15),
            state=AccMove.STATE_POSTED,
        )
        assert publiee.pk is not None


def test_reopening_without_a_written_reason_is_refused(societe, administrateur) -> None:
    """Une réouverture sans motif écrit est exactement ce qu'un contrôle
    fiscal demandera d'expliquer."""
    with use_tenant(societe.id):
        annee = _exercice(societe, code="EX-SANS-MOTIF")
        close_fiscal_year(annee, by=administrateur)
        with pytest.raises(ValidationError):
            reopen_fiscal_year(annee, by=administrateur, motif="   ")


def test_reopening_an_older_year_while_a_later_one_is_closed_is_refused(
    societe, administrateur
) -> None:
    """Rouvrir 2024 en laissant 2025 clos produirait des à-nouveaux
    incohérents, et l'incohérence ne se verrait qu'à la liasse suivante."""
    with use_tenant(societe.id):
        ancien = AccFiscalYear.objects.create(
            tenant=societe,
            code="EX-2024",
            date_start=dt.date(2024, 1, 1),
            date_end=dt.date(2024, 12, 31),
        )
        AccPeriodFactory(
            tenant=societe,
            fiscal_year=ancien,
            code="2024-01",
            date_start=dt.date(2024, 1, 1),
            date_end=dt.date(2024, 1, 31),
        )
        recent = _exercice(societe, code="EX-2026")
        close_fiscal_year(ancien, by=administrateur)
        close_fiscal_year(recent, by=administrateur)

        with pytest.raises(ValidationError) as refus:
            reopen_fiscal_year(ancien, by=administrateur, motif="Reprise d'écriture")
    assert "EX-2026" in " ".join(refus.value.messages)
