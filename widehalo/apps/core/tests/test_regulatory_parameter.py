from __future__ import annotations

import datetime

import pytest
from django.db import IntegrityError, transaction

from apps.core.models.regulatory import RegulatoryParameter
from apps.core.services.regulatory import get_parameter

pytestmark = pytest.mark.django_db


def test_get_parameter_resolves_the_value_valid_at_a_given_date() -> None:
    RegulatoryParameter.objects.create(
        code="vat_rate",
        value={"rate": "20.00"},
        valid_from=datetime.date(2025, 1, 1),
        valid_to=datetime.date(2025, 12, 31),
    )
    RegulatoryParameter.objects.create(
        code="vat_rate",
        value={"rate": "21.00"},
        valid_from=datetime.date(2026, 1, 1),
        valid_to=None,
    )

    assert get_parameter("vat_rate", datetime.date(2025, 6, 1)) == {"rate": "20.00"}
    assert get_parameter("vat_rate", datetime.date(2026, 6, 1)) == {"rate": "21.00"}


def test_get_parameter_raises_when_nothing_matches() -> None:
    with pytest.raises(RegulatoryParameter.DoesNotExist):
        get_parameter("unknown_code", datetime.date(2026, 1, 1))


def test_overlapping_validity_ranges_are_rejected() -> None:
    RegulatoryParameter.objects.create(
        code="threshold",
        value={"amount": "400000000"},
        valid_from=datetime.date(2025, 1, 1),
        valid_to=datetime.date(2025, 12, 31),
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        RegulatoryParameter.objects.create(
            code="threshold",
            value={"amount": "420000000"},
            valid_from=datetime.date(2025, 6, 1),
            valid_to=None,
        )
