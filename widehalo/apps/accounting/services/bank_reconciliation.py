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
import hashlib
import io
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounting.models import (
    AccAccount,
    AccBankStatementLine,
    AccMove,
    AccMoveLine,
    AccReconcileRule,
)

#: Les colonnes attendues du format CSV. Déclarées plutôt que lues au fil
#: du code : le rapport de chargement doit pouvoir dire QUELLE colonne
#: manque, et un `row["amount"]` disséminé ne le permet pas.
COLUMN_DATE = "date"
COLUMN_REFERENCE = "reference"
COLUMN_LABEL = "label"
COLUMN_AMOUNT = "amount"
COLUMN_DIRECTION = "direction"


@dataclass(frozen=True)
class RejectedLine:
    """Une ligne que le chargement n'a pas su lire, et pourquoi.

    `line_number` compte les lignes du FICHIER, en-tête comprise — c'est
    ce que l'exploitant voit dans son tableur, et lui donner un index de
    ligne de données l'obligerait à faire l'addition lui-même sur un
    export de plusieurs centaines de lignes."""

    line_number: int
    reason: str
    raw: dict[str, str]


@dataclass(frozen=True)
class StatementImportReport:
    """BNK-2 — « un rapport de chargement exploitable ».

    « Exploitable » veut dire : on sait ce qui est entré, ce qui ne l'est
    pas, et pourquoi. Un booléen ou un compte ne suffiraient pas — c'est
    la LIGNE fautive que l'exploitant doit retrouver."""

    lines: list[AccBankStatementLine]
    rejected: list[RejectedLine]
    duplicates: list[RejectedLine]
    already_imported: bool
    fingerprint: str

    @property
    def loaded_count(self) -> int:
        return len(self.lines)


def _statement_fingerprint(rows: list[dict[str, str]]) -> str:
    """L'empreinte d'un relevé, insensible à ce qui ne le change pas.

    Calculée sur les VALEURS normalisées et TRIÉES, jamais sur les octets :
    une banque qui ré-exporte le même relevé change volontiers l'ordre des
    colonnes, la casse d'un libellé ou les espaces de bord, sans qu'aucune
    opération n'ait bougé. Une empreinte d'octets manquerait donc
    exactement le cas que BNK-1 vise — « le rechargement d'un relevé déjà
    importé »."""
    graine = "\n".join(
        sorted(
            "|".join(
                (row.get(col) or "").strip().lower()
                for col in (
                    COLUMN_DATE,
                    COLUMN_REFERENCE,
                    COLUMN_LABEL,
                    COLUMN_AMOUNT,
                    COLUMN_DIRECTION,
                )
            )
            for row in rows
        )
    )
    return hashlib.sha256(graine.encode("utf-8")).hexdigest()


def _existing_line_keys(
    bank_account: AccAccount,
) -> set[tuple[dt.date, str, Decimal, str]]:
    """Les lignes DÉJÀ chargées sur ce compte, sous forme de clefs.

    **Lues en UNE requête, jamais une par ligne du fichier.** Un relevé
    mensuel porte couramment plusieurs centaines de lignes ; interroger la
    base pour chacune ferait du chargement une opération dont le coût
    croît avec l'historique du compte — le défaut quadratique déjà payé
    une fois sur l'import de tiers."""
    return {
        (
            ligne["statement_date"],
            (ligne["reference_external"] or "").strip().lower(),
            # **Le `Decimal` lui-même, jamais sa forme imprimée.** La base
            # rend `Decimal("150000.0000")` (quatre décimales déclarées), le
            # fichier `Decimal("150000")` : deux chaînes différentes pour le
            # même montant. Comparer les représentations faisait échouer
            # toute déduplication en silence — la ligne était rechargée, et
            # rien ne le signalait. `Decimal` compare et hache par VALEUR,
            # ce qui est la seule question posée ici.
            ligne["amount_mga"],
            ligne["direction"],
        )
        for ligne in AccBankStatementLine.objects.filter(bank_account=bank_account).values(
            "statement_date", "reference_external", "amount_mga", "direction"
        )
    }


def _parse_row(
    row: dict[str, str], line_number: int
) -> tuple[dict[str, Any] | None, RejectedLine | None]:
    """Lit une ligne, ou dit pourquoi elle est illisible.

    **Ne lève jamais.** C'est tout l'objet de BNK-2 : une ligne fautive
    n'interrompt pas le lot. La version précédente levait une
    `ValidationError` à la première anomalie, et comme les lignes étaient
    écrites au fil de la boucle sans transaction, le lot restait chargé À
    MOITIÉ — mesuré : un relevé de trois lignes dont la deuxième est
    illisible laissait la première en base, rendait un 400, et le ré-essai
    après correction du fichier la dupliquait. Les deux critères tombaient
    ensemble."""
    brut = {clef: (valeur or "") for clef, valeur in row.items() if clef}

    montant_brut = (row.get(COLUMN_AMOUNT) or "").strip()
    try:
        montant = Decimal(montant_brut)
    except InvalidOperation:
        return None, RejectedLine(
            line_number=line_number,
            reason=str(
                _("Montant illisible : %(valeur)r.")
                % {"valeur": montant_brut or row.get(COLUMN_AMOUNT)}
            ),
            raw=brut,
        )

    date_brute = (row.get(COLUMN_DATE) or "").strip()
    try:
        date_operation = dt.date.fromisoformat(date_brute)
    except ValueError:
        return None, RejectedLine(
            line_number=line_number,
            reason=str(
                _("Date illisible : %(valeur)r (attendu AAAA-MM-JJ).") % {"valeur": date_brute}
            ),
            raw=brut,
        )

    direction = (row.get(COLUMN_DIRECTION) or "").strip()
    if direction not in (AccBankStatementLine.DIRECTION_IN, AccBankStatementLine.DIRECTION_OUT):
        return None, RejectedLine(
            line_number=line_number,
            reason=str(
                _("Sens de transaction inconnu : %(valeur)r (attendu « in » ou « out »).")
                % {"valeur": direction}
            ),
            raw=brut,
        )

    return (
        {
            "statement_date": date_operation,
            "reference_external": (row.get(COLUMN_REFERENCE) or "").strip(),
            "label": (row.get(COLUMN_LABEL) or "").strip(),
            "amount_mga": montant,
            "direction": direction,
        },
        None,
    )


def import_bank_statement(bank_account: AccAccount, csv_bytes: bytes) -> StatementImportReport:
    """Charge un relevé, isole ce qu'il ne sait pas lire, ne duplique rien.

    **BNK-2** : « une ligne de relevé en anomalie n'interrompt pas le
    chargement du lot ; elle est isolée dans un rapport de chargement
    exploitable ». Les lignes lisibles entrent, les autres sont décrites
    avec leur numéro et leur motif.

    **BNK-1** : « le rechargement d'un relevé déjà importé ne crée aucun
    doublon de ligne et le signale explicitement ». Deux protections, et
    elles ne font pas double emploi :

    1. *Par ligne*, sur (date, référence, montant, sens) — mais UNIQUEMENT
       quand la référence est renseignée. Sans référence, deux opérations
       du même jour, du même montant et du même sens sont indiscernables
       d'un doublon, et les confondre ferait DISPARAÎTRE une opération
       réelle. C'est le même refus de deviner que PAY-3 : mieux vaut un
       doublon visible qu'une écriture perdue.
    2. *Par fichier*, sur l'empreinte du contenu normalisé — qui rattrape
       précisément le cas que la première laisse passer, celui d'une banque
       qui ne fournit pas de référence.

    **Tout ou rien pour ce qui est écrit.** Le chargement est atomique :
    ou bien les lignes retenues entrent toutes, ou bien aucune. C'est ce
    qui manquait, et c'est ce qui transformait une anomalie de format en
    doublons au ré-essai."""
    if bank_account.type != AccAccount.TYPE_BANK:
        raise ValidationError(
            _("Le compte %(code)s n'est pas un compte de banque (type=bank).")
            % {"code": bank_account.code}
        )

    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8", "replace")))
    rows = list(reader)
    empreinte = _statement_fingerprint(rows)

    if AccBankStatementLine.objects.filter(
        bank_account=bank_account, import_fingerprint=empreinte
    ).exists():
        return StatementImportReport(
            lines=[],
            rejected=[],
            duplicates=[],
            already_imported=True,
            fingerprint=empreinte,
        )

    deja_presentes = _existing_line_keys(bank_account)
    retenues: list[dict[str, Any]] = []
    rejetees: list[RejectedLine] = []
    doublons: list[RejectedLine] = []

    for index, row in enumerate(rows, start=2):  # start=2 : l'en-tête est la ligne 1.
        valeurs, rejet = _parse_row(row, index)
        if rejet is not None:
            rejetees.append(rejet)
            continue
        assert valeurs is not None  # noqa: S101 - _parse_row rend l'un ou l'autre, jamais ni l'un ni l'autre.

        reference = valeurs["reference_external"]
        clef = (
            valeurs["statement_date"],
            reference.lower(),
            valeurs["amount_mga"],
            valeurs["direction"],
        )
        if reference and clef in deja_presentes:
            doublons.append(
                RejectedLine(
                    line_number=index,
                    reason=str(
                        _("Opération déjà chargée (référence %(ref)s).") % {"ref": reference}
                    ),
                    raw={clef: (valeur or "") for clef, valeur in row.items() if clef},
                )
            )
            continue
        deja_presentes.add(clef)
        retenues.append(valeurs)

    batch_id = uuid.uuid4()
    with transaction.atomic():
        lignes = AccBankStatementLine.objects.bulk_create(
            [
                AccBankStatementLine(
                    tenant=bank_account.tenant,
                    bank_account=bank_account,
                    import_batch_id=batch_id,
                    import_fingerprint=empreinte,
                    state=AccBankStatementLine.STATE_UNMATCHED,
                    **valeurs,
                )
                for valeurs in retenues
            ]
        )

    return StatementImportReport(
        lines=list(lignes),
        rejected=rejetees,
        duplicates=doublons,
        already_imported=False,
        fingerprint=empreinte,
    )


#: BNK-3 — ce que vaut chaque condition dans le niveau de confiance.
#:
#: **Réserve écrite, parce que le cahier n'en donne aucun.** Il exige « un
#: niveau de confiance » sans dire comment le calculer. Le barème ci-dessous
#: est donc un PARAMÈTRE déclaré, pas une règle découverte : montant et
#: référence pèsent autant l'un que l'autre — une référence bancaire est une
#: clef, un montant qui tombe juste au centime aussi —, et le tiers seul ne
#: fait que corroborer, un même client réglant plusieurs factures.
#:
#: La somme des trois vaut 100 : une règle qui exige les trois conditions
#: produit une proposition à 100, une règle sur le seul montant à 40. Ce
#: qu'un exploitant doit lire est l'ÉCART entre les deux, pas la valeur
#: absolue.
CONFIDENCE_BY_CRITERION = {
    "amount": 40,
    "reference": 40,
    "partner": 20,
}


def _confidence_of(rule: AccReconcileRule) -> int:
    """Le niveau de confiance d'une proposition issue de cette règle.

    Porté par la RÈGLE et non par la ligne : ce qui distingue une
    proposition sûre d'une proposition faible, c'est le nombre de
    conditions qu'il a fallu satisfaire, et c'est la règle qui les
    déclare."""
    total = 0
    if rule.match_on_amount:
        total += CONFIDENCE_BY_CRITERION["amount"]
    if rule.match_on_reference:
        total += CONFIDENCE_BY_CRITERION["reference"]
    if rule.match_on_partner:
        total += CONFIDENCE_BY_CRITERION["partner"]
    return total


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

    # **Calculé UNE fois, hors de la boucle.** La version précédente
    # rappelait `_candidate_move_lines` pour chaque ligne de relevé : le
    # coût du rapprochement croissait donc comme le produit du nombre de
    # lignes par la taille du grand livre du compte — sur un relevé
    # mensuel de plusieurs centaines de lignes, c'est la différence entre
    # une seconde et une minute. Même défaut que l'import de tiers, corrigé
    # au lot T3 et retrouvé ici.
    #
    # Les candidats retenus sont retirés au fil de l'eau plutôt que relus :
    # deux lignes de relevé ne doivent jamais réserver la même écriture,
    # ce que la requête assurait en repartant de la base à chaque tour.
    candidates = _candidate_move_lines(bank_account)
    maintenant = timezone.now()

    for statement_line in unmatched_lines:
        for rule in rules:
            filtered = candidates
            if rule.match_on_amount:
                filtered = [c for c in filtered if _amount_matches(c, statement_line, rule)]
            if rule.match_on_reference:
                filtered = [c for c in filtered if _reference_matches(c, statement_line)]
            if rule.match_on_partner:
                filtered = [c for c in filtered if _partner_matches(c, statement_line)]

            if len(filtered) == 1:
                retenue = filtered[0]
                statement_line.matched_move_line = retenue
                statement_line.state = AccBankStatementLine.STATE_RULE_SUGGESTED
                # BNK-3 : les deux mots du critère, plus la règle qui a
                # proposé — sans elle, une proposition douteuse ne désigne
                # pas ce qu'il faut corriger.
                statement_line.suggested_at = maintenant
                statement_line.match_confidence = _confidence_of(rule)
                statement_line.matched_by_rule = rule
                statement_line.save(
                    update_fields=[
                        "matched_move_line",
                        "state",
                        "suggested_at",
                        "match_confidence",
                        "matched_by_rule",
                    ]
                )
                candidates = [c for c in candidates if c.id != retenue.id]
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
    "CONFIDENCE_BY_CRITERION",
    "RejectedLine",
    "StatementImportReport",
    "import_bank_statement",
    "suggest_matches",
    "confirm_reconciliation",
    "manual_match",
    "unmatched_or_suggested_lines",
]
