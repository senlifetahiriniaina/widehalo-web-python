from __future__ import annotations

import uuid

import pytest

from apps.accounting.services.public import (
    assign_partner_role_account,
    list_accounts,
    list_partner_role_accounts,
)
from apps.accounting.tests.factories import AccAccountFactory
from apps.core.tests.factories import TenantFactory, UserFactory
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_list_accounts_filters_by_type() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        expense = AccAccountFactory(tenant=tenant, type="expense")
        AccAccountFactory(tenant=tenant, type="income")

        rows = list_accounts(tenant, account_type="expense")

        assert [row["id"] for row in rows] == [expense.id]


def test_assign_partner_role_account_creates_and_updates_mapping() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        user = UserFactory()
        account_a = AccAccountFactory(tenant=tenant)
        account_b = AccAccountFactory(tenant=tenant)
        partner_id = uuid.uuid4()

        mapping_id = assign_partner_role_account(tenant, partner_id, "client", account_a.id, user)
        assert mapping_id is not None

        rows = list_partner_role_accounts(partner_id)
        assert rows == [
            {
                "role": "client",
                "account_id": account_a.id,
                "account_code": account_a.code,
                "account_name": account_a.name,
            }
        ]

        # Reassigning the same role updates the mapping instead of duplicating it.
        assign_partner_role_account(tenant, partner_id, "client", account_b.id, user)
        rows = list_partner_role_accounts(partner_id)
        assert len(rows) == 1
        assert rows[0]["account_id"] == account_b.id


def test_assign_partner_role_account_returns_none_for_unknown_account() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        user = UserFactory()
        result = assign_partner_role_account(tenant, uuid.uuid4(), "client", uuid.uuid4(), user)
        assert result is None
