"""RG-ACC-7 : toute ecriture en devise etrangere est convertie en MGA au
taux du jour (`acc_exchange_rate`). Les ecarts de change sont constates au
lettrage (cf. services/payments.py, etape A5) et a la cloture."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.accounting.models import AccExchangeRate
from apps.core.models.tenant import Tenant


def get_rate(tenant: Tenant, currency: str, date: dt.date) -> Decimal:
    if currency == tenant.base_currency:
        return Decimal(1)

    rate = (
        AccExchangeRate.objects.filter(tenant=tenant, currency=currency, date__lte=date)
        .order_by("-date")
        .first()
    )
    if rate is None:
        raise ValidationError(
            _("Aucun taux de change connu pour %(currency)s a la date du %(date)s.")
            % {"currency": currency, "date": date}
        )
    return rate.rate_to_mga


def convert_to_mga(amount: Decimal, currency: str, date: dt.date, *, tenant: Tenant) -> Decimal:
    rate = get_rate(tenant, currency, date)
    return (amount * rate).quantize(Decimal("0.0001"))
