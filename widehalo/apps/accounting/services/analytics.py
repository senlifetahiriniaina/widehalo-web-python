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
    analytiques concretes, une par (plan, compte analytique) reference.

    **Appelee par `post_move`, et elle ne l'etait par personne (G-4).** La
    distribution etait validee a la saisie (`enforce_and_validate`, appelee
    par `add_line`) et n'etait JAMAIS materialisee : `AccAnalyticLine`
    restait vide en production. Deux lectures s'appuient pourtant dessus —
    le compte de resultat analytique (`reports.py::
    analytical_income_statement`) et l'ecart budgetaire par axe
    (`budgets.py::_actual_amount`) — et rendaient donc zero partout, sans
    la moindre erreur. Treizieme occurrence du motif « rien de
    decoratif », et l'une des plus discretes : un rapport qui rend zero
    ressemble a une societe qui n'a pas d'activite sur cet axe.

    **Un axe inconnu devient un refus qui le nomme.**
    `AccAnalyticAccount.objects.get` levait `DoesNotExist`, qu'aucun
    gestionnaire ne rattrape — donc 500 a la publication d'une ecriture
    dont la distribution designe un code non declare. Le refus est
    desormais une `ValidationError` qui nomme le plan et le compte, sur le
    chemin de l'ecran comme sur celui de l'API."""
    amount = move_line.debit or move_line.credit
    created: list[AccAnalyticLine] = []

    # **Reprojection, jamais accumulation — et c'est la passe complete qui
    # l'a impose.** En branchant cette fonction sur `post_move`, deux tests
    # de la phase 2 ont double leurs montants : ils l'appelaient eux-memes
    # apres publication, et chaque appel AJOUTAIT un jeu de lignes. Le
    # defaut n'etait pas dans les tests. Les lignes analytiques d'une ligne
    # d'ecriture sont la PROJECTION de sa distribution : deux projections
    # de la meme distribution doivent donner le meme resultat, pas le
    # double. Effacer d'abord rend l'operation idempotente par
    # construction, au lieu de compter sur le fait qu'un seul appelant
    # existe — ce qui etait vrai hier et ne le restera pas.
    AccAnalyticLine.objects.filter(move_line=move_line).delete()

    for plan_code, allocations in move_line.analytic_distribution.items():
        for account_code, percentage in allocations.items():
            analytic_account = AccAnalyticAccount.objects.filter(
                tenant=move_line.tenant, plan__code=plan_code, code=account_code
            ).first()
            if analytic_account is None:
                raise ValidationError(
                    _(
                        "Le compte analytique « %(compte)s » du plan « %(plan)s » "
                        "n'existe pas : déclarez-le avant de publier une écriture "
                        "qui le désigne."
                    )
                    % {"compte": account_code, "plan": plan_code}
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
