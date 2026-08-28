"""Endpoints API de qualification (chantier RG-QUALIF) — `POST .../rows/
{id}/qualify` pour le journal de caisse et l'import de factures. L'acte
d'approuver une qualification en attente est deja couvert par
`apps.core.tests.test_qualification_generic_approval_screen` (endpoint
generique `/approvals/{id}/decide`, reutilise tel quel)."""

from __future__ import annotations

import datetime as dt
import io

import openpyxl
import pytest
from django.contrib.auth.models import Group, Permission
from django.test import Client

from apps.accounting.models import (
    AccAccount,
    AccFiscalYear,
    AccImportRow,
    AccInvoiceImportRow,
    AccJournal,
    AccPeriod,
)
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


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
def tenant():
    return Tenant.objects.create(code="ACC-QUALIF-API", name="Qualif API Tenant")


@pytest.fixture
def qualifier_user():
    user = User.objects.create_user(email="qualif-api@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="qualif-api-test")
    group.permissions.add(
        *Permission.objects.filter(
            content_type__app_label="accounting",
            codename__in=[
                "add_accaccount",
                "view_accaccount",
                "add_accimportbatch",
                "view_accimportbatch",
                "change_accimportrow",
                "view_accimportrow",
                "qualify_accimportrow",
                "qualify_accinvoiceimportrow",
            ],
        )
    )
    user.groups.add(group)
    return user


def test_qualify_cash_journal_import_row_endpoint(tenant, qualifier_user) -> None:
    client = Client()
    token = _access_token(client, qualifier_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    with use_tenant(tenant.id):
        cash_account = AccAccount.objects.create(
            tenant=tenant, code="571", name="Caisse", account_class=5, type=AccAccount.TYPE_CASH
        )
        AccJournal.objects.create(
            tenant=tenant,
            code="CAISSE",
            name="Caisse",
            type=AccJournal.TYPE_CASH,
            sequence_prefix="CA",
            default_account=cash_account,
        )
        fiscal_year = AccFiscalYear.objects.create(
            tenant=tenant, code="FY2026", date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 12, 31)
        )
        AccPeriod.objects.create(
            tenant=tenant,
            fiscal_year=fiscal_year,
            code="2026-01",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 1, 31),
        )
        real_account = AccAccount.objects.create(
            tenant=tenant, code="601", name="Achats", account_class=6, type=AccAccount.TYPE_EXPENSE
        )

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["DATE", "CAISSE", "CATEGORIE", "LIBELLE", "ENTREE", "SORTIE"])
    sheet.append([dt.date(2026, 1, 5), "CAISSE", "Non mappee", "Achat", None, 1000])
    buffer = io.BytesIO()
    workbook.save(buffer)
    upload = io.BytesIO(buffer.getvalue())
    upload.name = "journal.xlsx"

    import_response = client.post(
        "/api/v1/accounting/imports/cash-journal", {"file": upload}, **headers
    )
    row = import_response.json()["needs_qualification_rows"][0]
    assert row["uses_placeholder_account"] is True

    qualify_response = client.post(
        f"/api/v1/accounting/imports/cash-journal/rows/{row['id']}/qualify",
        {"account_id": str(real_account.id)},
        content_type="application/json",
        **headers,
    )

    assert qualify_response.status_code == 200
    data = qualify_response.json()
    assert data["status"] in (
        AccImportRow.STATUS_QUALIFIED,
        AccImportRow.STATUS_PENDING_APPROVAL,
    )
    assert data["uses_placeholder_account"] is False


def test_qualify_invoice_import_row_endpoint(tenant, qualifier_user) -> None:
    client = Client()
    token = _access_token(client, qualifier_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    with use_tenant(tenant.id):
        AccAccount.objects.create(
            tenant=tenant,
            type=AccAccount.TYPE_RECEIVABLE,
            code="411",
            name="Clients",
            account_class=4,
        )
        AccAccount.objects.create(
            tenant=tenant, type=AccAccount.TYPE_INCOME, code="707", name="Ventes", account_class=7
        )
        AccJournal.objects.create(
            tenant=tenant, type=AccJournal.TYPE_SALE, code="VTE", name="Ventes", sequence_prefix="V"
        )
        fiscal_year = AccFiscalYear.objects.create(
            tenant=tenant, code="FY2026", date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 12, 31)
        )
        AccPeriod.objects.create(
            tenant=tenant,
            fiscal_year=fiscal_year,
            code="2026-01",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 1, 31),
        )
        tax_account = AccAccount.objects.create(
            tenant=tenant, type=AccAccount.TYPE_TAX, code="4457", name="TVA", account_class=4
        )

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "REFERENCE",
            "DATE",
            "SENS",
            "PARTENAIRE",
            "CODE_PRODUIT",
            "DESIGNATION",
            "QUANTITE",
            "PRIX_UNITAIRE",
            "TAUX_TVA",
            "COMPTE",
        ]
    )
    sheet.append(["FAC-API-1", dt.date(2026, 1, 5), "client", "Client X", "REF", "Vente", 1, 100, None, ""])
    buffer = io.BytesIO()
    workbook.save(buffer)
    upload = io.BytesIO(buffer.getvalue())
    upload.name = "factures.xlsx"

    import_response = client.post("/api/v1/accounting/imports/invoices", {"file": upload}, **headers)
    row = import_response.json()["needs_qualification_rows"][0]
    assert row["uses_placeholder_tax"] is True

    qualify_response = client.post(
        f"/api/v1/accounting/imports/invoices/rows/{row['id']}/qualify",
        {"tax_account_id": str(tax_account.id)},
        content_type="application/json",
        **headers,
    )

    assert qualify_response.status_code == 200
    data = qualify_response.json()
    assert data["uses_placeholder_tax"] is False
    assert data["status"] in (
        AccInvoiceImportRow.STATUS_QUALIFIED,
        AccInvoiceImportRow.STATUS_PENDING_APPROVAL,
    )


def test_qualify_endpoint_forbidden_without_permission(tenant) -> None:
    unauthorized_user = User.objects.create_user(
        email="no-perm@example.com", password="Str0ngPassw0rd!23"
    )
    client = Client()
    token = _access_token(client, unauthorized_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.post(
        "/api/v1/accounting/imports/cash-journal/rows/00000000-0000-7000-8000-000000000000/qualify",
        {},
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 403
