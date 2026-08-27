from __future__ import annotations

import datetime as dt

import pytest
from django.contrib.auth.models import Group, Permission
from django.test import Client

from apps.accounting.models import AccTaxCalendar
from apps.accounting.services.tax_calendar import (
    create_tax_calendar_entry,
    seed_default_tax_calendar,
    upcoming_deadlines,
)
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


def _headers(token: str, tenant_id: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


def test_seed_default_tax_calendar_creates_the_expected_declaration_types() -> None:
    tenant = Tenant.objects.create(code="ACC-CAL", name="Calendrier Fiscal Tenant")
    with use_tenant(tenant.id):
        created = seed_default_tax_calendar(tenant, year=2026)
        types = {entry.declaration_type for entry in created}
        assert types == {
            AccTaxCalendar.DECLARATION_IRSA,
            AccTaxCalendar.DECLARATION_TVA,
            AccTaxCalendar.DECLARATION_IR_ACOMPTE,
            AccTaxCalendar.DECLARATION_IS_ANNUAL,
            AccTaxCalendar.DECLARATION_IR_ANNUAL,
            AccTaxCalendar.DECLARATION_IRCM,
            AccTaxCalendar.DECLARATION_DCOM,
            AccTaxCalendar.DECLARATION_TVM,
            AccTaxCalendar.DECLARATION_IFT,
            AccTaxCalendar.DECLARATION_IFPB,
            AccTaxCalendar.DECLARATION_ETATS_FINANCIERS,
        }
        assert all(entry.is_recurring_template for entry in created)
        is_annual = next(
            e for e in created if e.declaration_type == AccTaxCalendar.DECLARATION_IS_ANNUAL
        )
        assert is_annual.due_date == dt.date(2027, 3, 31)
        dcom = next(e for e in created if e.declaration_type == AccTaxCalendar.DECLARATION_DCOM)
        assert dcom.due_date == dt.date(2027, 6, 30)


def test_seed_default_tax_calendar_is_idempotent() -> None:
    tenant = Tenant.objects.create(code="ACC-CAL2", name="Calendrier Fiscal Tenant 2")
    with use_tenant(tenant.id):
        first = seed_default_tax_calendar(tenant, year=2026)
        second = seed_default_tax_calendar(tenant, year=2026)
        assert len(first) == 11
        assert len(second) == 0
        assert AccTaxCalendar.objects.count() == 11


def test_upcoming_deadlines_filters_past_entries_and_sorts_by_due_date() -> None:
    tenant = Tenant.objects.create(code="ACC-CAL3", name="Calendrier Fiscal Tenant 3")
    with use_tenant(tenant.id):
        today = dt.date(2026, 6, 1)
        create_tax_calendar_entry(
            tenant=tenant,
            declaration_type=AccTaxCalendar.DECLARATION_TVA,
            label="TVA passee",
            due_date=today - dt.timedelta(days=5),
            periodicity=AccTaxCalendar.PERIODICITY_MONTHLY,
        )
        far_entry = create_tax_calendar_entry(
            tenant=tenant,
            declaration_type=AccTaxCalendar.DECLARATION_DCOM,
            label="DCOM lointain",
            due_date=today + dt.timedelta(days=200),
            periodicity=AccTaxCalendar.PERIODICITY_ANNUAL,
        )
        near_entry = create_tax_calendar_entry(
            tenant=tenant,
            declaration_type=AccTaxCalendar.DECLARATION_IRSA,
            label="IRSA proche",
            due_date=today + dt.timedelta(days=10),
            periodicity=AccTaxCalendar.PERIODICITY_MONTHLY,
        )

        deadlines = upcoming_deadlines(tenant, within_days=90, today=today)
        assert [e.id for e in deadlines] == [near_entry.id]
        assert far_entry not in deadlines


@pytest.fixture
def calendar_tenant():
    tenant = Tenant.objects.create(code="ACC-CAL-API", name="Calendrier Fiscal API Tenant")
    return tenant


def test_tax_calendar_api_crud_for_comptable(calendar_tenant) -> None:
    tenant = calendar_tenant
    user = User.objects.create_user(email="cal-api@example.com", password="Str0ngPassw0rd!23")
    # "comptable" fait partie de `settings.CORE_MFA_REQUIRED_ROLES` (Lot 1,
    # etape 4) et bloquerait la connexion JWT sans device TOTP enrole — meme
    # contournement qu'`apps.accounting.tests.test_api::api_ledger` : un
    # groupe ad hoc porteur exactement des permissions Django reellement
    # visees par ce test (view/add sur AccTaxCalendar), plutot que le role
    # complet.
    group, _ = Group.objects.get_or_create(name="accounting-tax-calendar-test")
    group.permissions.add(
        *Permission.objects.filter(
            content_type__app_label="accounting",
            codename__in=["view_acctaxcalendar", "add_acctaxcalendar"],
        )
    )
    user.groups.add(group)

    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    create_response = client.post(
        "/api/v1/accounting/tax-calendar",
        {
            "declaration_type": AccTaxCalendar.DECLARATION_TVA,
            "label": "TVA janvier",
            "due_date": "2026-02-15",
            "periodicity": AccTaxCalendar.PERIODICITY_MONTHLY,
        },
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 200
    body = create_response.json()
    assert body["declaration_type"] == AccTaxCalendar.DECLARATION_TVA
    assert body["due_date"] == "2026-02-15"

    list_response = client.get("/api/v1/accounting/tax-calendar", **headers)
    assert list_response.status_code == 200
    results = list_response.json()["results"]
    assert len(results) == 1
    assert results[0]["label"] == "TVA janvier"

    filtered_response = client.get(
        "/api/v1/accounting/tax-calendar",
        {"declaration_type": AccTaxCalendar.DECLARATION_DCOM},
        **headers,
    )
    assert filtered_response.json()["results"] == []


def test_tax_calendar_api_denied_for_commercial_role(calendar_tenant) -> None:
    """`commercial` n'a aucun acces au module `accounting` selon
    `ROLE_APP_PERMISSIONS` — verifie ici que le refus vaut aussi pour les
    nouveaux endpoints ACC-CAL1."""
    tenant = calendar_tenant
    user = User.objects.create_user(email="cal-outsider@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "commercial")

    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    list_response = client.get("/api/v1/accounting/tax-calendar", **headers)
    assert list_response.status_code == 403

    create_response = client.post(
        "/api/v1/accounting/tax-calendar",
        {
            "declaration_type": AccTaxCalendar.DECLARATION_TVA,
            "label": "TVA janvier",
            "due_date": "2026-02-15",
            "periodicity": AccTaxCalendar.PERIODICITY_MONTHLY,
        },
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 403
