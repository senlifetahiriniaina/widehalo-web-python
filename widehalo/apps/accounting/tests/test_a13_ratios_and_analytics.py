"""A13 — ACC-RATIO1/ACC-RATIO2 (ratios financiers) et ACC-ANA (compte de
resultat analytique par axe)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.test import Client

from apps.accounting.models import (
    AccAccount,
    AccAnalyticAccount,
    AccAnalyticPlan,
    AccFiscalYear,
    AccJournal,
    AccPeriod,
)
from apps.accounting.services.analytics import record_analytic_lines
from apps.accounting.services.moves import add_line, create_draft_move, post_move
from apps.accounting.services.reports import analytical_income_statement, financial_ratios
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _make_account(tenant, *, code, name, account_class, type, is_current=True):
    return AccAccount.objects.create(
        tenant=tenant,
        code=code,
        name=name,
        account_class=account_class,
        type=type,
        is_current=is_current,
    )


@pytest.fixture
def bare_ledger():
    tenant = Tenant.objects.create(code="ACC-A13", name="Accounting A13 Tenant")
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
            tenant=tenant, code="OD", name="OD", type=AccJournal.TYPE_MISC, sequence_prefix="OD"
        )
        return tenant, fiscal_year, period, journal


def _post(tenant, journal, period, date, *, debit_account, debit, credit_account, credit):
    move = create_draft_move(tenant=tenant, journal=journal, period=period, date=date)
    add_line(move, account=debit_account, label="D", debit=Decimal(debit))
    add_line(move, account=credit_account, label="C", credit=Decimal(credit))
    return post_move(move)


# ---------------------------------------------------------------------------
# ACC-RATIO1 / ACC-RATIO2 — scenario principal, chaque ratio recalculable a
# la main (cf. commentaires).
# ---------------------------------------------------------------------------


@pytest.fixture
def ratio_ledger(bare_ledger):
    tenant, fiscal_year, period, journal = bare_ledger
    with use_tenant(tenant.id):
        bank = _make_account(
            tenant, code="512", name="Banques", account_class=5, type=AccAccount.TYPE_BANK
        )
        capital = _make_account(
            tenant,
            code="101",
            name="Capital",
            account_class=1,
            type=AccAccount.TYPE_EQUITY,
            is_current=False,
        )
        materiel = _make_account(
            tenant,
            code="215",
            name="Materiel",
            account_class=2,
            type=AccAccount.TYPE_ASSET,
            is_current=False,
        )
        clients = _make_account(
            tenant, code="411", name="Clients", account_class=4, type=AccAccount.TYPE_RECEIVABLE
        )
        fournisseurs = _make_account(
            tenant, code="401", name="Fournisseurs", account_class=4, type=AccAccount.TYPE_PAYABLE
        )
        ventes = _make_account(
            tenant, code="701", name="Ventes", account_class=7, type=AccAccount.TYPE_INCOME
        )
        achats = _make_account(
            tenant, code="601", name="Achats", account_class=6, type=AccAccount.TYPE_EXPENSE
        )
        personnel = _make_account(
            tenant,
            code="641",
            name="Charges de personnel",
            account_class=6,
            type=AccAccount.TYPE_EXPENSE,
        )
        stock = _make_account(
            tenant, code="370", name="Stock", account_class=3, type=AccAccount.TYPE_STOCK
        )

        date = dt.date(2026, 3, 1)
        # 1. Apport de capital.
        _post(
            tenant,
            journal,
            period,
            date,
            debit_account=bank,
            debit=50_000,
            credit_account=capital,
            credit=50_000,
        )
        # 2. Acquisition d'une immobilisation.
        _post(
            tenant,
            journal,
            period,
            date,
            debit_account=materiel,
            debit=40_000,
            credit_account=bank,
            credit=40_000,
        )
        # 3. Vente a credit.
        _post(
            tenant,
            journal,
            period,
            date,
            debit_account=clients,
            debit=100_000,
            credit_account=ventes,
            credit=100_000,
        )
        # 4. Encaissement partiel du client (creance ouverte residuelle : 40 000).
        _post(
            tenant,
            journal,
            period,
            date,
            debit_account=bank,
            debit=60_000,
            credit_account=clients,
            credit=60_000,
        )
        # 5. Achat a credit.
        _post(
            tenant,
            journal,
            period,
            date,
            debit_account=achats,
            debit=30_000,
            credit_account=fournisseurs,
            credit=30_000,
        )
        # 6. Paiement partiel du fournisseur (dette ouverte residuelle : 10 000).
        _post(
            tenant,
            journal,
            period,
            date,
            debit_account=fournisseurs,
            debit=20_000,
            credit_account=bank,
            credit=20_000,
        )
        # 7. Charges de personnel payees comptant.
        _post(
            tenant,
            journal,
            period,
            date,
            debit_account=personnel,
            debit=20_000,
            credit_account=bank,
            credit=20_000,
        )
        # 8. Constatation d'un stock final.
        _post(
            tenant,
            journal,
            period,
            date,
            debit_account=stock,
            debit=8_000,
            credit_account=bank,
            credit=8_000,
        )

    return tenant, fiscal_year


def test_financial_ratios_ratio1_matches_hand_calculation(ratio_ledger) -> None:
    tenant, fiscal_year = ratio_ledger
    with use_tenant(tenant.id):
        data = financial_ratios(fiscal_year)

    ratio1 = data["ratio1"]
    # actif courant 70 000 (411:40 000 + 370:8 000 + 512:22 000) / passif
    # courant 10 000 (401).
    assert ratio1["current_ratio"] == Decimal("7")
    # dettes totales (10 000 + 50 000) - capitaux propres 50 000 = 10 000 ;
    # / capitaux propres 50 000.
    assert ratio1["debt_to_equity"] == Decimal("0.2")
    # resultat net 50 000 (CA 100 000 - achats 30 000 - personnel 20 000) /
    # CA 100 000.
    assert ratio1["marge_nette"] == Decimal("0.5")
    assert ratio1["ebitda"] == Decimal("50000")
    assert ratio1["dso_jours"] == (Decimal(40_000) / Decimal(100_000)) * Decimal(365)
    assert ratio1["dpo_jours"] == (Decimal(10_000) / Decimal(30_000)) * Decimal(365)


def test_financial_ratios_ratio2_matches_hand_calculation_and_flags_negative_treasury(
    ratio_ledger,
) -> None:
    tenant, fiscal_year = ratio_ledger
    with use_tenant(tenant.id):
        data = financial_ratios(fiscal_year)

    ratio2 = data["ratio2"]
    # FDR = passif non courant (capitaux propres, 50 000) - actif non
    # courant (215, 40 000).
    assert ratio2["fdr"] == Decimal("10000")
    # BFR = (stock 8 000 + creances 40 000) - dettes fournisseurs 10 000.
    assert ratio2["bfr"] == Decimal("38000")
    assert ratio2["tresorerie_nette"] == Decimal("10000") - Decimal("38000")
    assert ratio2["liquidite_generale"] == data["ratio1"]["current_ratio"]
    # (actif courant 70 000 - stock 8 000) / passif courant 10 000.
    assert ratio2["liquidite_immediate"] == Decimal("6.2")
    # (CA 100 000 - achats consommes 30 000) / CA 100 000.
    assert ratio2["marge_brute"] == Decimal("0.7")
    assert ratio2["rentabilite_economique"] == Decimal(50_000) / Decimal(110_000)
    assert ratio2["rentabilite_financiere"] == Decimal("1")
    assert ratio2["rotation_stocks_jours"] == (Decimal(8_000) / Decimal(30_000)) * Decimal(365)

    # BFR (38 000) > FDR (10 000) : tresorerie structurellement negative,
    # signal explicitement recherche par les analystes de credit.
    assert data["bfr_superieur_fdr"] is True


def test_bfr_superieur_fdr_flips_false_when_treasury_is_healthy(bare_ledger) -> None:
    """Scenario inverse : gros FDR (forte capitalisation, faible
    immobilisation), BFR faible voire negatif (dettes fournisseurs >
    stock+creances, cas courant d'un cycle finance par les fournisseurs)."""
    tenant, fiscal_year, period, journal = bare_ledger
    with use_tenant(tenant.id):
        bank = _make_account(
            tenant, code="512", name="Banques", account_class=5, type=AccAccount.TYPE_BANK
        )
        capital = _make_account(
            tenant,
            code="101",
            name="Capital",
            account_class=1,
            type=AccAccount.TYPE_EQUITY,
            is_current=False,
        )
        materiel = _make_account(
            tenant,
            code="215",
            name="Materiel",
            account_class=2,
            type=AccAccount.TYPE_ASSET,
            is_current=False,
        )
        clients = _make_account(
            tenant, code="411", name="Clients", account_class=4, type=AccAccount.TYPE_RECEIVABLE
        )
        fournisseurs = _make_account(
            tenant, code="401", name="Fournisseurs", account_class=4, type=AccAccount.TYPE_PAYABLE
        )
        ventes = _make_account(
            tenant, code="701", name="Ventes", account_class=7, type=AccAccount.TYPE_INCOME
        )
        achats = _make_account(
            tenant, code="601", name="Achats", account_class=6, type=AccAccount.TYPE_EXPENSE
        )
        stock = _make_account(
            tenant, code="370", name="Stock", account_class=3, type=AccAccount.TYPE_STOCK
        )

        date = dt.date(2026, 3, 1)
        # Forte capitalisation, faible immobilisation => FDR = 190 000.
        _post(
            tenant,
            journal,
            period,
            date,
            debit_account=bank,
            debit=200_000,
            credit_account=capital,
            credit=200_000,
        )
        _post(
            tenant,
            journal,
            period,
            date,
            debit_account=materiel,
            debit=10_000,
            credit_account=bank,
            credit=10_000,
        )
        # Stock et creances faibles.
        _post(
            tenant,
            journal,
            period,
            date,
            debit_account=stock,
            debit=1_000,
            credit_account=bank,
            credit=1_000,
        )
        _post(
            tenant,
            journal,
            period,
            date,
            debit_account=clients,
            debit=2_000,
            credit_account=ventes,
            credit=2_000,
        )
        # Dette fournisseur superieure au stock+creances => BFR negatif.
        _post(
            tenant,
            journal,
            period,
            date,
            debit_account=achats,
            debit=5_000,
            credit_account=fournisseurs,
            credit=5_000,
        )

        data = financial_ratios(fiscal_year)

    assert data["ratio2"]["fdr"] == Decimal("190000")
    assert data["ratio2"]["bfr"] == Decimal("-2000")
    assert data["bfr_superieur_fdr"] is False


def test_financial_ratios_returns_none_for_zero_denominators(bare_ledger) -> None:
    """Tenant sans aucun mouvement (CA nul, capitaux propres nuls, aucune
    dette fournisseur) : tous les ratios a denominateur nul renvoient
    `None`, jamais une exception."""
    tenant, fiscal_year, _period, _journal = bare_ledger
    with use_tenant(tenant.id):
        data = financial_ratios(fiscal_year)

    assert data["ratio1"]["current_ratio"] is None
    assert data["ratio1"]["debt_to_equity"] is None
    assert data["ratio1"]["marge_nette"] is None
    assert data["ratio1"]["dso_jours"] is None
    assert data["ratio1"]["dpo_jours"] is None
    assert data["ratio1"]["ebitda"] == Decimal(0)
    assert data["ratio2"]["liquidite_generale"] is None
    assert data["ratio2"]["liquidite_immediate"] is None
    assert data["ratio2"]["marge_brute"] is None
    assert data["ratio2"]["rentabilite_economique"] is None
    assert data["ratio2"]["rentabilite_financiere"] is None
    assert data["ratio2"]["rotation_stocks_jours"] is None
    # FDR/BFR/tresorerie nette restent calculables (pas de division) : tout
    # a zero, donc pas de tresorerie structurellement negative.
    assert data["ratio2"]["fdr"] == Decimal(0)
    assert data["ratio2"]["bfr"] == Decimal(0)
    assert data["bfr_superieur_fdr"] is False


# ---------------------------------------------------------------------------
# ACC-ANA — compte de resultat analytique par axe
# ---------------------------------------------------------------------------


@pytest.fixture
def analytic_ledger(bare_ledger):
    tenant, fiscal_year, period, journal = bare_ledger
    with use_tenant(tenant.id):
        bank = _make_account(
            tenant, code="512", name="Banques", account_class=5, type=AccAccount.TYPE_BANK
        )
        ventes = _make_account(
            tenant, code="701", name="Ventes", account_class=7, type=AccAccount.TYPE_INCOME
        )
        achats = _make_account(
            tenant, code="601", name="Achats", account_class=6, type=AccAccount.TYPE_EXPENSE
        )
        plan = AccAnalyticPlan.objects.create(tenant=tenant, code="projet", name="Projet")
        p1 = AccAnalyticAccount.objects.create(tenant=tenant, plan=plan, code="P1", name="Projet 1")
        p2 = AccAnalyticAccount.objects.create(tenant=tenant, plan=plan, code="P2", name="Projet 2")

        date = dt.date(2026, 2, 1)

        def _posted_line(*, account, debit=Decimal(0), credit=Decimal(0), distribution):
            move = create_draft_move(tenant=tenant, journal=journal, period=period, date=date)
            line = add_line(
                move,
                account=account,
                debit=debit,
                credit=credit,
                analytic_distribution=distribution,
            )
            counter_account = bank
            add_line(
                move,
                account=counter_account,
                credit=debit,
                debit=credit,
            )
            post_move(move)
            record_analytic_lines(line)

        # Produits : 6 000 sur P1, 4 000 sur P2.
        _posted_line(account=ventes, credit=Decimal(6_000), distribution={"projet": {"P1": 100}})
        _posted_line(account=ventes, credit=Decimal(4_000), distribution={"projet": {"P2": 100}})
        # Charges : 3 000 sur P1, 1 000 sur P2.
        _posted_line(account=achats, debit=Decimal(3_000), distribution={"projet": {"P1": 100}})
        _posted_line(account=achats, debit=Decimal(1_000), distribution={"projet": {"P2": 100}})

    return tenant, fiscal_year, plan, p1, p2


def test_analytical_income_statement_splits_produits_charges_per_axis(analytic_ledger) -> None:
    tenant, fiscal_year, plan, p1, p2 = analytic_ledger
    with use_tenant(tenant.id):
        rows = analytical_income_statement(fiscal_year, plan)

    by_code = {row["code"]: row for row in rows}
    assert by_code["P1"]["produits"] == Decimal("6000.0000")
    assert by_code["P1"]["charges"] == Decimal("3000.0000")
    assert by_code["P1"]["net"] == Decimal("3000.0000")
    assert by_code["P2"]["produits"] == Decimal("4000.0000")
    assert by_code["P2"]["charges"] == Decimal("1000.0000")
    assert by_code["P2"]["net"] == Decimal("3000.0000")


def test_analytical_income_statement_is_scoped_to_the_fiscal_year(analytic_ledger) -> None:
    tenant, fiscal_year, plan, _p1, _p2 = analytic_ledger
    with use_tenant(tenant.id):
        other_fiscal_year = AccFiscalYear.objects.create(
            tenant=tenant,
            code="FY2027",
            date_start=dt.date(2027, 1, 1),
            date_end=dt.date(2027, 12, 31),
        )
        rows = analytical_income_statement(other_fiscal_year, plan)
    assert rows == []


# ---------------------------------------------------------------------------
# API — /reports/financial-ratios et /reports/analytical-income-statement
# ---------------------------------------------------------------------------


def _access_token(client: Client, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.json()["access"]


def _headers(token: str, tenant_id: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


@pytest.fixture
def api_user():
    user = User.objects.create_user(email="a13-api@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="accounting-a13-test")
    group.permissions.add(
        *Permission.objects.filter(
            content_type__app_label="accounting",
            codename__in=["view_accaccount", "view_accmove"],
        )
    )
    user.groups.add(group)
    return user


def test_financial_ratios_endpoint_returns_the_nested_ratio_dict(ratio_ledger, api_user) -> None:
    tenant, fiscal_year = ratio_ledger
    client = Client()
    token = _access_token(client, api_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get(
        f"/api/v1/accounting/reports/financial-ratios?fiscal_year_id={fiscal_year.id}", **headers
    )
    assert response.status_code == 200
    payload = response.json()
    assert "ratio1" in payload and "ratio2" in payload
    assert payload["bfr_superieur_fdr"] is True
    assert payload["ratio1"]["current_ratio"] == "7"


def test_analytical_income_statement_endpoint_supports_csv_export(
    analytic_ledger, api_user
) -> None:
    tenant, fiscal_year, plan, _p1, _p2 = analytic_ledger
    client = Client()
    token = _access_token(client, api_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get(
        "/api/v1/accounting/reports/analytical-income-statement"
        f"?fiscal_year_id={fiscal_year.id}&analytic_plan_id={plan.id}&format=csv",
        **headers,
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    body = response.content.decode("utf-8")
    assert "P1" in body and "P2" in body
