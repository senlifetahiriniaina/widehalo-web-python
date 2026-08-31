"""A16 — Rapprochement bancaire ASSISTE par regles (`acc_reconcile_rule`,
moteur simple montant/reference/tiers), version generique dont A15
(`services/mobile_money.py`) est explicitement le mecanisme plus simple et
autonome (rapprochement `AccPayment` <-> relevé mobile money) — PAS ce
module-ci. Ici, on rapproche une ligne de relevé bancaire EXTERNE
directement a une `AccMoveLine` du GRAND LIVRE du compte bancaire lui-meme
(cf. docstring de `AccBankStatementLine`), ce qui est le rapprochement
bancaire classique.

Reserve legere documentee (meme discipline que le CSV placeholder d'A15) :
le format CSV ci-dessous (`date`, `reference`, `label`, `amount`,
`direction`) est un format PLACEHOLDER, non sourcé d'un export reel d'une
banque malgache (BOA/BNI/BFV/BMOI/MCB/SBM, §2.1 de l'annexe de financement)
— a ajuster une fois un export reel obtenu d'une banque.

OFX : NON implemente ici. Un parseur OFX minimal aurait ete un "nice to
have" si trivialement faisable en stdlib pur ; en pratique OFX (format
SGML-like historique, souvent sans fermeture de balises, ou OFX2/XML avec
un en-tete SGML hybride) n'a pas de parseur fiable dans la stdlib Python
(`xml.etree` echoue sur la variante SGML la plus repandue sans un
pre-traitement non trivial des tags non fermes) — l'ajouter proprement
demanderait soit une bibliotheque tierce (ex. `ofxparse`), explicitement
hors scope ("pas de nouvelle dependance pour cette tache"), soit un
bricolage de parsing regex fragile. DIFFERE, comme le PDF, plutot que
bricole. Seul le CSV (minimum requis par le plan) est implemente.

Ambiguite : jamais de devinette. Si les conditions actives d'une regle
isolent 0 ou plus d'une `AccMoveLine` candidate, cette regle est ignoree
pour cette ligne de relevé (on essaie la regle suivante, par priorite
decroissante) ; si aucune regle ne resout la ligne, elle reste
`unmatched`."""

from __future__ import annotations

import csv
import datetime as dt
import io
import uuid
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext as _

from apps.accounting.models import (
    AccAccount,
    AccBankStatementLine,
    AccMove,
    AccMoveLine,
    AccReconcileRule,
)


def import_bank_statement(bank_account: AccAccount, csv_bytes: bytes) -> list[AccBankStatementLine]:
    """Parse un CSV placeholder (colonnes `date` ISO YYYY-MM-DD, `reference`,
    `label`, `amount`, `direction` in/out) et cree une `AccBankStatementLine`
    par ligne, toutes dans le meme `import_batch_id` (un `uuid4()` genere
    ici, partage par tout l'import), `state="unmatched"`. Refuse un
    `bank_account` qui n'est pas de type `AccAccount.TYPE_BANK` (validation
    applicative, cf. docstring de `AccBankStatementLine` — pas de contrainte
    DB portant sur un champ d'un autre modele)."""
    if bank_account.type != AccAccount.TYPE_BANK:
        raise ValidationError(
            _("Le compte %(code)s n'est pas un compte de banque (type=bank).")
            % {"code": bank_account.code}
        )

    batch_id = uuid.uuid4()
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))
    lines: list[AccBankStatementLine] = []
    for row in reader:
        try:
            amount = Decimal(row["amount"])
        except (KeyError, InvalidOperation) as exc:
            raise ValidationError(
                _("Montant invalide dans le relevé bancaire : %(value)r")
                % {"value": row.get("amount")}
            ) from exc
        try:
            statement_date = dt.date.fromisoformat(row["date"])
        except (KeyError, ValueError) as exc:
            raise ValidationError(
                _("Date invalide dans le relevé bancaire : %(value)r") % {"value": row.get("date")}
            ) from exc
        direction = row.get("direction", "").strip()
        if direction not in (AccBankStatementLine.DIRECTION_IN, AccBankStatementLine.DIRECTION_OUT):
            raise ValidationError(
                _("Sens de transaction invalide dans le relevé bancaire : %(value)r")
                % {"value": direction}
            )
        lines.append(
            AccBankStatementLine.objects.create(
                tenant=bank_account.tenant,
                bank_account=bank_account,
                import_batch_id=batch_id,
                statement_date=statement_date,
                reference_external=row.get("reference", ""),
                label=row.get("label", ""),
                amount_mga=amount,
                direction=direction,
                state=AccBankStatementLine.STATE_UNMATCHED,
            )
        )
    return lines


def _amount_matches(
    move_line: AccMoveLine, statement_line: AccBankStatementLine, rule: AccReconcileRule
) -> bool:
    """`direction="in"` (argent qui entre en banque) se traduit par un debit
    du compte bancaire (actif) ; `direction="out"` par un credit — logique
    debit/credit standard d'un compte d'actif."""
    candidate_amount = (
        move_line.debit
        if statement_line.direction == AccBankStatementLine.DIRECTION_IN
        else move_line.credit
    )
    return abs(candidate_amount - statement_line.amount_mga) <= rule.amount_tolerance_mga


def _reference_matches(move_line: AccMoveLine, statement_line: AccBankStatementLine) -> bool:
    """Correspondance par sous-chaine, direction volontairement BIDIRECTIONNELLE
    et documentee comme telle (le plan laisse le choix de direction a
    l'implementation) : `reference_external` de la ligne de relevé DANS le
    `label` de la `AccMoveLine`, OU l'inverse (le `label` de l'ecriture DANS
    la reference externe) — comparaison insensible a la casse, aux espaces
    de bord. Une reference/label vide ne peut jamais "matcher" (evite une
    correspondance triviale par chaines vides)."""
    reference = (statement_line.reference_external or "").strip().lower()
    label = (move_line.label or "").strip().lower()
    if not reference or not label:
        return False
    return reference in label or label in reference


def _partner_matches(move_line: AccMoveLine, statement_line: AccBankStatementLine) -> bool:
    if statement_line.partner_id is None:
        return False
    return move_line.partner_id == statement_line.partner_id


def _candidate_move_lines(bank_account: AccAccount) -> list[AccMoveLine]:
    """Ecritures publiees, non lettrees, sur ce compte bancaire, pas deja
    retenues comme `matched_move_line` d'une AUTRE ligne de relevé (regle
    ou confirmation manuelle deja en place — jamais deux lignes de relevé
    reservant la meme AccMoveLine)."""
    already_matched_ids = AccBankStatementLine.objects.filter(
        matched_move_line__isnull=False
    ).values_list("matched_move_line_id", flat=True)
    return list(
        AccMoveLine.objects.filter(
            account=bank_account,
            move__state=AccMove.STATE_POSTED,
            reconciled_with__isnull=True,
        ).exclude(id__in=list(already_matched_ids))
    )


def suggest_matches(
    bank_account: AccAccount, *, rules: list[AccReconcileRule] | None = None
) -> list[AccBankStatementLine]:
    """Pour chaque `AccBankStatementLine` `unmatched` de ce compte, evalue
    les `AccReconcileRule` actives (portee sur ce compte OU globales) par
    priorite decroissante. La premiere regle dont les conditions ANDees
    isolent EXACTEMENT une `AccMoveLine` candidate fixe `matched_move_line`
    et passe l'etat a `rule_suggested` (PAS `matched` — confirmation
    humaine requise, cf. `confirm_reconciliation`). Retourne les lignes
    ayant recu une suggestion."""
    if rules is None:
        rules = list(
            AccReconcileRule.objects.filter(is_active=True)
            .filter(Q(bank_account=bank_account) | Q(bank_account__isnull=True))
            .order_by("-priority")
        )

    suggested: list[AccBankStatementLine] = []
    unmatched_lines = AccBankStatementLine.objects.filter(
        bank_account=bank_account, state=AccBankStatementLine.STATE_UNMATCHED
    ).order_by("statement_date")

    for statement_line in unmatched_lines:
        candidates = _candidate_move_lines(bank_account)
        for rule in rules:
            filtered = candidates
            if rule.match_on_amount:
                filtered = [c for c in filtered if _amount_matches(c, statement_line, rule)]
            if rule.match_on_reference:
                filtered = [c for c in filtered if _reference_matches(c, statement_line)]
            if rule.match_on_partner:
                filtered = [c for c in filtered if _partner_matches(c, statement_line)]

            if len(filtered) == 1:
                statement_line.matched_move_line = filtered[0]
                statement_line.state = AccBankStatementLine.STATE_RULE_SUGGESTED
                statement_line.save(update_fields=["matched_move_line", "state"])
                suggested.append(statement_line)
                break
            # 0 ou 2+ candidats : ambigu ou aucune correspondance pour cette
            # regle, on essaie la regle suivante sans jamais deviner.

    return suggested


def confirm_reconciliation(
    statement_line: AccBankStatementLine, *, move_line: AccMoveLine | None = None
) -> AccBankStatementLine:
    """Etape de confirmation HUMAINE. Sans `move_line` explicite, exige que
    `statement_line.state == "rule_suggested"` (une regle a deja propose une
    `matched_move_line`, l'humain se contente de confirmer). Avec `move_line`
    fourni, ce parametre ECRASE toute suggestion de regle (l'humain corrige
    ou choisit lui-meme) — les deux chemins aboutissent a `state="matched"`."""
    if move_line is not None:
        statement_line.matched_move_line = move_line
    elif statement_line.state != AccBankStatementLine.STATE_RULE_SUGGESTED:
        raise ValidationError(
            _(
                "Cette ligne n'a pas de suggestion de règle a confirmer "
                "(fournir `move_line` pour un rapprochement manuel direct)."
            )
        )
    statement_line.state = AccBankStatementLine.STATE_MATCHED
    statement_line.save(update_fields=["matched_move_line", "state"])
    return statement_line


def manual_match(
    statement_line: AccBankStatementLine, move_line: AccMoveLine
) -> AccBankStatementLine:
    """Rapprochement manuel direct, sans passer par aucune regle — pour le
    cas ou aucune regle ne s'applique mais un humain reconnait la
    correspondance a l'oeil."""
    statement_line.matched_move_line = move_line
    statement_line.state = AccBankStatementLine.STATE_MATCHED
    statement_line.save(update_fields=["matched_move_line", "state"])
    return statement_line


def unmatched_or_suggested_lines(bank_account: AccAccount) -> list[AccBankStatementLine]:
    """Liste de travail (`unmatched` + `rule_suggested`) pour un futur ecran
    de rapprochement assiste — meme idee que
    `services/mobile_money.py::unmatched_mobile_money_lines`."""
    return list(
        AccBankStatementLine.objects.filter(
            bank_account=bank_account,
            state__in=[
                AccBankStatementLine.STATE_UNMATCHED,
                AccBankStatementLine.STATE_RULE_SUGGESTED,
            ],
        ).order_by("statement_date")
    )


__all__ = [
    "import_bank_statement",
    "suggest_matches",
    "confirm_reconciliation",
    "manual_match",
    "unmatched_or_suggested_lines",
]
