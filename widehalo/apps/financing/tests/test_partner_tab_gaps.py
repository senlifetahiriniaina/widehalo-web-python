"""Tests du gap PT9 (chantier "fiche partenaire a onglets par role") sur
le contrat public de `financing` : `list_loan_applications_for_bank_partner`
et `list_credocs_for_bank_partner`."""

from __future__ import annotations

import uuid

import pytest

from apps.core.tests.factories import TenantFactory
from apps.core.tests.utils import use_tenant
from apps.financing.services.public import (
    list_credocs_for_bank_partner,
    list_loan_applications_for_bank_partner,
)
from apps.financing.tests.factories import FinCredocFactory, FinLoanApplicationFactory

pytestmark = pytest.mark.django_db


def test_list_loan_applications_for_bank_partner_returns_rows_for_that_bank() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        partner_id = uuid.uuid4()
        application = FinLoanApplicationFactory(tenant=tenant, bank_partner_id=partner_id)
        FinLoanApplicationFactory(tenant=tenant)  # other bank, must not appear

        rows = list_loan_applications_for_bank_partner(partner_id)

        assert len(rows) == 1
        assert rows[0]["id"] == application.id
        assert rows[0]["reference"] == application.reference
        assert rows[0]["type"] == application.type
        assert rows[0]["amount_requested_mga"] == application.amount_requested_mga
        assert rows[0]["state"] == application.state


def test_list_loan_applications_for_bank_partner_returns_empty_list_for_unknown_partner() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        assert list_loan_applications_for_bank_partner(uuid.uuid4()) == []


def test_list_credocs_for_bank_partner_returns_rows_via_loan_application() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        partner_id = uuid.uuid4()
        application = FinLoanApplicationFactory(tenant=tenant, bank_partner_id=partner_id)
        credoc = FinCredocFactory(tenant=tenant, loan_application=application)
        FinCredocFactory(tenant=tenant)  # no loan_application, must not appear

        rows = list_credocs_for_bank_partner(partner_id)

        assert len(rows) == 1
        assert rows[0]["id"] == credoc.id
        assert rows[0]["reference"] == credoc.reference
        assert rows[0]["bank"] == credoc.bank
        assert rows[0]["amount_mga"] == credoc.amount_mga
        assert rows[0]["state"] == credoc.state


def test_list_credocs_for_bank_partner_returns_empty_list_for_unknown_partner() -> None:
    tenant = TenantFactory()
    with use_tenant(tenant.id):
        assert list_credocs_for_bank_partner(uuid.uuid4()) == []
