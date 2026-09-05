"""Construction du socle de simulation (`services.baseline.build_baseline`)
— agrégation compte de résultat (via `income_statement`) + taux de TVA de
référence (versionné) + position de trésorerie + échéances ouvertes."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccPeriod
from apps.accounting.services.moves import add_line, create_draft_move, post_move
from apps.core.models.regulatory import RegulatoryParameter
from apps.core.models.tenant import Tenant
from apps.core.tests.factories import RegulatoryParameterFactory
from apps.core.tests.utils import use_tenant
from apps.simulation.services.baseline import build_baseline, deserialize_baseline_data

pytestmark = pytest.mark.django_db


def _make_account(
    tenant: Tenant, *, code: str, name: str, account_class: int, type: str
) -> AccAccount:
    return AccAccount.objects.create(
        tenant=tenant, code=code, name=name, account_class=account_class, type=type
    )


@pytest.fixture
def ledger_tenant() -> Tenant:
    tenant = Tenant.objects.create(code="SIM-BL", name="Simulation Baseline Tenant")
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
            code="2026-09",
            date_start=dt.date(2026, 9, 1),
            date_end=dt.date(2026, 9, 30),
        )
        journal = AccJournal.objects.create(
            tenant=tenant,
            code="OD",
            name="Opérations diverses",
            type=AccJournal.TYPE_MISC,
            sequence_prefix="OD",
        )
        income = _make_account(
            tenant, code="701", name="Ventes", account_class=7, type=AccAccount.TYPE_INCOME
        )
        receivable = _make_account(
            tenant, code="411", name="Clients", account_class=4, type=AccAccount.TYPE_RECEIVABLE
        )
        achats = _make_account(
            tenant, code="601", name="Achats", account_class=6, type=AccAccount.TYPE_EXPENSE
        )
        payable = _make_account(
            tenant, code="401", name="Fournisseurs", account_class=4, type=AccAccount.TYPE_PAYABLE
        )
        personnel = _make_account(
            tenant, code="641", name="Rémunérations", account_class=6, type=AccAccount.TYPE_EXPENSE
        )
        personnel_due = _make_account(
            tenant, code="421", name="Personnel dû", account_class=4, type=AccAccount.TYPE_PAYABLE
        )
        bank = _make_account(
            tenant, code="512", name="Banque", account_class=5, type=AccAccount.TYPE_BANK
        )

        date = dt.date(2026, 9, 5)

        # Vente a credit, ouverte, echeance le 15/09.
        move = create_draft_move(tenant=tenant, journal=journal, period=period, date=date)
        add_line(
            move,
            account=receivable,
            label="Client",
            debit=Decimal(10000000),
            due_date=dt.date(2026, 9, 15),
        )
        add_line(move, account=income, label="Vente", credit=Decimal(10000000))
        post_move(move)

        # Achat a credit, ouvert, echeance le 20/09.
        move = create_draft_move(tenant=tenant, journal=journal, period=period, date=date)
        add_line(move, account=achats, label="Achat", debit=Decimal(4000000))
        add_line(
            move,
            account=payable,
            label="Fournisseur",
            credit=Decimal(4000000),
            due_date=dt.date(2026, 9, 20),
        )
        post_move(move)

        # Charges de personnel (contrepartie non recevable/payable pour ce test).
        move = create_draft_move(tenant=tenant, journal=journal, period=period, date=date)
        add_line(move, account=personnel, label="Salaires", debit=Decimal(2000000))
        add_line(move, account=personnel_due, label="Personnel dû", credit=Decimal(2000000))
        post_move(move)

        # Vente comptant : position de trésorerie de départ non nulle.
        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 9, 1)
        )
        add_line(move, account=bank, label="Vente comptant", debit=Decimal(5000000))
        add_line(move, account=income, label="Vente comptant", credit=Decimal(5000000))
        post_move(move)

        # Surcharge PROPRE AU TENANT depuis L3, et non plus une ligne
        # globale : `accounting/migrations/0030_seed_vat_reference_rate.py`
        # seme desormais `tva.taux_normal` en valeur globale a partir du
        # 2026-01-01, et deux plages globales qui se chevauchent violent la
        # contrainte d'exclusion `core_regulatory_parameter_no_overlap`.
        # Une surcharge par tenant ne chevauche rien (la contrainte inclut
        # `tenant_id`) et prevaut sur la valeur globale
        # (`services/regulatory.py::get_parameter`) — ce test continue donc
        # d'imposer SA valeur, ce qui est ce qu'il verifie.
        RegulatoryParameterFactory(
            tenant=tenant, code="tva.taux_normal", value=20, valid_from=dt.date(2025, 1, 1)
        )
    return tenant


def test_build_baseline_extracts_income_statement_lines(ledger_tenant: Tenant) -> None:
    with use_tenant(ledger_tenant.id):
        baseline = build_baseline(ledger_tenant, as_of_date=dt.date(2026, 9, 30))

    assert baseline.data["degraded"] is False
    assert Decimal(baseline.data["ca_ref"]) == Decimal("15000000")  # 10M a credit + 5M comptant
    assert Decimal(baseline.data["achats_consommes_ref"]) == Decimal("4000000")
    assert Decimal(baseline.data["charges_personnel_ref"]) == Decimal("2000000")
    assert Decimal(baseline.data["tva_taux_ref"]) == Decimal("20")
    assert baseline.regulatory_param_version == {"tva.taux_normal": 1}
    # Les echeances ouvertes (15/09, 20/09) precedent `as_of_date`
    # (30/09) : hors de la fenetre de projection [as_of_date, as_of_date +
    # horizon_days], donc absentes ici par construction — cf. le test
    # dedie `test_build_baseline_includes_open_settlement_items`
    # ci-dessous, qui verifie ce cas avec un `as_of_date` anterieur aux
    # echeances.
    assert baseline.open_items_total_count == 0


def test_build_baseline_includes_open_settlement_items(ledger_tenant: Tenant) -> None:
    with use_tenant(ledger_tenant.id):
        baseline = build_baseline(ledger_tenant, as_of_date=dt.date(2026, 9, 1))

    kinds = {(item["kind"], item["due_date"]) for item in baseline.data["open_items"]}
    assert ("receivable", "2026-09-15") in kinds
    assert ("payable", "2026-09-20") in kinds


def test_build_baseline_raises_without_a_configured_tva_parameter() -> None:
    """Depuis L3, `tva.taux_normal` est seme en valeur globale par
    `accounting/migrations/0030_seed_vat_reference_rate.py` — precisement
    parce que son absence rendait ce module inutilisable sur toute instance
    neuve. L'absence doit donc etre PROVOQUEE pour etre testee.

    Le test garde tout son sens : un exploitant peut fermer la plage de
    validite du parametre (`valid_to`) sans en ouvrir une nouvelle, et le
    socle doit alors refuser de se construire plutot que d'inventer un
    taux."""
    tenant = Tenant.objects.create(code="SIM-NOTVA", name="No TVA Tenant")
    RegulatoryParameter.objects.filter(code="tva.taux_normal").delete()
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        build_baseline(tenant, as_of_date=dt.date(2026, 9, 30))


def test_deserialize_baseline_data_round_trips_decimals_and_dates(ledger_tenant: Tenant) -> None:
    with use_tenant(ledger_tenant.id):
        baseline = build_baseline(ledger_tenant, as_of_date=dt.date(2026, 9, 30))
        data = deserialize_baseline_data(baseline)

    assert data["ca_ref"] == Decimal("15000000")
    assert data["as_of_date"] == dt.date(2026, 9, 30)
    assert all(isinstance(item["due_date"], dt.date) for item in data["open_items"])
    assert all(isinstance(item["amount_mga"], Decimal) for item in data["open_items"])


def test_build_baseline_degrades_gracefully_without_a_fiscal_year() -> None:
    """Aucun exercice ne couvre `as_of_date` : le socle reste construit
    (jamais une exception) mais `degraded=True` et seul `ca_ref` (via
    `sales.get_revenue_summary`) est renseigné — jamais une valeur
    inventée pour les postes de charges."""
    tenant = Tenant.objects.create(code="SIM-NOFY", name="No Fiscal Year Tenant")
    with use_tenant(tenant.id):
        # Surcharge PROPRE AU TENANT depuis L3, et non plus une ligne
        # globale : `accounting/migrations/0030_seed_vat_reference_rate.py`
        # seme desormais `tva.taux_normal` en valeur globale a partir du
        # 2026-01-01, et deux plages globales qui se chevauchent violent la
        # contrainte d'exclusion `core_regulatory_parameter_no_overlap`.
        # Une surcharge par tenant ne chevauche rien (la contrainte inclut
        # `tenant_id`) et prevaut sur la valeur globale
        # (`services/regulatory.py::get_parameter`) — ce test continue donc
        # d'imposer SA valeur, ce qui est ce qu'il verifie.
        RegulatoryParameterFactory(
            tenant=tenant, code="tva.taux_normal", value=20, valid_from=dt.date(2025, 1, 1)
        )
        baseline = build_baseline(tenant, as_of_date=dt.date(2026, 9, 30))

    assert baseline.data["degraded"] is True
    assert Decimal(baseline.data["achats_consommes_ref"]) == Decimal(0)
