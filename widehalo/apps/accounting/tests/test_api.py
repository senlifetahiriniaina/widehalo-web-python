from __future__ import annotations

import datetime as dt

import pytest
from django.contrib.auth.models import Group, Permission
from django.test import Client

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccPeriod
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant

pytestmark = pytest.mark.django_db


def _access_token(client: Client, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.json()["access"]


@pytest.fixture
def api_ledger():
    tenant = Tenant.objects.create(code="ACC-API", name="Accounting API Tenant")
    user = User.objects.create_user(email="acc-api@example.com", password="Str0ngPassw0rd!23")
    # Un groupe distinct de "comptable" : ce dernier fait partie de
    # CORE_MFA_REQUIRED_ROLES (Lot 1, etape 4) et bloquerait la connexion
    # JWT de ce test tant qu'un device TOTP n'est pas enrole. Note (T6,
    # wiring require_permission) : on ne peut donc PAS simplifier ceci en
    # `grant_role(user, "comptable")` malgre que ce role couvre desormais
    # les permissions necessaires via ROLE_APP_PERMISSIONS/CUSTOM_
    # PERMISSIONS — verifie, "comptable"/"direction"/"admin" sont TOUS
    # dans CORE_MFA_REQUIRED_ROLES. On reste donc sur un groupe ad hoc,
    # etendu avec les permissions Django reellement exercees par les tests
    # de ce fichier (vue comptes, creation + validation de facture, PDF).
    group, _ = Group.objects.get_or_create(name="accounting-api-test-validators")
    group.permissions.add(
        *Permission.objects.filter(
            content_type__app_label="accounting",
            codename__in=[
                "validate_accmove",
                "view_accaccount",
                "view_accmove",
                "add_accmove",
                "view_accasset",
                "add_accasset",
                "change_accasset",
                "add_accassetdepreciation",
                "view_accprovision",
                "add_accprovision",
            ],
        )
    )
    user.groups.add(group)

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
            code="VTE",
            name="Ventes",
            type=AccJournal.TYPE_SALE,
            sequence_prefix="VTE",
        )
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

    return tenant, user, fiscal_year, period, journal, receivable, income


def _headers(token: str, tenant_id: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


def test_create_and_validate_invoice_via_api(api_ledger) -> None:
    tenant, user, _fy, period, journal, receivable, income = api_ledger
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/accounting/invoices",
        {
            "journal_id": str(journal.id),
            "period_id": str(period.id),
            "date": "2026-01-15",
            "receivable_account_id": str(receivable.id),
            "lines": [{"account_id": str(income.id), "amount": "1000", "label": "Vente"}],
        },
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    invoice_id = create_response.json()["id"]
    assert create_response.json()["state"] == "draft"

    validate_response = client.post(f"/api/v1/accounting/invoices/{invoice_id}/validate", **headers)
    assert validate_response.status_code == 200
    body = validate_response.json()
    assert body["state"] == "posted"
    assert body["invoice_state"] == "validated"
    assert body["reference"] != ""


def test_list_accounts_via_api(api_ledger) -> None:
    tenant, user, *_ = api_ledger
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get("/api/v1/accounting/accounts", **headers)
    assert response.status_code == 200
    codes = {a["code"] for a in response.json()["results"]}
    assert {"411", "701"} <= codes


def test_register_asset_and_fixed_asset_annexes_via_api(api_ledger) -> None:
    tenant, user, fiscal_year, period, journal, receivable, income = api_ledger
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    with use_tenant(tenant.id):
        immo_account = AccAccount.objects.create(
            tenant=tenant, code="2183", name="Materiel", account_class=2, type=AccAccount.TYPE_ASSET
        )

    create_response = client.post(
        "/api/v1/accounting/assets",
        {
            "category": "corporelle",
            "label": "Machine API",
            "account_id": str(immo_account.id),
            "acquisition_date": "2026-01-01",
            "acquisition_value_mga": "1000000",
            "depreciation_method": "lineaire",
            "useful_life_years": 5,
        },
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    asset_id = create_response.json()["id"]
    assert create_response.json()["state"] == "active"

    compute_response = client.post(
        f"/api/v1/accounting/assets/{asset_id}/depreciation/compute",
        {"fiscal_year_id": str(fiscal_year.id), "post": False},
        content_type="application/json",
        **headers,
    )
    assert compute_response.status_code == 200
    assert compute_response.json()["annual_dotation_mga"] == "200000.0000"

    annexes_response = client.get(
        f"/api/v1/accounting/reports/fixed-asset-annexes?fiscal_year_id={fiscal_year.id}", **headers
    )
    assert annexes_response.status_code == 200
    body = annexes_response.json()
    expected_keys = {"actif_immobilise", "amortissements", "provisions", "creances_dettes"}
    assert expected_keys == set(body.keys())


def test_invoice_pdf_endpoint_returns_a_pdf(api_ledger) -> None:
    tenant, user, _fy, period, journal, receivable, income = api_ledger
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/accounting/invoices",
        {
            "journal_id": str(journal.id),
            "period_id": str(period.id),
            "date": "2026-01-15",
            "receivable_account_id": str(receivable.id),
            "lines": [{"account_id": str(income.id), "amount": "1000", "label": "Vente"}],
        },
        content_type="application/json",
        **headers,
    )
    invoice_id = create_response.json()["id"]
    client.post(f"/api/v1/accounting/invoices/{invoice_id}/validate", **headers)

    pdf_response = client.get(f"/api/v1/accounting/invoices/{invoice_id}/pdf", **headers)
    assert pdf_response.status_code == 200
    assert pdf_response["Content-Type"] == "application/pdf"
    assert pdf_response.content.startswith(b"%PDF")


def test_validate_invoice_via_api_denied_without_permission(api_ledger) -> None:
    """Regression T6/RBAC : require_permission("accounting.validate_accmove")
    doit refuser (403) un utilisateur authentifie qui n'a pas cette
    permission — ici un "collaborateur", role par defaut sans acces au
    module accounting."""
    tenant, user, _fy, period, journal, receivable, income = api_ledger
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/accounting/invoices",
        {
            "journal_id": str(journal.id),
            "period_id": str(period.id),
            "date": "2026-01-15",
            "receivable_account_id": str(receivable.id),
            "lines": [{"account_id": str(income.id), "amount": "1000", "label": "Vente"}],
        },
        content_type="application/json",
        **headers,
    )
    invoice_id = create_response.json()["id"]

    outsider = User.objects.create_user(
        email="acc-outsider@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(outsider, "collaborateur")
    outsider_token = _access_token(client, outsider.email, "Str0ngPassw0rd!23")
    outsider_headers = _headers(outsider_token, str(tenant.id))

    response = client.post(f"/api/v1/accounting/invoices/{invoice_id}/validate", **outsider_headers)
    assert response.status_code == 403
