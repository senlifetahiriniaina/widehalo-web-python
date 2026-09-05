"""L3 — le taux de TVA sous verrou réglementaire, et la période close
défendue en base.

Deux invariants comptables qui n'en étaient pas encore.

**1. `tva.taux_normal` n'était semé par rien.** Le code était référencé à
quatre endroits du dépôt et créé nulle part : ni migration, ni commande, ni
service. Conséquence vérifiée sur une base de démonstration entièrement
amorcée — `apps.simulation.services.baseline.build_baseline` levait une
`ValidationError` et **le module Simulation ne pouvait construire aucun
socle, sur aucune instance**. Le code était juste ; rien ne l'amorçait.

**2. Le refus d'écriture en période close vivait dans le seul service.**
`post_move` le vérifiait, donc toute écriture n'empruntant pas ce service
publiait sans obstacle. Le dépôt avait pourtant déjà tranché deux fois dans
l'autre sens : équilibre débit/crédit et immuabilité des écritures publiées
sont en base depuis la Phase 1. La période close était le seul des trois
invariants resté en Python.

Le test qui compte pour le second point est celui de **contournement** :
écrire directement par l'ORM, hors du service, et voir la base refuser.
Sans lui, on prouverait seulement que le service fait ce qu'il dit — ce
qu'on savait déjà.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.db import transaction

from apps.accounting.models import AccMove, AccPeriod, AccTax
from apps.accounting.services.vat_reference import (
    VAT_STANDARD_RATE_CODE,
    diverging_sale_taxes,
    resolve_reference_vat_rate,
)
from apps.accounting.tests.factories import (
    AccJournalFactory,
    AccMoveFactory,
    AccPeriodFactory,
    AccTaxFactory,
)
from apps.core.models.regulatory import RegulatoryParameter
from apps.core.models.tenant import Tenant
from apps.core.services.regulatory_governance import ACTIVE_CALCULATION_PARAMETER_CODES
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def acc_tenant():
    tenant = Tenant.objects.create(code="ACC-L3", name="Accounting L3 Tenant")
    with use_tenant(tenant.id):
        yield tenant


# ---------------------------------------------------------------------------
# 1. Le taux de TVA de référence
# ---------------------------------------------------------------------------


def test_the_vat_reference_rate_is_actually_seeded(acc_tenant) -> None:
    """Le défaut d'origine, en une assertion : le paramètre existe.

    Il était référencé par `simulation`, par deux docstrings et par un
    commentaire de modèle — et créé par personne."""
    assert RegulatoryParameter.objects.filter(code=VAT_STANDARD_RATE_CODE).exists()


def test_the_reference_rate_resolves_at_the_document_date(acc_tenant) -> None:
    """`at_date` est la date du DOCUMENT, jamais « aujourd'hui » : un avoir
    émis en mars sur une facture de janvier doit retrouver le taux de
    janvier. C'est l'exigence D9."""
    resolved = resolve_reference_vat_rate(acc_tenant, at_date=dt.date(2026, 6, 30))
    assert resolved is not None
    rate, version = resolved
    assert rate == Decimal("20.00")
    assert version >= 1


def test_a_date_before_the_effective_date_resolves_to_nothing(acc_tenant) -> None:
    """Renvoie `None`, jamais une exception : un tenant peut légitimement
    n'avoir aucun référentiel de TVA (régime synthétique), et un appelant de
    lecture ne doit pas avoir à s'en protéger."""
    assert resolve_reference_vat_rate(acc_tenant, at_date=dt.date(2020, 1, 1)) is None


def test_the_vat_rate_is_under_the_oecfm_deployment_lock() -> None:
    """C'était le seul taux légal du produit à y échapper, alors que les dix
    paramètres de paie y sont soumis depuis la Phase 3."""
    assert VAT_STANDARD_RATE_CODE in ACTIVE_CALCULATION_PARAMETER_CODES


def test_the_seeded_rate_is_not_pre_validated() -> None:
    """Cahier §4 : « aucune hypothèse réglementaire ne peut être levée par
    défaut au motif que le développement doit avancer ». Semer ce paramètre
    déjà validé OECFM contournerait le verrou que ce lot vient d'étendre."""
    param = RegulatoryParameter.objects.get(code=VAT_STANDARD_RATE_CODE, tenant__isnull=True)
    assert param.statut_validation == RegulatoryParameter.STATUS_NON_VALIDE


def test_a_sale_tax_diverging_from_the_law_is_reported(acc_tenant) -> None:
    """Un taux saisi à 18 % quand la loi dit 20 % est aujourd'hui
    indétectable autrement qu'à l'œil."""
    AccTaxFactory(tenant=acc_tenant, type=AccTax.TYPE_SALE, code="TVA18", rate=Decimal("18.00"))
    AccTaxFactory(tenant=acc_tenant, type=AccTax.TYPE_SALE, code="TVA20", rate=Decimal("20.00"))

    rows = diverging_sale_taxes(acc_tenant, at_date=dt.date(2026, 6, 30))

    assert [row["code"] for row in rows] == ["TVA18"]
    assert rows[0]["reference_rate"] == Decimal("20.00")


def test_divergence_is_reported_and_never_blocking(acc_tenant) -> None:
    """LECTURE PURE, à dessein : un écart peut être parfaitement légitime
    (taux réduit sectoriel, exonération), et refuser l'enregistrement
    casserait des cas réels. Ce que l'exploitant doit pouvoir faire, c'est
    le VOIR."""
    tax = AccTaxFactory(
        tenant=acc_tenant, type=AccTax.TYPE_SALE, code="TVA-RED", rate=Decimal("5.00")
    )
    assert diverging_sale_taxes(acc_tenant, at_date=dt.date(2026, 6, 30))
    tax.refresh_from_db()
    assert tax.rate == Decimal("5.00")  # jamais corrigé d'office


# ---------------------------------------------------------------------------
# 2. La période close, défendue en base
# ---------------------------------------------------------------------------


def _closed_period(tenant):
    period = AccPeriodFactory(
        tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 1, 31)
    )
    period.state = AccPeriod.STATE_CLOSED
    period.save(update_fields=["state"])
    return period


def test_the_database_refuses_a_posted_move_inserted_in_a_closed_period(acc_tenant) -> None:
    """LE test du lot : on écrit directement par l'ORM, hors du service, et
    la base refuse. Sans ce contournement, on ne prouverait que ce qu'on
    savait déjà — que `post_move` fait ce qu'il annonce."""
    period = _closed_period(acc_tenant)
    journal = AccJournalFactory(tenant=acc_tenant)

    # `pytest.raises(Exception, match=...)` : idiome deja etabli dans ce
    # depot pour les triggers plpgsql (`test_moves.py`, immuabilite des
    # ecritures publiees). La classe exacte depend du pilote — psycopg3
    # remonte un `RAISE EXCEPTION` (SQLSTATE P0001) en `ProgrammingError`,
    # pas en `IntegrityError` — et le message, lui, est stable et porte le
    # sens.
    with pytest.raises(Exception, match="periode close"), transaction.atomic():
        AccMove.objects.create(
            tenant=acc_tenant,
            journal=journal,
            period=period,
            date=dt.date(2026, 1, 15),
            state=AccMove.STATE_POSTED,
        )


def test_the_database_refuses_posting_an_existing_draft_in_a_closed_period(acc_tenant) -> None:
    """L'autre voie de contournement : créer en brouillon, puis basculer
    l'état par un `update()` qui ne passe par aucun service."""
    period = _closed_period(acc_tenant)
    move = AccMoveFactory(tenant=acc_tenant, period=period, state=AccMove.STATE_DRAFT)

    with pytest.raises(Exception, match="periode close"), transaction.atomic():
        AccMove.objects.filter(id=move.id).update(state=AccMove.STATE_POSTED)


def test_a_draft_in_a_closed_period_remains_allowed(acc_tenant) -> None:
    """Portée volontairement étroite : préparer une écriture dans une
    période close est légitime — on la publiera après réouverture, ou on la
    repositionnera. Interdire le brouillon ferait du trigger une gêne."""
    period = _closed_period(acc_tenant)
    move = AccMoveFactory(tenant=acc_tenant, period=period, state=AccMove.STATE_DRAFT)
    assert move.pk is not None


def test_closing_a_period_that_already_holds_posted_moves_remains_possible(acc_tenant) -> None:
    """Sans quoi aucune clôture ne serait possible : une période se ferme
    précisément parce qu'elle contient des écritures publiées."""
    period = AccPeriodFactory(
        tenant=acc_tenant, date_start=dt.date(2026, 2, 1), date_end=dt.date(2026, 2, 28)
    )
    AccMoveFactory(tenant=acc_tenant, period=period, state=AccMove.STATE_POSTED)

    period.state = AccPeriod.STATE_CLOSED
    period.save(update_fields=["state"])

    period.refresh_from_db()
    assert period.state == AccPeriod.STATE_CLOSED


def test_posting_in_an_open_period_is_untouched(acc_tenant) -> None:
    """Le trigger ne doit gêner aucun usage normal."""
    period = AccPeriodFactory(
        tenant=acc_tenant, date_start=dt.date(2026, 3, 1), date_end=dt.date(2026, 3, 31)
    )
    move = AccMoveFactory(tenant=acc_tenant, period=period, state=AccMove.STATE_POSTED)
    assert move.state == AccMove.STATE_POSTED
