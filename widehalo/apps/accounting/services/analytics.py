"""RG-ACC-9 : toute ligne de charge ou de produit doit porter une
distribution analytique dont la somme des pourcentages vaut 100% —
configurable en obligatoire ou facultatif par compte
(`AccAccount.analytic_required`). Une distribution est un JSON de la
forme `{"projet": {"P-042": 100}, "atelier": {"AT-ANTS": 100}}` (§5.1.7) :
chaque PLAN est independant, la somme des pourcentages a l'interieur d'un
meme plan doit valoir 100%, plusieurs plans peuvent s'appliquer a la meme
ligne simultanement."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.accounting.models import AccAccount, AccAnalyticAccount, AccAnalyticLine, AccMoveLine

_PERCENT_TOLERANCE = Decimal("0.01")


def validate_distribution(distribution: dict[str, dict[str, Any]]) -> None:
    for plan_code, allocations in distribution.items():
        total = sum((Decimal(str(value)) for value in allocations.values()), Decimal(0))
        if abs(total - Decimal(100)) > _PERCENT_TOLERANCE:
            raise ValidationError(
                _("La distribution analytique du plan '%(plan)s' totalise %(total)s%%, pas 100%%.")
                % {"plan": plan_code, "total": total}
            )


def enforce_and_validate(account: AccAccount, distribution: dict[str, Any]) -> None:
    if account.analytic_required and not distribution:
        raise ValidationError(
            _("Une distribution analytique est obligatoire pour le compte %(code)s.")
            % {"code": account.code}
        )
    if distribution:
        validate_distribution(distribution)


def record_analytic_lines(move_line: AccMoveLine) -> list[AccAnalyticLine]:
    """Materialise la distribution JSON de `move_line` en lignes
    analytiques concretes, une par (plan, compte analytique) reference."""
    amount = move_line.debit or move_line.credit
    created: list[AccAnalyticLine] = []

    for plan_code, allocations in move_line.analytic_distribution.items():
        for account_code, percentage in allocations.items():
            analytic_account = AccAnalyticAccount.objects.get(
                tenant=move_line.tenant, plan__code=plan_code, code=account_code
            )
            line_amount = (amount * Decimal(str(percentage)) / Decimal(100)).quantize(
                Decimal("0.0001")
            )
            created.append(
                AccAnalyticLine.objects.create(
                    tenant=move_line.tenant,
                    analytic_account=analytic_account,
                    move_line=move_line,
                    date=move_line.move.date,
                    amount=line_amount,
                )
            )

    return created
