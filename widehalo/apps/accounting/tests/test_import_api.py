"""Endpoints API pour les imports comptable/caisse depuis Excel (cf.
`services/{chart_of_accounts_import,cash_journal_import}.py`,
`docs/IMPORT_FORMATS.md`)."""

from __future__ import annotations

import datetime as dt
import io

import openpyxl
import pytest
from django.contrib.auth.models import Group, Permission
from django.test import Client

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccPeriod
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


def _xlsx_bytes(header: list[str], rows: list[list]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def tenant():
    return Tenant.objects.create(code="ACC-IMPORT-API", name="Import API Tenant")


@pytest.fixture
def import_user():
    user = User.objects.create_user(email="import-api@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="accounting-import-test")
    group.permissions.add(
        *Permission.objects.filter(
            content_type__app_label="accounting",
            codename__in=[
                "add_accaccount",
                "view_accaccount",
                "add_accimportbatch",
                "view_accimportbatch",
                "add_accimportrow",
                "change_accimportrow",
                "view_accimportrow",
            ],
        )
    )
    user.groups.add(group)
    return user


def test_import_chart_of_accounts_endpoint(tenant, import_user) -> None:
    client = Client()
    token = _access_token(client, import_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    xlsx_bytes = _xlsx_bytes(
        ["Classe", "Code", "Intitulé", "Type"],
        [[5, "571", "Caisse principale", AccAccount.TYPE_CASH]],
    )
    upload = io.BytesIO(xlsx_bytes)
    upload.name = "plan_comptable.xlsx"
    response = client.post(
        "/api/v1/accounting/imports/chart-of-accounts",
        {"file": upload},
        **headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_valid"] is True
    assert data["created_count"] == 1
    with use_tenant(tenant.id):
        assert AccAccount.objects.filter(tenant=tenant, code="571").exists()


def test_import_cash_journal_endpoint_and_resolve(tenant, import_user) -> None:
    client = Client()
    token = _access_token(client, import_user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    with use_tenant(tenant.id):
        fiscal_year = AccFiscalYear.objects.create(
            tenant=tenant,
            code="FY2026",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 12, 31),
        )
        AccPeriod.objects.create(
            tenant=tenant,
            fiscal_year=fiscal_year,
            code="2026-01",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 1, 31),
        )
        AccJournal.objects.create(
            tenant=tenant,
            code="CAISSE",
            name="Caisse",
            type=AccJournal.TYPE_CASH,
            sequence_prefix="CA",
            default_account=AccAccount.objects.create(
                tenant=tenant,
                code="571",
                name="Caisse",
                account_class=5,
                type=AccAccount.TYPE_CASH,
            ),
        )

    xlsx_bytes = _xlsx_bytes(
        ["DATE", "CAISSE", "CATEGORIE", "LIBELLE", "ENTREE", "SORTIE"],
        [
            # Categorie non mappee : DEfaultable depuis RG-QUALIF (compte
            # d'attente), une ecriture est materialisee immediatement.
            [dt.date(2026, 1, 5), "CAISSE", "Non mappee", "Depense diverse", None, 1000],
            # Date hors de toute periode ouverte (aucune periode couvrant
            # 2027 n'existe) : reste `unresolvable`, non-defaultable
            # (inventer une periode n'a pas de repli sûr).
            [dt.date(2027, 6, 15), "CAISSE", "Non mappee", "Hors periode", None, 500],
        ],
    )
    upload = io.BytesIO(xlsx_bytes)
    upload.name = "journal.xlsx"
    response = client.post(
        "/api/v1/accounting/imports/cash-journal",
        {"file": upload},
        **headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_rows"] == 2
    assert data["needs_qualification_count"] == 1
    assert data["anomaly_count"] == 1
    needs_qualification_row = data["needs_qualification_rows"][0]
    assert needs_qualification_row["status"] == "needs_qualification"
    assert "CATEGORIE_NON_MAPPEE" in needs_qualification_row["anomaly_codes"]
    assert needs_qualification_row["uses_placeholder_account"] is True
    unresolvable_row = data["anomaly_rows"][0]
    assert unresolvable_row["status"] == "unresolvable"
    assert "PERIODE_FERMEE_OU_INEXISTANTE" in unresolvable_row["anomaly_codes"]

    with use_tenant(tenant.id):
        account = AccAccount.objects.create(
            tenant=tenant,
            code="601",
            name="Achats divers",
            account_class=6,
            type=AccAccount.TYPE_EXPENSE,
        )

    resolve_response = client.post(
        f"/api/v1/accounting/imports/cash-journal/rows/{unresolvable_row['id']}/resolve",
        {"account_id": str(account.id), "date": "2026-01-05"},
        content_type="application/json",
        **headers,
    )
    assert resolve_response.status_code == 200
    resolved = resolve_response.json()
    assert resolved["status"] == "resolved"
    assert resolved["move_id"] is not None
