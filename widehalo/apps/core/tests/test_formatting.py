"""Tests du formatage de montants — `format_mga`/`format_mga_precise`
(correctif ecran catalogue, prix avec separateur de milliers + 2
decimales)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.core.templatetags.currency import mga2_filter
from apps.core.utils.formatting import format_mga_precise


def test_format_mga_precise_rounds_to_two_decimals_with_thousands_separator() -> None:
    assert format_mga_precise(Decimal("98610.0000")) == "98\xa0610,00\xa0MGA"


def test_format_mga_precise_rounds_half_up() -> None:
    assert format_mga_precise(Decimal("1234.567")) == "1\xa0234,57\xa0MGA"


def test_format_mga_precise_small_amount_has_no_thousands_separator() -> None:
    assert format_mga_precise(Decimal("42")) == "42,00\xa0MGA"


@pytest.mark.parametrize("value", ["98610.0000", 98610, 98610.0])
def test_mga2_filter_accepts_decimal_int_and_float(value: object) -> None:
    assert mga2_filter(value) == "98\xa0610,00\xa0MGA"
