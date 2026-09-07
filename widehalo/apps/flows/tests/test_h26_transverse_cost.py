"""H26 — le compteur transverse, et pourquoi il ne renvoie pas un nombre.

Décision structurante n°6 du cahier : « tout échange porte un coût imputé
et un plafond opposable ». Le plafond a besoin d'un total.

Un total nu serait un piège, et c'est tout l'objet de H26 : une somme sur
une période à cheval sur une bascule d'unité est **exacte à l'ariary** et
pourtant **incomparable** à la période précédente — ce ne sont pas les
mêmes objets qu'on compte. Un nombre nu laisserait cette incomparabilité
invisible, et une jauge de plafond afficherait une variation qui ne veut
rien dire.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.cost_units import COST_UNIT_CONVERSATION, COST_UNIT_MESSAGE
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.flows.models import FlwExchange
from apps.flows.services.cost import compare_periods, cost_total
from apps.flows.services.exchange import prepare_exchange
from apps.flows.tests.factories import FlwLinkFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup():
    tenant = Tenant.objects.create(code="H26-FLX", name="Coût flux SARL")
    with use_tenant(tenant.id):
        link = FlwLinkFactory(tenant=tenant)
    return tenant, link


def _priced(tenant, link, montant, unite):
    exchange = prepare_exchange(tenant, link, operation="OP1")
    exchange.cost_ariary = Decimal(montant)
    exchange.cost_unit = unite
    exchange.save(update_fields=["cost_ariary", "cost_unit"])
    return exchange


def test_a_homogeneous_period_totals_and_says_so(setup) -> None:
    tenant, link = setup
    with use_tenant(tenant.id):
        _priced(tenant, link, "50", COST_UNIT_MESSAGE)
        _priced(tenant, link, "70", COST_UNIT_MESSAGE)
        total = cost_total(
            tenant,
            since=timezone.now() - dt.timedelta(days=1),
            until=timezone.now() + dt.timedelta(days=1),
        )

    assert total.amount == Decimal("120")
    assert total.units == {COST_UNIT_MESSAGE}
    assert total.is_homogeneous
    assert total.is_fully_priced


def test_a_period_spanning_a_switch_is_exact_and_says_it_is_not_comparable(setup) -> None:
    """Le cœur de H26. La somme reste juste — on ne perd pas un ariary —
    mais la période porte deux unités, et c'est ce que le total doit
    dire."""
    tenant, link = setup
    with use_tenant(tenant.id):
        _priced(tenant, link, "50", COST_UNIT_MESSAGE)
        _priced(tenant, link, "300", COST_UNIT_CONVERSATION)
        total = cost_total(
            tenant,
            since=timezone.now() - dt.timedelta(days=1),
            until=timezone.now() + dt.timedelta(days=1),
        )

    assert total.amount == Decimal("350"), "La somme doit rester exacte à l'ariary."
    assert not total.is_homogeneous, (
        "Une période à cheval sur une bascule se déclare homogène : la comparer à la "
        "période précédente reviendrait à comparer des conversations à des messages, "
        "sans que rien ne le signale."
    )


def test_an_unpriced_exchange_is_counted_as_such_not_as_zero(setup) -> None:
    """« Coût non encore imputé » et « coût nul » sont deux choses
    différentes. Un plafond évalué sur un total incomplet laisse passer des
    envois que le coût réel aurait bloqués."""
    tenant, link = setup
    with use_tenant(tenant.id):
        _priced(tenant, link, "50", COST_UNIT_MESSAGE)
        prepare_exchange(tenant, link, operation="OP2")  # sans coût
        total = cost_total(
            tenant,
            since=timezone.now() - dt.timedelta(days=1),
            until=timezone.now() + dt.timedelta(days=1),
        )

    assert total.amount == Decimal("50")
    assert total.priced_rows == 1
    assert total.unpriced_rows == 1
    assert not total.is_fully_priced


def test_a_free_exchange_is_priced_and_a_pending_one_is_not(setup) -> None:
    """La distinction qui compte, vérifiée là où elle se lit : zéro est un
    montant connu, `None` ne l'est pas. Une soumission fiscale gratuite ne
    doit pas rendre la période « incomplète »."""
    tenant, link = setup
    with use_tenant(tenant.id):
        _priced(tenant, link, "0", COST_UNIT_MESSAGE)
        total = cost_total(
            tenant,
            since=timezone.now() - dt.timedelta(days=1),
            until=timezone.now() + dt.timedelta(days=1),
        )

    assert total.amount == Decimal(0)
    assert total.is_fully_priced, "Un échange gratuit est tarifé, pas en attente de tarif."
    assert total.units == {COST_UNIT_MESSAGE}


def test_comparing_two_periods_of_different_units_is_refused_with_a_reason(setup) -> None:
    """Un motif plutôt qu'un booléen : « comparaison impossible » sans
    raison est une impasse pour l'utilisateur, qui ne peut ni corriger ni
    comprendre."""
    tenant, link = setup
    with use_tenant(tenant.id):
        _priced(tenant, link, "50", COST_UNIT_MESSAGE)
        courante = cost_total(
            tenant,
            since=timezone.now() - dt.timedelta(hours=1),
            until=timezone.now() + dt.timedelta(days=1),
        )
    precedente = type(courante)(amount=Decimal("300"), units=frozenset({COST_UNIT_CONVERSATION}))

    motif = compare_periods(courante, precedente)
    assert motif != ""
    assert "unité" in motif


def test_two_homogeneous_periods_compare_without_objection(setup) -> None:
    """Le cas nominal, et il ne mérite pas d'objet : chaîne vide."""
    tenant, link = setup
    with use_tenant(tenant.id):
        _priced(tenant, link, "50", COST_UNIT_MESSAGE)
        courante = cost_total(
            tenant,
            since=timezone.now() - dt.timedelta(hours=1),
            until=timezone.now() + dt.timedelta(days=1),
        )
    precedente = type(courante)(amount=Decimal("40"), units=frozenset({COST_UNIT_MESSAGE}))
    assert compare_periods(courante, precedente) == ""


def test_the_total_is_scoped_to_the_period_and_the_tenant(setup) -> None:
    """Falsification du reste : un compteur qui ignorerait ses bornes
    satisferait tous les tests ci-dessus."""
    tenant, link = setup
    with use_tenant(tenant.id):
        ancien = _priced(tenant, link, "999", COST_UNIT_MESSAGE)
        FlwExchange.objects.filter(pk=ancien.pk).update(
            created_at=timezone.now() - dt.timedelta(days=40)
        )
        _priced(tenant, link, "50", COST_UNIT_MESSAGE)
        total = cost_total(
            tenant,
            since=timezone.now() - dt.timedelta(days=7),
            until=timezone.now() + dt.timedelta(days=1),
        )

    assert total.amount == Decimal("50"), (
        "Le total ignore ses bornes de période : un plafond mensuel compterait l'historique entier."
    )
