"""Ecran de rapprochement bancaire — BNK-1, BNK-2, BNK-3.

**Le moteur existait ; personne ne pouvait s'en servir.** L'import de
releve, la deduplication par ligne et par fichier, le moteur de regles avec
son bareme de confiance et la confirmation humaine sont livres depuis T6,
testes et corrects. Il n'existait **aucun ecran** : ni pour deposer un
releve, ni pour voir la liste de travail, ni pour confirmer une suggestion.
La docstring d'`unmatched_or_suggested_lines` le disait en toutes lettres —
« liste de travail pour un FUTUR ecran de rapprochement assiste ».

Or BNK-3 repose sur une confirmation HUMAINE : `suggest_matches` ne passe
jamais une ligne a `matched`, et `confirm_reconciliation` exige un geste. Un
critere qui exige un humain et ne lui donne pas d'ecran n'est pas tenu — il
est seulement hors de portee de sa propre preuve.

**L'ecran ne poste JAMAIS d'ecriture**, et c'est l'interdit du §4.4 : un
releve ingere produit des PROPOSITIONS de lettrage. Le rapprochement relie
une ligne de releve a une ligne d'ecriture existante ; il n'en cree aucune.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from apps.accounting.models import AccAccount, AccBankStatementLine, AccMove, AccMoveLine
from apps.accounting.services.bank_reconciliation import (
    confirm_reconciliation,
    import_bank_statement,
    manual_match,
    suggest_matches,
    unmatched_or_suggested_lines,
)
from apps.core.services.permissions import screen_forbidden, screen_permission
from apps.core.views.tenant_web import resolve_tenant


def _comptes_bancaires(tenant) -> list[AccAccount]:
    return list(
        AccAccount.objects.filter(
            tenant=tenant,
            is_active=True,
            type__in=(AccAccount.TYPE_BANK, AccAccount.TYPE_CASH),
        ).order_by("code")
    )


def _lignes_rapprochables(compte: AccAccount) -> list[AccMoveLine]:
    """Les ecritures candidates, telles que le moteur les considere.

    L'ecran propose exactement ce que la regle sait viser : une ligne
    d'ecriture publiee portee par CE compte de tresorerie. Proposer autre
    chose ferait esperer un rapprochement que `confirm_reconciliation`
    accepterait sans que la comptabilite ne tienne."""
    return list(
        AccMoveLine.objects.filter(account=compte, move__state=AccMove.STATE_POSTED)
        .select_related("move")
        .order_by("-move__date")[:200]
    )


@login_required
@screen_permission("accounting.view_accbankstatementline")
def bank_reconciliation(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    comptes = _comptes_bancaires(tenant)
    compte_id = request.GET.get("account_id") or (str(comptes[0].id) if comptes else "")
    compte = next((c for c in comptes if str(c.id) == compte_id), None)
    erreur = ""
    rapport = None

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.change_accbankstatementline")
        if refus is not None:
            return refus
        action = request.POST.get("action", "")
        compte = get_object_or_404(AccAccount, id=request.POST.get("account_id"), tenant=tenant)
        try:
            if action == "import":
                fichier = request.FILES.get("statement")
                if fichier is None:
                    raise ValidationError(_("Aucun fichier de relevé fourni."))
                rapport = import_bank_statement(compte, fichier.read())
            elif action == "suggest":
                suggest_matches(compte)
            elif action == "confirm":
                ligne = get_object_or_404(
                    AccBankStatementLine, id=request.POST.get("line_id"), bank_account=compte
                )
                confirm_reconciliation(ligne)
            elif action == "match":
                ligne = get_object_or_404(
                    AccBankStatementLine, id=request.POST.get("line_id"), bank_account=compte
                )
                ecriture = get_object_or_404(
                    AccMoveLine, id=request.POST.get("move_line_id"), account=compte
                )
                manual_match(ligne, ecriture)
        except ValidationError as exc:
            erreur = "; ".join(getattr(exc, "messages", [str(exc)]))
        else:
            if action != "import":
                # Le rapport d'import doit rester a l'ecran ; les autres
                # actions repartent sur une page propre.
                return redirect(f"{request.path}?account_id={compte.id}")

    contexte: dict[str, Any] = {
        "comptes": comptes,
        "compte": compte,
        "error": erreur,
        "rapport": rapport,
        "lignes": unmatched_or_suggested_lines(compte) if compte else [],
        "ecritures": _lignes_rapprochables(compte) if compte else [],
    }
    return render(request, "accounting/bank_reconciliation.html", contexte)
