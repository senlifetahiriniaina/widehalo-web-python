"""Verifie que l'ecran generique "Mes validations en attente" (Lot 1
etape 8, `apps.core.api_workflow`) surfaces les nouvelles
`ApprovalRequest` de qualification (chantier RG-QUALIF) SANS
modification — il est deja generique par content-type — et que l'endpoint
generique `POST /api/v1/approvals/{id}/decide` repercute correctement la
decision sur le statut de la ligne d'import metier concernee, via le
registre de hooks post-decide de `apps.core.api_workflow`."""

from __future__ import annotations

import datetime as dt
import io

import openpyxl
import pytest
from django.contrib.auth.models import Group, Permission
from django.test import Client

from apps.accounting.models import AccAccount, AccFiscalYear, AccImportRow, AccJournal
from apps.accounting.services.cash_journal_import import (
    import_cash_journal_xlsx,
    qualify_import_row,
)
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.auth import issue_tokens
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _access_token(_client: Client, email: str, _password: str) -> str:
    # `issue_tokens` directement, jamais le flux HTTP `/auth/login` : le
    # role "direction" (approbateur par defaut de la regle de
    # qualification, cf. `ensure_qualification_approval_rule`) est soumis
    # a la MFA obligatoire (`settings.CORE_MFA_REQUIRED_ROLES`), hors
    # perimetre de ce test (qui verifie uniquement la visibilite/decision
    # generique par content-type, pas le flux d'authentification MFA).
    user = User.objects.get(email=email)
    access, _refresh = issue_tokens(user)
    return access


def _headers(token: str, tenant_id: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


@pytest.fixture
def qualification_setup():
    tenant = Tenant.objects.create(code="QUALIF-SCREEN-T", name="Qualif Screen Tenant")
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
            tenant=tenant,
            code="FY2026",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 12, 31),
        )
        from apps.accounting.models import AccPeriod

        AccPeriod.objects.create(
            tenant=tenant,
            fiscal_year=fiscal_year,
            code="2026-01",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 1, 31),
        )
        expense_account = AccAccount.objects.create(
            tenant=tenant,
            code="601",
            name="Achats divers",
            account_class=6,
            type=AccAccount.TYPE_EXPENSE,
        )

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["DATE", "CAISSE", "CATEGORIE", "LIBELLE", "ENTREE", "SORTIE"])
    sheet.append([dt.date(2026, 1, 5), "CAISSE", "Non mappee", "Achat", None, 1000])
    buffer = io.BytesIO()
    workbook.save(buffer)

    with use_tenant(tenant.id):
        summary = import_cash_journal_xlsx(tenant, buffer.getvalue())
        row = AccImportRow.objects.get(batch=summary.batch)
        assert row.status == AccImportRow.STATUS_NEEDS_QUALIFICATION

        qualifier = User.objects.create_user(
            email="qualifier@example.com", password="Str0ngPassw0rd!23"
        )
        qualified = qualify_import_row(row, account=expense_account, qualified_by=qualifier)
        assert qualified.status == AccImportRow.STATUS_PENDING_APPROVAL

    approver = User.objects.create_user(email="approver@example.com", password="Str0ngPassw0rd!23")
    group, _ = Group.objects.get_or_create(name="direction")
    group.permissions.add(
        *Permission.objects.filter(
            content_type__app_label="accounting", codename="view_accimportrow"
        )
    )
    approver.groups.add(group)

    return {
        "tenant": tenant,
        "row_id": str(qualified.id),
        "approval_request_id": str(qualified.qualification_approval_request_id),
        "approver": approver,
    }


def test_generic_pending_approvals_endpoint_surfaces_the_qualification_request(
    qualification_setup,
) -> None:
    client = Client()
    token = _access_token(client, "approver@example.com", "Str0ngPassw0rd!23")
    response = client.get(
        "/api/v1/approvals/pending",
        **{"HTTP_AUTHORIZATION": f"Bearer {token}"},
    )

    assert response.status_code == 200
    ids = [entry["id"] for entry in response.json()]
    assert qualification_setup["approval_request_id"] in ids


def test_generic_decide_endpoint_marks_the_import_row_qualified(qualification_setup) -> None:
    tenant = qualification_setup["tenant"]
    client = Client()
    token = _access_token(client, "approver@example.com", "Str0ngPassw0rd!23")

    response = client.post(
        f"/api/v1/approvals/{qualification_setup['approval_request_id']}/decide",
        {"approved": True},
        content_type="application/json",
        **{"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": str(tenant.id)},
    )

    assert response.status_code == 200
    with use_tenant(tenant.id):
        row = AccImportRow.objects.get(id=qualification_setup["row_id"])
        assert row.status == AccImportRow.STATUS_QUALIFIED
