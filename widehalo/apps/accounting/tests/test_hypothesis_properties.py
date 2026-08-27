"""Tests de proprietes (couche 13 du CDC, §8) : RG-ACC-1 (partie double)
verifiee sur des lignes generees arbitrairement par Hypothesis plutot que sur
les seuls cas fixes de `test_moves.py`. 1000 exemples par test, comme l'exige
le critere de sortie de cette couche.

Chaque exemple cree son propre tenant/exercice/journal/comptes : aucune
fixture pytest partagee entre exemples (Hypothesis rejoue la fonction
decoree plusieurs centaines de fois par test, et une fixture a portee
fonction declencherait le health check `function_scoped_fixture`)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccMove, AccPeriod
from apps.accounting.services.moves import add_line, create_draft_move, post_move
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db

# Amplitude compatible avec DecimalField(max_digits=18, decimal_places=4) :
# on reste tres loin du plafond (10**14) pour eviter tout depassement lors
# de la sommation de plusieurs lignes, et on borne les montants a des
# valeurs strictement positives (un montant nul des deux cotes serait
# trivialement equilibre et n'exercerait pas grand-chose).
_AMOUNT = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("1000000"),
    places=4,
    allow_nan=False,
    allow_infinity=False,
)


def _ledger() -> tuple[Tenant, AccPeriod, AccJournal, list[AccAccount]]:
    """Cree un jeu de comptes minimal, unique par exemple Hypothesis (le code
    tenant doit etre unique en base) — un `uuid4` garantit l'unicite sur les
    1000 exemples sans dependre d'un compteur externe."""
    tenant = Tenant.objects.create(
        code=f"HYP-ACC-{uuid.uuid4().hex[:12]}", name="Hypothesis Accounting Tenant"
    )
    with use_tenant(tenant.id):
        fiscal_year = AccFiscalYear.objects.create(
            tenant=tenant,
            code="FY2026",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 12, 31),
        )
        period = AccPeriod.objects.create(
            tenant=tenant,
            fiscal_year=fiscal_year,
            code="2026-01",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 1, 31),
        )
        journal = AccJournal.objects.create(
            tenant=tenant,
            code="OD",
            name="Operations diverses",
            type=AccJournal.TYPE_MISC,
            sequence_prefix="OD",
        )
        # Deux comptes suffisent a repartir un nombre arbitraire de lignes
        # debit/credit ; on alterne dessus.
        receivable = AccAccount.objects.create(
            tenant=tenant,
            code="411",
            name="Clients",
            account_class=4,
            type=AccAccount.TYPE_RECEIVABLE,
        )
        income = AccAccount.objects.create(
            tenant=tenant, code="701", name="Ventes", account_class=7, type=AccAccount.TYPE_INCOME
        )
    return tenant, period, journal, [receivable, income]


@pytest.mark.slow
@given(debit_amounts=st.lists(_AMOUNT, min_size=1, max_size=6))
@settings(
    max_examples=1000,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
def test_move_balanced_by_construction_always_posts(debit_amounts: list[Decimal]) -> None:
    """RG-ACC-1 : pour un nombre arbitraire de lignes debit dont la somme
    totale est portee par une unique ligne credit (egalite exacte garantie
    par construction, independamment de tout arrondi de repartition),
    `post_move()` doit toujours reussir et les totaux publies doivent
    correspondre exactement au total des lignes debit."""
    tenant, period, journal, (receivable, income) = _ledger()
    with use_tenant(tenant.id):
        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 1, 15)
        )
        total = sum(debit_amounts, Decimal(0))
        for amount in debit_amounts:
            add_line(move, account=receivable, label="Debit", debit=amount)
        # Une seule ligne credit porte tout le total : egalite exacte
        # garantie par construction, sans dependre d'un arrondi de
        # repartition entre plusieurs lignes credit.
        add_line(move, account=income, label="Credit", credit=total)

        posted = post_move(move)

        assert posted.state == AccMove.STATE_POSTED
        assert posted.total_debit == posted.total_credit == total


@pytest.mark.slow
@given(debit_amounts=st.lists(_AMOUNT, min_size=1, max_size=6), perturbation=_AMOUNT)
@settings(
    max_examples=1000,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
def test_move_unbalanced_by_construction_is_always_rejected(
    debit_amounts: list[Decimal], perturbation: Decimal
) -> None:
    """RG-ACC-1 : la meme construction que ci-dessus, mais avec le total
    credit delibrement perturbe (le total credit posee est le total debit
    plus un montant strictement positif), doit toujours etre refusee par
    `post_move()` avec une ValidationError, quelle que soit l'amplitude des
    montants generes."""
    tenant, period, journal, (receivable, income) = _ledger()
    with use_tenant(tenant.id):
        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 1, 15)
        )
        total = sum(debit_amounts, Decimal(0))
        for amount in debit_amounts:
            add_line(move, account=receivable, label="Debit", debit=amount)
        # Perturbation strictement positive : le credit ne peut jamais
        # coïncider avec le debit par construction.
        add_line(move, account=income, label="Credit", credit=total + perturbation)

        with pytest.raises(ValidationError):
            post_move(move)
