"""Rapports de base de la phase 1 (ACC-BAL, ACC-GL, ACC-JRN, ACC-FAC), et
depuis l'etape A9 de la phase 2, les 5 etats financiers de base (ACC-BIL,
ACC-CR, ACC-CR-FCT, ACC-CF, ACC-VCP) et les balances agees (ACC-AGE-C,
ACC-AGE-F). Declaration TVA, analytique et previsionnel de tresorerie
restent a des etapes ulterieures de la phase 2 (cf. plan).

Reserve OECFM (meme discipline que `chart_of_accounts.py`) : les fonctions
ci-dessous appliquent la structure du bilan/compte de resultat/flux de
tresorerie/variation des capitaux propres telle que reconstruite dans le
document annexe « Rapports_Financiers_Fiscaux_et_Bancaires_Madagascar.pdf »
(§1.10.1 a §1.10.4, PCG 2005 Art. 131-3 a 141), document explicitement non
valide par un expert-comptable OECFM (son §0.3/§3.5). A confirmer aupres
d'un cabinet OECFM avant tout usage en production reelle."""

from __future__ import annotations

import csv
import datetime as dt
import io
from decimal import Decimal
from typing import Any

from django.db.models import Sum

from apps.accounting.models import (
    AccAccount,
    AccAnalyticLine,
    AccAnalyticPlan,
    AccAsset,
    AccAssetDepreciation,
    AccAssetMovement,
    AccDcomDeclaration,
    AccFiscalYear,
    AccJournal,
    AccMove,
    AccMoveLine,
    AccProvision,
)
from apps.accounting.services.framework import framework_for_tenant
from apps.core.models.tenant import Tenant


def rows_to_bytes(rows: list[dict[str, Any]], fields: list[str], *, format: str = "json") -> bytes:
    if format == "json":
        import json

        return json.dumps(rows, indent=2, ensure_ascii=False, default=str).encode("utf-8")

    if format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        return buffer.getvalue().encode("utf-8")

    if format == "xlsx":
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(fields)
        for row in rows:
            sheet.append([row.get(field) for field in fields])
        buffer_bytes = io.BytesIO()
        workbook.save(buffer_bytes)
        return buffer_bytes.getvalue()

    raise ValueError(f"Format de rapport non supporte : {format}")


def trial_balance(fiscal_year: AccFiscalYear) -> list[dict[str, Any]]:
    """ACC-BAL — balance generale : pour chaque compte mouvemente, total
    debit/credit et solde, toutes ecritures publiees de l'exercice."""
    lines = AccMoveLine.objects.filter(
        move__period__fiscal_year=fiscal_year, move__state=AccMove.STATE_POSTED
    )
    totals = (
        lines.values("account__code", "account__name")
        .annotate(total_debit=Sum("debit"), total_credit=Sum("credit"))
        .order_by("account__code")
    )
    rows = []
    for entry in totals:
        debit = entry["total_debit"] or Decimal(0)
        credit = entry["total_credit"] or Decimal(0)
        rows.append(
            {
                "code": entry["account__code"],
                "name": entry["account__name"],
                "debit": debit,
                "credit": credit,
                "balance": debit - credit,
            }
        )
    return rows


def general_ledger(account: AccAccount, fiscal_year: AccFiscalYear) -> list[dict[str, Any]]:
    """ACC-GL — grand livre d'un compte : le detail des lignes publiees,
    par ordre chronologique."""
    lines = (
        AccMoveLine.objects.filter(
            account=account,
            move__period__fiscal_year=fiscal_year,
            move__state=AccMove.STATE_POSTED,
        )
        .select_related("move")
        .order_by("move__date", "move__reference")
    )
    return [
        {
            "date": line.move.date,
            "reference": line.move.reference,
            "label": line.label,
            "debit": line.debit,
            "credit": line.credit,
        }
        for line in lines
    ]


def journal_report(journal: AccJournal, fiscal_year: AccFiscalYear) -> list[dict[str, Any]]:
    """ACC-JRN — journal : toutes les ecritures publiees d'un journal,
    dans l'ordre de leur numerotation."""
    moves = AccMove.objects.filter(
        journal=journal, period__fiscal_year=fiscal_year, state=AccMove.STATE_POSTED
    ).order_by("reference")
    rows = []
    for move in moves:
        for line in move.lines.all():
            rows.append(
                {
                    "reference": move.reference,
                    "date": move.date,
                    "account": line.account.code,
                    "label": line.label,
                    "debit": line.debit,
                    "credit": line.credit,
                }
            )
    return rows


# RG-ACC (presentation) : tolerance d'arrondi Decimal, meme convention que
# `sales.services.invoicing._FULLY_INVOICED_TOLERANCE_MGA`.
_BALANCE_TOLERANCE_MGA = Decimal("0.01")


# ACC-BIL (§1.10.1 du document annexe) : ordre de presentation a l'actif et
# au passif, par type de compte, a l'interieur de chaque bloc courant/non
# courant. Approximation assumee : le CDC ne distingue les types de compte
# qu'a une granularite large (`AccAccount.type`), pas au niveau
# immobilisations-incorporelles/corporelles/financieres ni
# fournisseurs/autres-dettes — la sous-distinction fine du §1.10.1 n'est
# donc pas reconstructible sans un champ supplementaire ; on ordonne au
# niveau de granularite disponible.
def _statement_order(framework: Any, side: str) -> dict[str, int]:
    """Ordre de presentation d'un cote du bilan, par type de compte.

    D10-3 : lu dans le referentiel (`statement_structure["balance_sheet_order"]`)
    plutot que fige dans deux dictionnaires de module. Un referentiel sans
    ordre declare produit un regroupement stable mais non ordonne — c'est un
    cas de configuration incomplete, pas une structure PCG de repli."""
    if framework is None:
        return {}
    order: dict[str, dict[str, int]] = framework.statement_structure.get("balance_sheet_order", {})
    return order.get(side, {})


def balance_sheet(fiscal_year: AccFiscalYear, *, as_of_date: Any = None) -> dict[str, Any]:
    """ACC-BIL — bilan (§1.10.1 du document annexe, Art. 220-1 et 220-2).

    Agrege le solde CUMULE (depuis l'origine, pas seulement l'exercice
    `fiscal_year`) de chaque `AccAccount` mouvemente par une ecriture
    publiee dont la date est <= `as_of_date` (par defaut la date de fin de
    `fiscal_year`) — un bilan est un etat de situation a une date donnee,
    par construction cumulatif sur toute l'histoire du tenant, contrairement
    au compte de resultat qui est borne a l'exercice.

    Ventilation actif/passif par `AccAccount.type`, puis par
    `AccAccount.is_current` (§1.10.1, Art. 131-3 a 131-11) : comptes `tax` a
    solde debiteur => actif (actifs d'impot), a solde crediteur => passif
    (passifs d'impot) — seul type ambigu du plan comptable, tranche au cas
    par cas ligne par ligne plutot que par le type seul.

    `"balanced"` est un simple indicateur informatif (tolerance Decimal
    `_BALANCE_TOLERANCE_MGA`, meme convention que
    `sales.services.invoicing`) : un desequilibre reel serait deja empeche
    par RG-ACC-1 (`post_move` refuse toute ecriture debit != credit) — ce
    drapeau signale une anomalie de PRESENTATION (ex. compte mal type), pas
    une nouvelle invariance a faire respecter ici."""
    cutoff = as_of_date or fiscal_year.date_end
    entries = (
        AccMoveLine.objects.filter(move__state=AccMove.STATE_POSTED, move__date__lte=cutoff)
        .values("account__code", "account__name", "account__type", "account__is_current")
        .annotate(total_debit=Sum("debit"), total_credit=Sum("credit"))
        .order_by("account__code")
    )

    actif_courant: list[dict[str, Any]] = []
    actif_non_courant: list[dict[str, Any]] = []
    passif_courant: list[dict[str, Any]] = []
    passif_non_courant: list[dict[str, Any]] = []
    total_actif = Decimal(0)
    total_passif = Decimal(0)

    for entry in entries:
        debit = entry["total_debit"] or Decimal(0)
        credit = entry["total_credit"] or Decimal(0)
        balance = debit - credit
        if balance == 0:
            continue
        account_type = entry["account__type"]
        is_current = entry["account__is_current"]
        row: dict[str, Any] = {
            "code": entry["account__code"],
            "name": entry["account__name"],
            "_type": account_type,
        }

        if account_type == AccAccount.TYPE_TAX:
            if balance > 0:
                row["amount"] = balance
                total_actif += balance
                (actif_courant if is_current else actif_non_courant).append(row)
            else:
                row["amount"] = -balance
                total_passif += -balance
                (passif_courant if is_current else passif_non_courant).append(row)
        elif account_type in (
            AccAccount.TYPE_ASSET,
            AccAccount.TYPE_RECEIVABLE,
            AccAccount.TYPE_BANK,
            AccAccount.TYPE_CASH,
            AccAccount.TYPE_STOCK,
        ):
            row["amount"] = balance
            total_actif += balance
            (actif_courant if is_current else actif_non_courant).append(row)
        elif account_type in (
            AccAccount.TYPE_LIABILITY,
            AccAccount.TYPE_PAYABLE,
            AccAccount.TYPE_EQUITY,
        ):
            row["amount"] = -balance
            total_passif += -balance
            (passif_courant if is_current else passif_non_courant).append(row)
        else:
            # Comptes de produits/charges (income/expense) : leur solde net
            # de l'exercice remonte au bilan via le compte 120 "Resultat de
            # l'exercice" (deja code en type `equity` dans la fixture
            # PCG2005) une fois l'ecriture d'affectation du resultat passee
            # — ils ne sont donc jamais presentes directement au bilan ici.
            continue

    framework = framework_for_tenant(fiscal_year.tenant)
    asset_order = _statement_order(framework, "asset")
    liability_order = _statement_order(framework, "liability")
    for bucket, order_map in (
        (actif_courant, asset_order),
        (actif_non_courant, asset_order),
        (passif_courant, liability_order),
        (passif_non_courant, liability_order),
    ):
        bucket.sort(key=lambda r: (order_map.get(r["_type"], 99), r["code"]))
        for row in bucket:
            del row["_type"]

    balanced = abs(total_actif - total_passif) <= _BALANCE_TOLERANCE_MGA

    return {
        "as_of_date": cutoff,
        "actif": {"courant": actif_courant, "non_courant": actif_non_courant, "total": total_actif},
        "passif": {
            "courant": passif_courant,
            "non_courant": passif_non_courant,
            "total": total_passif,
        },
        "balanced": balanced,
    }


def _account_balances(fiscal_year: AccFiscalYear) -> dict[str, tuple[Decimal, Decimal]]:
    """Solde debit/credit cumule par code de compte, toutes ecritures
    publiees de l'exercice — brique commune a `income_statement` et
    `income_statement_by_function` (memes ecritures source, §1.10.2)."""
    entries = (
        AccMoveLine.objects.filter(
            move__period__fiscal_year=fiscal_year, move__state=AccMove.STATE_POSTED
        )
        .values("account__code")
        .annotate(total_debit=Sum("debit"), total_credit=Sum("credit"))
    )
    return {
        entry["account__code"]: (
            entry["total_debit"] or Decimal(0),
            entry["total_credit"] or Decimal(0),
        )
        for entry in entries
    }


def _sum_natural(
    balances: dict[str, tuple[Decimal, Decimal]], prefixes: tuple[str, ...], natural: str
) -> Decimal:
    total = Decimal(0)
    for code, (debit, credit) in balances.items():
        if code.startswith(prefixes):
            total += (credit - debit) if natural == "credit" else (debit - credit)
    return total


def _poste_amount(balances: dict[str, tuple[Decimal, Decimal]], entry: dict[str, Any]) -> Decimal:
    natural = entry["natural"]
    opposite = "debit" if natural == "credit" else "credit"
    # `tuple(...)` obligatoire : depuis D10-3 les prefixes viennent du JSON du
    # referentiel, donc sous forme de liste, et `str.startswith` n'accepte
    # qu'une chaine ou un tuple de chaines.
    return _sum_natural(balances, tuple(entry.get("additive", ())), natural) - _sum_natural(
        balances, tuple(entry.get("subtractive", ())), opposite
    )


def income_statement(fiscal_year: AccFiscalYear) -> list[dict[str, Any]]:
    """ACC-CR — compte de resultat par nature, presentation « en liste » avec
    soldes intermediaires en cascade.

    D10-3 : la structure n'est plus ecrite en Python. Elle est lue dans
    `AccFramework.statement_structure["lines"]` du referentiel actif du tenant
    (cahier §13.3 : « les etats financiers sont produits selon la structure du
    referentiel actif du tenant, jamais selon une structure codee en dur »).

    Trois natures de ligne, evaluees dans l'ordre de la liste :

    - `poste` : montant agrege depuis des prefixes de compte (`additive`
      moins `subtractive`, ce dernier evalue dans le sens oppose de
      `natural`) — c'est l'ancien `_CR_NATURE_MAPPING` ;
    - `total` : solde intermediaire, somme des lignes `add` moins les lignes
      `sub`, toutes deja resolues plus haut — c'est l'ancienne cascade I a IX ;
    - `constant` : valeur fixe, pour une ligne que le referentiel affiche sans
      lui rattacher de comptes (les elements extraordinaires du PCG 2005, dont
      l'Annexe II ne fournit aucune plage).

    Retourne une liste vide si le tenant n'a pas de referentiel resolu : meme
    discipline que le reste de cette surface, aucune exception pour une
    configuration absente."""
    framework = framework_for_tenant(fiscal_year.tenant)
    lines: list[dict[str, Any]] = []
    if framework is not None:
        lines = framework.statement_structure.get("lines", [])
    if not lines:
        return []

    balances = _account_balances(fiscal_year)
    computed: dict[str, Decimal] = {}
    rows: list[dict[str, Any]] = []
    for line in lines:
        kind = line.get("kind")
        if kind == "poste":
            amount = _poste_amount(balances, line)
        elif kind == "total":
            amount = sum(
                (computed.get(key, Decimal(0)) for key in line.get("add", [])), Decimal(0)
            ) - sum((computed.get(key, Decimal(0)) for key in line.get("sub", [])), Decimal(0))
        else:
            amount = Decimal(str(line.get("value", "0")))
        computed[line["key"]] = amount
        rows.append({"poste": line.get("roman", ""), "label": line["label"], "amount": amount})
    return rows


def income_statement_by_function(fiscal_year: AccFiscalYear) -> list[dict[str, Any]]:
    """ACC-CR-FCT — compte de resultat par fonction (ACC-CR-FN1, §1.10.2 du
    document annexe) : reclasse les MEMES ecritures que `income_statement`
    (classes 6 = charges), via `AccAccount.functional_destination`, plutot
    que de les reclasser par nature — pas de double saisie.

    Simplification V1 assumee (le document le permet implicitement, §1.10.2
    ne detaille pas un sous-cascade par fonction) : pas de cascade
    intermediaire (cout des ventes / frais commerciaux / frais
    administratifs a plusieurs sous-lignes) — un total de charges par
    destination (production/distribution/administration/autre), plus les
    produits (classe 7, inchanges par rapport a la nature) et le resultat
    net, qui doit necessairement egaler celui d'`income_statement` (memes
    ecritures, seule la ventilation des charges differe)."""
    # D10-4 : les classes de charge et de produit viennent du referentiel
    # actif du tenant, plus des litteraux 6 et 7 (qui sont la forme PCG 2005).
    framework = framework_for_tenant(fiscal_year.tenant)
    expense_class = framework.expense_class if framework else None
    income_class = framework.income_class if framework else None
    if expense_class is None or income_class is None:
        return []

    charge_entries = (
        AccMoveLine.objects.filter(
            move__period__fiscal_year=fiscal_year,
            move__state=AccMove.STATE_POSTED,
            account__account_class=expense_class,
        )
        .values("account__functional_destination")
        .annotate(total_debit=Sum("debit"), total_credit=Sum("credit"))
    )
    totals_by_destination: dict[str, Decimal] = {
        AccAccount.FUNCTIONAL_PRODUCTION: Decimal(0),
        AccAccount.FUNCTIONAL_DISTRIBUTION: Decimal(0),
        AccAccount.FUNCTIONAL_ADMINISTRATION: Decimal(0),
        AccAccount.FUNCTIONAL_AUTRE: Decimal(0),
    }
    for entry in charge_entries:
        destination = entry["account__functional_destination"] or AccAccount.FUNCTIONAL_AUTRE
        debit = entry["total_debit"] or Decimal(0)
        credit = entry["total_credit"] or Decimal(0)
        totals_by_destination[destination] += debit - credit

    total_charges = sum(totals_by_destination.values(), Decimal(0))

    revenue_entries = AccMoveLine.objects.filter(
        move__period__fiscal_year=fiscal_year,
        move__state=AccMove.STATE_POSTED,
        account__account_class=income_class,
    ).aggregate(total_debit=Sum("debit"), total_credit=Sum("credit"))
    total_produits = (revenue_entries["total_credit"] or Decimal(0)) - (
        revenue_entries["total_debit"] or Decimal(0)
    )

    resultat_net = total_produits - total_charges

    return [
        {"label": "Produits", "amount": total_produits},
        {
            "label": "Charges de production",
            "amount": totals_by_destination[AccAccount.FUNCTIONAL_PRODUCTION],
        },
        {
            "label": "Charges de distribution",
            "amount": totals_by_destination[AccAccount.FUNCTIONAL_DISTRIBUTION],
        },
        {
            "label": "Charges d'administration",
            "amount": totals_by_destination[AccAccount.FUNCTIONAL_ADMINISTRATION],
        },
        {"label": "Autres charges", "amount": totals_by_destination[AccAccount.FUNCTIONAL_AUTRE]},
        {"label": "RESULTAT NET DE L'EXERCICE", "amount": resultat_net},
    ]


def _cash_flow_section(account: AccAccount, investing_class: int | None) -> str:
    """ACC-CF (§1.10.3 du document annexe) : classification "methode
    directe" d'une ligne de contrepartie de mouvement de tresorerie —
    choix de methode documente sur `cash_flow_statement`.

    D10-4 : `investing_class` vient du referentiel actif
    (`AccFramework.investing_class`), plus du litteral 2 qui etait la forme
    PCG 2005 des comptes d'immobilisation."""
    if investing_class is not None and account.account_class == investing_class:
        return "investing"
    if account.type in (AccAccount.TYPE_EQUITY, AccAccount.TYPE_LIABILITY):
        return "financing"
    return "operating"


def cash_flow_statement(fiscal_year: AccFiscalYear) -> dict[str, Any]:
    """ACC-CF — tableau des flux de tresorerie (§1.10.3 du document annexe,
    Art. 141, Titre XII.33-34), trois sections (operationnel/investissement/
    financement).

    Choix de methode assume (methode DIRECTE, pas indirecte) : le document
    annexe exige seulement "presente les entrees et sorties de tresorerie...
    structurees en trois sections", sans imposer la reconciliation a partir
    du resultat net (methode indirecte classique) — la methode indirecte
    demanderait de suivre la variation du besoin en fonds de roulement, non
    encore modelisee a cette etape (A9). La methode directe est ici
    entierement derivable de l'existant : chaque ecriture publiee touchant
    un compte caisse/banque (`AccAccount.TYPE_CASH`/`TYPE_BANK`, memes
    comptes qu'`cash_basis_report`, A8) est classee par la NATURE de son
    (des) compte(s) de contrepartie dans la meme ecriture — immobilisation
    (classe PCG 2) => investissement, capitaux propres/passif financier =>
    financement, tout le reste (produit/charge/creance/dette/taxe/stock) =>
    operationnel. Le montant impute a chaque ligne de contrepartie est son
    solde credit-debit PROPRE (et non le solde de la ligne caisse) : une
    ecriture equilibree garantit que la somme des soldes credit-debit de
    toutes les lignes de contrepartie egale exactement la variation de
    tresorerie de l'ecriture, ce qui permet d'imputer chaque contrepartie a
    sa section sans ambiguite meme si une ecriture a plusieurs
    contreparties."""
    framework = framework_for_tenant(fiscal_year.tenant)
    investing_class = framework.investing_class if framework else None

    sections: dict[str, Decimal] = {
        "operating": Decimal(0),
        "investing": Decimal(0),
        "financing": Decimal(0),
    }
    detail_rows: list[dict[str, Any]] = []

    moves = AccMove.objects.filter(
        period__fiscal_year=fiscal_year, state=AccMove.STATE_POSTED
    ).prefetch_related("lines__account")

    for move in moves:
        all_lines = list(move.lines.all())
        has_cash_line = any(
            line.account.type in (AccAccount.TYPE_CASH, AccAccount.TYPE_BANK) for line in all_lines
        )
        if not has_cash_line:
            continue
        for line in all_lines:
            if line.account.type in (AccAccount.TYPE_CASH, AccAccount.TYPE_BANK):
                continue
            amount = line.credit - line.debit
            if amount == 0:
                continue
            section = _cash_flow_section(line.account, investing_class)
            sections[section] += amount
            detail_rows.append(
                {
                    "date": move.date,
                    "reference": move.reference,
                    "section": section,
                    "account": line.account.code,
                    "label": line.label,
                    "amount": amount,
                }
            )

    net_change_in_cash = sections["operating"] + sections["investing"] + sections["financing"]

    return {
        "operating": sections["operating"],
        "investing": sections["investing"],
        "financing": sections["financing"],
        "net_change_in_cash": net_change_in_cash,
        "lines": detail_rows,
    }


def equity_variation_statement(fiscal_year: AccFiscalYear) -> list[dict[str, Any]]:
    """ACC-VCP — etat de variation des capitaux propres (§1.10.4 du document
    annexe, Titre XII.35-36), un ouverture/mouvements/cloture PAR compte de
    type `equity`.

    Simplification V1 assumee (explicitement hors perimetre A9, cf. plan) :
    pas de sous-classification des mouvements de l'exercice en
    resultat/changements de methode/corrections d'erreurs/operations en
    capital — ces sous-categories demanderaient un marquage de chaque
    ecriture non encore modelise. Un simple "mouvements de l'exercice"
    agrege honore l'identite ouverture + mouvements = cloture, sans
    pretendre au detail complet exige par le §1.10.4 tel quel.

    Solde d'ouverture = solde CUMULE (toutes ecritures publiees, toute
    l'histoire) du compte a la date de fin de l'exercice fiscal PRECEDENT
    (le plus recent dont `date_end < fiscal_year.date_start`). Si aucun
    exercice anterieur n'existe (premier exercice du tenant), ouverture =
    0 — cas limite documente explicitement, pas une erreur."""
    accounts = AccAccount.objects.filter(type=AccAccount.TYPE_EQUITY).order_by("code")
    prior_fiscal_year = (
        AccFiscalYear.objects.filter(date_end__lt=fiscal_year.date_start)
        .order_by("-date_end")
        .first()
    )

    rows: list[dict[str, Any]] = []
    for account in accounts:
        if prior_fiscal_year is not None:
            prior_totals = AccMoveLine.objects.filter(
                account=account,
                move__state=AccMove.STATE_POSTED,
                move__date__lte=prior_fiscal_year.date_end,
            ).aggregate(debit=Sum("debit"), credit=Sum("credit"))
            opening = (prior_totals["credit"] or Decimal(0)) - (prior_totals["debit"] or Decimal(0))
        else:
            opening = Decimal(0)

        movement_totals = AccMoveLine.objects.filter(
            account=account,
            move__state=AccMove.STATE_POSTED,
            move__period__fiscal_year=fiscal_year,
        ).aggregate(debit=Sum("debit"), credit=Sum("credit"))
        movement = (movement_totals["credit"] or Decimal(0)) - (
            movement_totals["debit"] or Decimal(0)
        )

        rows.append(
            {
                "code": account.code,
                "name": account.name,
                "opening": opening,
                "movement": movement,
                "closing": opening + movement,
            }
        )
    return rows


# ACC-ANNEXE1 (§1.11 du document annexe) reutilisera les memes tranches —
# constantes exposees ici (pas privees) pour cette reutilisation future.
AGE_BUCKET_LESS_THAN_1_YEAR = "moins_d_un_an"
AGE_BUCKET_1_TO_5_YEARS = "un_a_cinq_ans"
AGE_BUCKET_MORE_THAN_5_YEARS = "plus_de_cinq_ans"
_AGE_BUCKETS = (AGE_BUCKET_LESS_THAN_1_YEAR, AGE_BUCKET_1_TO_5_YEARS, AGE_BUCKET_MORE_THAN_5_YEARS)


def _age_bucket(due_date: Any, as_of_date: Any) -> str:
    if due_date is None:
        # Pas d'echeance renseignee : traite comme "moins d'un an" plutot
        # que rejete — simplification documentee, coherente avec le fait
        # qu'une ligne sans echeance ne doit pas disparaitre du rapport.
        return AGE_BUCKET_LESS_THAN_1_YEAR
    age_days = (as_of_date - due_date).days
    if age_days < 365:
        return AGE_BUCKET_LESS_THAN_1_YEAR
    if age_days < 5 * 365:
        return AGE_BUCKET_1_TO_5_YEARS
    return AGE_BUCKET_MORE_THAN_5_YEARS


def _aged_balance(account_type: str, as_of_date: Any) -> list[dict[str, Any]]:
    cutoff = as_of_date or dt.date.today()
    lines = (
        AccMoveLine.objects.filter(account__type=account_type, move__state=AccMove.STATE_POSTED)
        # "ouvert" = pas encore lettre (RG-ACC-8, cf. services/payments.py) :
        # `matching_number` reste vide tant que la ligne n'est pas soldee.
        .filter(matching_number="")
        .select_related("account")
    )

    grouped: dict[Any, dict[str, Any]] = {}
    for line in lines:
        bucket = _age_bucket(line.due_date, cutoff)
        balance = (
            line.debit - line.credit
            if account_type == AccAccount.TYPE_RECEIVABLE
            else line.credit - line.debit
        )
        entry = grouped.setdefault(
            line.partner_id,
            {"partner_id": line.partner_id, **{b: Decimal(0) for b in _AGE_BUCKETS}},
        )
        entry[bucket] += balance

    rows = []
    for entry in grouped.values():
        entry["total"] = sum((entry[b] for b in _AGE_BUCKETS), Decimal(0))
        rows.append(entry)
    return rows


def aged_receivables(as_of_date: Any = None) -> list[dict[str, Any]]:
    """ACC-AGE-C — balance agee clients : lignes `receivable` non lettrees,
    par tiers, ventilees par tranche d'echeance vs `due_date` (memes bornes
    que l'annexe "etat des creances et dettes" du §1.11 du document annexe,
    reutilisees ici bien qu'ACC-ANNEXE1 lui-meme reste hors perimetre A9)."""
    return _aged_balance(AccAccount.TYPE_RECEIVABLE, as_of_date)


def aged_payables(as_of_date: Any = None) -> list[dict[str, Any]]:
    """ACC-AGE-F — balance agee fournisseurs : lignes `payable` non
    lettrees, par tiers, memes tranches qu'`aged_receivables`."""
    return _aged_balance(AccAccount.TYPE_PAYABLE, as_of_date)


def list_open_settlement_items(
    *, as_of_date: Any = None, horizon_days: int = 91
) -> list[dict[str, Any]]:
    """Lignes `receivable`/`payable` OUVERTES (memes criteres qu'`aged_
    receivables`/`aged_payables` et que `treasury_forecast` : `matching_
    number == ""`, echeance connue) dans la fenetre `[as_of_date, as_of_date
    + horizon_days]`, au format BRUT ligne par ligne (montant + echeance),
    plutot que deja agregees par tiers (`aged_*`) ou deja decoupees en
    paniers hebdomadaires figes (`treasury_forecast`).

    Ajoute pour le module `simulation` (SIM-7 : projection de tresorerie a
    13 semaines) qui doit pouvoir DECALER l'echeance de chaque ligne selon
    un levier de delai de reglement puis re-decouper elle-meme en paniers —
    un decoupage deja fige ne permettrait pas ce recalcul local cote
    client."""
    as_of = as_of_date or dt.date.today()
    horizon_end = as_of + dt.timedelta(days=horizon_days)
    items: list[dict[str, Any]] = []
    for account_type, kind in (
        (AccAccount.TYPE_RECEIVABLE, "receivable"),
        (AccAccount.TYPE_PAYABLE, "payable"),
    ):
        lines = AccMoveLine.objects.filter(
            account__type=account_type,
            move__state=AccMove.STATE_POSTED,
            matching_number="",
            due_date__isnull=False,
            due_date__gte=as_of,
            due_date__lte=horizon_end,
        )
        for line in lines:
            amount = (
                line.debit - line.credit
                if account_type == AccAccount.TYPE_RECEIVABLE
                else line.credit - line.debit
            )
            items.append(
                {
                    "kind": kind,
                    "due_date": line.due_date,
                    "amount_mga": amount,
                    "partner_id": line.partner_id,
                }
            )
    return items


def cash_basis_report(fiscal_year: AccFiscalYear, *, mode: str = "recap") -> list[dict[str, Any]]:
    """ACC-SMT — rapport de tresorerie simplifie pour un tenant au regime
    Impot Synthetique (§1.1.1 du document annexe), derive uniquement des
    lignes d'ecriture (`AccMoveLine`) portees par un compte de type caisse
    ou banque (`AccAccount.TYPE_CASH`/`TYPE_BANK`) — aucune table source de
    verite supplementaire.

    Deux sous-formats, selon `mode` :
    - `"recap"` : "recapitulatif recettes/depenses" (sous-strate CA < 100 M
      Ar) — liste plate date/libelle/montant/sens ;
    - `"smt"` : "etat des encaissements/decaissements" (Systeme Minimal de
      Tresorerie, sous-strate 100-200 M Ar) — memes lignes, plus une colonne
      `balance` : le solde net de tresorerie cumule.

    Le choix du mode est explicitement laisse a l'appelant (parametre
    obligatoire de fait ici, defaut `"recap"`) : determiner automatiquement
    la sous-strate applicable exigerait de calculer le CA reel de
    l'exercice, ce que seul ACC-CR (compte de resultat, etape A9) permettra
    de faire correctement — cf. note de l'etape A8 du plan. Ne PAS deviner
    la strate a partir d'un autre indicateur en attendant.

    Reserve OECFM/DGI (§0.5, §3.5 du document annexe) : les seuils de CA et
    la nomenclature des sous-strates SMT/recapitulatif sont repris d'un
    document non primaire — a confirmer aupres d'un expert-comptable OECFM
    ou de la DGI avant tout usage en production reelle."""
    if mode not in ("recap", "smt"):
        raise ValueError(f"Mode de rapport ACC-SMT non supporte : {mode!r}")

    lines = (
        AccMoveLine.objects.filter(
            account__type__in=[AccAccount.TYPE_CASH, AccAccount.TYPE_BANK],
            move__period__fiscal_year=fiscal_year,
            move__state=AccMove.STATE_POSTED,
        )
        .select_related("move")
        .order_by("move__date", "move__reference")
    )

    rows: list[dict[str, Any]] = []
    running_balance = Decimal(0)
    for line in lines:
        if line.debit:
            direction = "in"
            amount = line.debit
        else:
            direction = "out"
            amount = line.credit
        row: dict[str, Any] = {
            "date": line.move.date,
            "label": line.label,
            "amount": amount,
            "direction": direction,
        }
        if mode == "smt":
            running_balance += amount if direction == "in" else -amount
            row["balance"] = running_balance
        rows.append(row)
    return rows


_ASSET_CATEGORY_LABELS: dict[str, str] = dict(AccAsset.CATEGORY_CHOICES)


def _actif_immobilise_annex(fiscal_year: AccFiscalYear) -> list[dict[str, Any]]:
    """Colonne "Valeur brute debut exercice" calculee directement depuis
    `AccAsset` (valeur d'acquisition des immobilisations deja detenues/deja
    cedees avant le debut de l'exercice), independamment des mouvements —
    plus robuste qu'une reconstruction par mouvements cumules. Les colonnes
    de MOUVEMENT DE L'EXERCICE (acquisitions/cessions/virements) sont elles
    lues depuis `AccAssetMovement` sur la fenetre `[date_start, date_end]`."""
    categories = [c for c, _label in AccAsset.CATEGORY_CHOICES]
    opening: dict[str, Decimal] = dict.fromkeys(categories, Decimal(0))
    for asset in AccAsset.objects.all():
        if asset.acquisition_date < fiscal_year.date_start:
            opening[asset.category] += asset.acquisition_value_mga
        if (
            asset.state == AccAsset.STATE_DISPOSED
            and asset.disposal_date is not None
            and asset.disposal_date < fiscal_year.date_start
        ):
            opening[asset.category] -= asset.acquisition_value_mga

    acquisitions: dict[str, Decimal] = dict.fromkeys(categories, Decimal(0))
    cessions: dict[str, Decimal] = dict.fromkeys(categories, Decimal(0))
    virements: dict[str, Decimal] = dict.fromkeys(categories, Decimal(0))

    movements = AccAssetMovement.objects.filter(
        date__gte=fiscal_year.date_start, date__lte=fiscal_year.date_end
    ).select_related("asset")
    for movement in movements:
        category = movement.asset.category
        if movement.movement_type == AccAssetMovement.MOVEMENT_ACQUISITION:
            # Par construction (`services/assets.py::register_asset`), le
            # montant du mouvement d'acquisition EGALE la valeur brute de
            # l'actif — utilise directement plutot que re-derive.
            acquisitions[category] += movement.asset.acquisition_value_mga
        elif movement.movement_type == AccAssetMovement.MOVEMENT_DISPOSAL:
            # Choix documente : la colonne "cessions" de cette annexe est la
            # VALEUR BRUTE (cout d'acquisition) qui sort du suivi de l'actif
            # immobilise — PAS le prix de cession (`movement.amount_mga`,
            # qui porte `disposal_value_mga`, une donnee de plus-value/
            # moins-value hors perimetre de cette annexe).
            cessions[category] += movement.asset.acquisition_value_mga
        elif movement.movement_type == AccAssetMovement.MOVEMENT_TRANSFER:
            # Simplification V1 assumee : un virement de poste a poste est
            # ici algebrique (`amount_mga` tel que saisi), agrege par
            # categorie de l'actif transfere — `AccAsset.category` etant
            # fixe par actif (pas reaffecte par le virement lui-meme en
            # V1), cette colonne reste indicative plutot qu'une reconciliation
            # stricte entre 2 categories distinctes.
            virements[category] += movement.amount_mga

    rows = []
    for category in categories:
        valeur_brute_debut = opening[category]
        valeur_brute_fin = (
            valeur_brute_debut + acquisitions[category] - cessions[category] + virements[category]
        )
        rows.append(
            {
                "categorie": category,
                "categorie_label": _ASSET_CATEGORY_LABELS[category],
                "valeur_brute_debut_exercice": valeur_brute_debut,
                "acquisitions": acquisitions[category],
                "cessions_mises_au_rebut": cessions[category],
                "virements_de_poste_a_poste": virements[category],
                "valeur_brute_fin_exercice": valeur_brute_fin,
            }
        )
    return rows


def _amortissements_annex(
    fiscal_year: AccFiscalYear, valeur_brute_fin: dict[str, Decimal]
) -> list[dict[str, Any]]:
    """`valeur_brute_fin` : valeur brute fin d'exercice par categorie, deja
    calculee par `_actif_immobilise_annex`, reutilisee ici pour deriver la
    "Valeur nette comptable" (= valeur brute fin exercice - cumul fin
    exercice) sans recalcul — annexes coherentes par construction entre
    elles, comme l'exige le document annexe (§1.11)."""
    categories = [c for c, _label in AccAsset.CATEGORY_CHOICES]
    cumul_debut: dict[str, Decimal] = dict.fromkeys(categories, Decimal(0))
    dotations: dict[str, Decimal] = dict.fromkeys(categories, Decimal(0))
    sorties: dict[str, Decimal] = dict.fromkeys(categories, Decimal(0))

    entries = AccAssetDepreciation.objects.filter(fiscal_year=fiscal_year).select_related("asset")
    for entry in entries:
        category = entry.asset.category
        cumul_debut[category] += entry.opening_accumulated_mga
        dotations[category] += entry.annual_dotation_mga
        # "Amortissements sur sorties" : l'amortissement cumule (jusqu'a la
        # cession, incluse) d'un actif cede DURANT cet exercice est retire du
        # cumul — n'a de sens que si l'actif a effectivement ete cede sur
        # cet exercice precis (pas seulement "est disposed" aujourd'hui).
        asset = entry.asset
        if (
            asset.state == AccAsset.STATE_DISPOSED
            and asset.disposal_date is not None
            and fiscal_year.date_start <= asset.disposal_date <= fiscal_year.date_end
        ):
            sorties[category] += entry.closing_accumulated_mga

    rows = []
    for category in categories:
        cumul_fin = cumul_debut[category] + dotations[category] - sorties[category]
        rows.append(
            {
                "categorie": category,
                "categorie_label": _ASSET_CATEGORY_LABELS[category],
                "cumul_debut_exercice": cumul_debut[category],
                "dotations_de_l_exercice": dotations[category],
                "amortissements_sur_sorties": sorties[category],
                "cumul_fin_exercice": cumul_fin,
                "valeur_nette_comptable": valeur_brute_fin.get(category, Decimal(0)) - cumul_fin,
            }
        )
    return rows


def _provisions_annex(fiscal_year: AccFiscalYear) -> list[dict[str, Any]]:
    provisions = AccProvision.objects.filter(fiscal_year=fiscal_year).order_by("nature")
    grouped: dict[str, dict[str, Any]] = {}
    for provision in provisions:
        entry = grouped.setdefault(
            provision.nature,
            {
                "nature": provision.nature,
                "montant_debut_exercice": Decimal(0),
                "dotations": Decimal(0),
                "reprises": Decimal(0),
                "montant_fin_exercice": Decimal(0),
            },
        )
        entry["montant_debut_exercice"] += provision.opening_amount_mga
        entry["dotations"] += provision.dotation_mga
        entry["reprises"] += provision.reprise_mga
        entry["montant_fin_exercice"] += provision.closing_amount_mga
    return list(grouped.values())


def _creances_dettes_annex(fiscal_year: AccFiscalYear) -> list[dict[str, Any]]:
    """Reutilise `aged_receivables`/`aged_payables` (A9) VERBATIM — memes
    tranches d'echeance, aucune reimplementation de la logique de bucket.
    `as_of_date` = fin d'exercice (coherent avec `balance_sheet`, un etat de
    situation a une date donnee). "autre" (troisieme nature de la colonne du
    document annexe, §1.11) reste a 0 : aucune entite `AccMoveLine` de type
    ni creance ni dette n'est actuellement rattachee a une echeance dans le
    modele existant — case documentee plutot que devinee."""
    cutoff = fiscal_year.date_end
    receivable_rows = aged_receivables(as_of_date=cutoff)
    payable_rows = aged_payables(as_of_date=cutoff)

    def _totals(rows: list[dict[str, Any]]) -> dict[str, Decimal]:
        totals = {b: Decimal(0) for b in _AGE_BUCKETS}
        for row in rows:
            for bucket in _AGE_BUCKETS:
                totals[bucket] += row[bucket]
        return totals

    client_totals = _totals(receivable_rows)
    fournisseur_totals = _totals(payable_rows)

    def _row(nature: str, totals: dict[str, Decimal]) -> dict[str, Any]:
        return {
            "nature": nature,
            AGE_BUCKET_LESS_THAN_1_YEAR: totals[AGE_BUCKET_LESS_THAN_1_YEAR],
            AGE_BUCKET_1_TO_5_YEARS: totals[AGE_BUCKET_1_TO_5_YEARS],
            AGE_BUCKET_MORE_THAN_5_YEARS: totals[AGE_BUCKET_MORE_THAN_5_YEARS],
            "total": sum(totals.values(), Decimal(0)),
        }

    return [
        _row("client", client_totals),
        _row("fournisseur", fournisseur_totals),
        _row("autre", {b: Decimal(0) for b in _AGE_BUCKETS}),
    ]


def fixed_asset_annexes(fiscal_year: AccFiscalYear) -> dict[str, list[dict[str, Any]]]:
    """ACC-ANNEXE1 (§1.11 du document annexe) : assemblage automatique des 4
    annexes fiscales obligatoires accompagnant le bilan/compte de resultat au
    regime reel. Structure de colonnes TRANSCRITE VERBATIM depuis le tableau
    du §1.11 ("Annexe | Structure de colonnes recommandee | Entite ERP
    correspondante") :

    - "actif_immobilise" : Categorie d'immobilisation | Valeur brute debut
      exercice | Acquisitions | Cessions/mises au rebut | Virements de poste
      a poste | Valeur brute fin exercice.
    - "amortissements" : Categorie d'immobilisation | Cumul debut exercice |
      Dotations de l'exercice | Amortissements sur sorties | Cumul fin
      exercice | Valeur nette comptable.
    - "provisions" : Nature de la provision | Montant debut exercice |
      Dotations | Reprises | Montant fin exercice.
    - "creances_dettes" : Nature (client/fournisseur/autre) | Moins d'un an |
      Un a cinq ans | Plus de cinq ans | Total.

    Reserve OECFM explicite (§3.5 du document annexe, rappelee comme pour
    `balance_sheet`/`income_statement` a l'etape A9) : ces 4 structures de
    colonnes ne sont PAS retrouvees littéralement dans un formulaire officiel
    numerote malgache (contrairement aux liasses fiscales francaises
    2054-2059 ou aux canevas SYSCOHADA) — reconstruites par analogie
    fonctionnelle avec l'article XII.13 du PCG 2005 (§III.13 du Guide
    annote), identiques dans tous les referentiels derives des normes
    IAS/IFRS selon le document source lui-meme. A confirmer aupres d'un
    cabinet OECFM ou de la DGI avant tout usage en production reelle, jamais
    a presenter comme un formulaire officiel definitif tel quel.

    Coherence par construction (comme l'exige le §1.11) : "actif_immobilise"
    et "amortissements" partagent les memes `AccAsset`/`AccAssetMovement`/
    `AccAssetDepreciation` que le bilan (compte de classe 2, cf.
    `balance_sheet`) ; "creances_dettes" reutilise EXACTEMENT
    `aged_receivables`/`aged_payables` (A9), memes tranches, aucune
    reimplementation."""
    actif_immobilise = _actif_immobilise_annex(fiscal_year)
    valeur_brute_fin = {
        row["categorie"]: row["valeur_brute_fin_exercice"] for row in actif_immobilise
    }
    return {
        "actif_immobilise": actif_immobilise,
        "amortissements": _amortissements_annex(fiscal_year, valeur_brute_fin),
        "provisions": _provisions_annex(fiscal_year),
        "creances_dettes": _creances_dettes_annex(fiscal_year),
    }


def dcom_report(declaration: AccDcomDeclaration) -> list[dict[str, Any]]:
    """ACC-DCOM1 — rapport plat du droit de communication, format XLSX-friendly
    proche des canevas DGI (§1.8 du document annexe) : une ligne par
    (tiers, classification), nom d'affichage du tiers resolu ICI, au moment
    du rendu, JAMAIS stocke sur `AccDcomLine` (regle de couplage n°1 —
    `apps.partners.services.public.get_partner_display_name`, seule surface
    autorisee vers `partners`).

    Reserve OECFM/DGI : `classification` est le classement de repli par
    classe PCG documente sur `services/dcom.py` — pas les 9 canevas DGI
    exacts, cf. reserve en tete de ce module."""
    from apps.partners.services.public import get_partner_display_name

    rows: list[dict[str, Any]] = []
    for line in declaration.lines.all().order_by("partner_id", "classification"):
        rows.append(
            {
                "partner_id": str(line.partner_id),
                "partner_name": get_partner_display_name(line.partner_id),
                "classification": line.classification,
                "amount_mga": line.amount_mga,
            }
        )
    return rows


def _bucket_total(rows: list[dict[str, Any]]) -> Decimal:
    """Somme du champ `amount` d'un panier courant/non-courant tel que
    retourne par `balance_sheet` (`actif`/`passif` x `courant`/`non_courant`)."""
    return sum((row["amount"] for row in rows), Decimal(0))


def _cumulative_balance_by_type(account_type: str, cutoff: Any) -> Decimal:
    """Solde CUMULE (meme convention que `balance_sheet` : toutes ecritures
    publiees depuis l'origine, date <= `cutoff`) de tous les comptes d'un
    `AccAccount.type` donne — utilise ici pour recuperer isolement le solde
    des comptes de stock (necessaire au BFR/rotation des stocks), une
    information que `balance_sheet` ne restitue plus une fois ses paniers
    courant/non-courant construits (le type de compte est supprime de
    chaque ligne apres tri, cf. `balance_sheet`)."""
    totals = AccMoveLine.objects.filter(
        account__type=account_type, move__state=AccMove.STATE_POSTED, move__date__lte=cutoff
    ).aggregate(debit=Sum("debit"), credit=Sum("credit"))
    return (totals["debit"] or Decimal(0)) - (totals["credit"] or Decimal(0))


def _ratio_or_none(
    numerator: Decimal, denominator: Decimal, *, times: Decimal | None = None
) -> Decimal | None:
    """RG (implicite ACC-RATIO1/2) : un ratio dont le denominateur est nul
    (CA nul, capitaux propres nuls, dettes fournisseurs nulles...) renvoie
    `None` plutot que de lever `ZeroDivisionError` — un jeune tenant/petit
    tenant peut tres bien n'avoir encore aucun chiffre d'affaires ou aucune
    dette fournisseur, ce n'est pas une erreur applicative."""
    if denominator == 0:
        return None
    result = numerator / denominator
    if times is not None:
        result *= times
    return result


def financial_ratios(fiscal_year: AccFiscalYear) -> dict[str, Any]:
    """ACC-RATIO1 + ACC-RATIO2 (§2.8 du document annexe, table "Ratios
    financiers utilises par les banques" transcrite verbatim) : ratios
    financiers de base (CDC §5.1, enrichissement WideHalo jamais construit
    jusqu'ici) + les 3 piliers de l'analyse bancaire locale malgache.

    Structure du retour : deux sous-dictionnaires clairement separes,
    `"ratio1"` (les 6 ratios deja prevus au CDC : Current Ratio,
    Debt-to-Equity, marge nette, EBITDA, DSO, DPO) et `"ratio2"` (les
    ratios de la table §2.8 du document annexe : structure/liquidite/marge/
    rentabilite/rotation) — choix de NE PAS tout fusionner a plat pour que
    l'origine CDC vs annexe-banques de chaque ratio reste tracable a la
    lecture du JSON, plutot que par un commentaire perdu dans le code. Le
    signal explicitement recherche par les analystes de credit (BFR > FDR,
    tresorerie structurellement negative) est neanmoins remonte en clef
    TOP-LEVEL `"bfr_superieur_fdr"` (pas dans `"ratio2"`) pour qu'il ne soit
    jamais enterre dans un sous-objet.

    Reutilise entierement les rapports deja construits en A9 (jamais de
    recalcul direct depuis `AccMoveLine`, sauf pour le solde des comptes de
    stock isole, cf. `_cumulative_balance_by_type` — `balance_sheet` ne
    l'expose plus une fois ses paniers construits) :
    - `balance_sheet(fiscal_year)` pour les totaux actif/passif courant et
      non courant (`_bucket_total`) et le total actif.
    - `income_statement(fiscal_year)` pour "Chiffre d'affaires", "Achats
      consommes", "EXCEDENT BRUT D'EXPLOITATION" et "RESULTAT NET DE
      L'EXERCICE", lus PAR LEUR LABEL EXACT (pas de reconstruction).
    - `equity_variation_statement(fiscal_year)` pour le total des capitaux
      propres (somme des soldes de cloture) : `balance_sheet` ne distingue
      pas les comptes `equity` du reste de son panier passif une fois trie
      (le type de compte est supprime de chaque ligne), alors
      qu'`equity_variation_statement` isole deja exactement ce total et est
      garanti coherent avec le bilan par construction (meme ecritures
      source, cf. sa propre docstring) — reutilise plutot que redevine.
    - `aged_receivables`/`aged_payables(as_of_date=fiscal_year.date_end)`
      pour les creances clients / dettes fournisseurs "d'exploitation".

    Approximations documentees explicitement (formule usuelle retenue en
    l'absence de precision du document source, a ajuster si l'analyste
    bancaire/l'expert-comptable en prefere une autre — reserve plus legere
    que celle des canevas DGI, il ne s'agit ici que d'usages d'analyse
    financiere standards, pas d'une reconstruction de formulaire officiel) :

    1. **Debt-to-Equity** : le panier "passif" de `balance_sheet` regroupe
       DEJA capitaux propres et dettes ensemble (c'est la definition meme
       du bilan, passif = capitaux propres + dettes) sans distinguer les
       deux dans les lignes retournees. Les "dettes totales" utilisees ici
       sont donc calculees par difference : (passif courant + passif non
       courant du bilan) - capitaux propres (via
       `equity_variation_statement`) — ratio dettes/capitaux propres
       standard, PAS "(passif courant+non courant)/capitaux propres" au
       sens litteral (qui reviendrait a (dettes+capitaux propres)/capitaux
       propres, soit ratio+1, un calcul qui n'aurait pas de sens usuel).
    2. **FDR (Fonds de Roulement)** = passif non courant du bilan - actif
       non courant du bilan. Ceci fonctionne directement SANS recalculer
       "ressources stables" separement, car dans la fixture PCG2005 (cf.
       docstring de `balance_sheet`) les capitaux propres ET les
       immobilisations sont les deux seules exceptions `is_current=False`
       par defaut — le panier "passif non courant" du bilan EST donc deja
       exactement "capitaux propres + passifs non courants" (ressources
       stables), et le panier "actif non courant" EST deja "emplois
       stables" (immobilisations). Hypothese heritee de A9, pas nouvelle
       ici.
    3. **DSO/DPO/rotation des stocks** utilisent un solde de fin d'exercice
       (photo a `fiscal_year.date_end`, via `aged_receivables`/
       `aged_payables`/solde de stock) plutot qu'une VRAIE moyenne
       ouverture+cloture/2 — une moyenne exigerait la balance agee de
       l'exercice precedent, qui peut ne pas exister pour le premier
       exercice d'un tenant. Simplification documentee, pas un choix
       silencieux.
    4. **DSO/DPO** utilisent "Chiffre d'affaires"/"Achats consommes" (HT,
       tels qu'exposes par `income_statement`) comme proxy du "TTC" exige
       par la formule bancaire usuelle : la TVA collectee/deductible n'est
       pas isolee separement par ecriture dans ce modele au niveau ou
       `income_statement` la restitue.
    5. **Dettes d'exploitation (BFR)** : `aged_payables` inclut TOUTES les
       dettes fournisseurs non lettrees, pas seulement celles qualifiees
       "d'exploitation" au sens strict (un BFR plus rigoureux exclurait les
       dettes non-exploitation, distinction non modelisee ici).
    6. **Marge brute** : "Cout des ventes" n'existe pas comme ligne
       distincte dans `income_statement` — "Achats consommes" sert de proxy
       le plus proche disponible dans ce modele de donnees (un vrai cout
       des ventes demanderait un suivi COGS distinct des achats bruts, non
       modelise a ce stade).
    7. **Rentabilite economique/financiere** : le document annexe ne
       precise que le PRINCIPE ("aptitude a degager un profit rapporte aux
       ressources investies, fonds propres, fonds pretes"), pas les
       denominateurs exacts. Formules usuelles retenues ici : rentabilite
       economique = resultat net / total actif (rapporte a l'ensemble des
       ressources investies, fonds propres ET empruntes) ; rentabilite
       financiere = resultat net / capitaux propres (rapporte aux seuls
       fonds propres).

    Division par zero (CA nul, capitaux propres nuls, dettes fournisseurs
    nulles...) : chaque ratio concerne renvoie `None` plutot que de lever,
    cf. `_ratio_or_none` — un jeune/petit tenant peut n'avoir aucun CA ou
    aucune dette fournisseur, ce n'est pas une anomalie."""
    cutoff = fiscal_year.date_end
    bs = balance_sheet(fiscal_year, as_of_date=cutoff)
    postes = {row["label"]: row["amount"] for row in income_statement(fiscal_year)}
    capitaux_propres = sum(
        (row["closing"] for row in equity_variation_statement(fiscal_year)), Decimal(0)
    )

    actif_courant = _bucket_total(bs["actif"]["courant"])
    actif_non_courant = _bucket_total(bs["actif"]["non_courant"])
    passif_courant = _bucket_total(bs["passif"]["courant"])
    passif_non_courant = _bucket_total(bs["passif"]["non_courant"])
    total_actif = bs["actif"]["total"]

    chiffre_affaires = postes["Chiffre d'affaires"]
    achats_consommes = postes["Achats consommes"]
    ebitda = postes["EXCEDENT BRUT D'EXPLOITATION"]
    resultat_net = postes["RESULTAT NET DE L'EXERCICE"]

    stock = _cumulative_balance_by_type(AccAccount.TYPE_STOCK, cutoff)
    creances_clients = sum(
        (row["total"] for row in aged_receivables(as_of_date=cutoff)), Decimal(0)
    )
    dettes_fournisseurs = sum(
        (row["total"] for row in aged_payables(as_of_date=cutoff)), Decimal(0)
    )

    dettes_totales = (passif_courant + passif_non_courant) - capitaux_propres

    current_ratio = _ratio_or_none(actif_courant, passif_courant)

    ratio1 = {
        "current_ratio": current_ratio,
        "debt_to_equity": _ratio_or_none(dettes_totales, capitaux_propres),
        "marge_nette": _ratio_or_none(resultat_net, chiffre_affaires),
        "ebitda": ebitda,
        "dso_jours": _ratio_or_none(creances_clients, chiffre_affaires, times=Decimal(365)),
        "dpo_jours": _ratio_or_none(dettes_fournisseurs, achats_consommes, times=Decimal(365)),
    }

    fdr = passif_non_courant - actif_non_courant
    bfr = (stock + creances_clients) - dettes_fournisseurs
    tresorerie_nette = fdr - bfr

    ratio2 = {
        "fdr": fdr,
        "bfr": bfr,
        "tresorerie_nette": tresorerie_nette,
        # Alias documente : identique a `ratio1.current_ratio`, seule la
        # denomination differe entre le CDC (§5.1) et la table §2.8 du
        # document annexe — jamais recalcule une seconde fois.
        "liquidite_generale": current_ratio,
        "liquidite_immediate": _ratio_or_none(actif_courant - stock, passif_courant),
        "marge_brute": _ratio_or_none(chiffre_affaires - achats_consommes, chiffre_affaires),
        "rentabilite_economique": _ratio_or_none(resultat_net, total_actif),
        "rentabilite_financiere": _ratio_or_none(resultat_net, capitaux_propres),
        "rotation_stocks_jours": _ratio_or_none(stock, achats_consommes, times=Decimal(365)),
    }

    return {
        "as_of_date": cutoff,
        "ratio1": ratio1,
        "ratio2": ratio2,
        # Signal explicitement recherche par les analystes de credit (§2.8
        # du document annexe, "Implication ERP") : tresorerie
        # structurellement negative. Clef TOP-LEVEL volontairement, pas
        # enterree dans `ratio2`.
        "bfr_superieur_fdr": bfr > fdr,
    }


def analytical_income_statement(
    fiscal_year: AccFiscalYear, analytic_plan: AccAnalyticPlan
) -> list[dict[str, Any]]:
    """ACC-ANA — compte de resultat analytique par axe : agrege les
    `AccAnalyticLine` deja materialisees par `services/analytics.py::
    record_analytic_lines()` (A6), par `AccAnalyticAccount` du `analytic_plan`
    donne, pour les ecritures PUBLIEES de `fiscal_year` — pure agregation
    d'une table existante, aucun nouveau modele.

    Ventilation produits/charges par compte analytique (au-dela d'un simple
    total plat) : realisable simplement ici car chaque `AccAnalyticLine`
    remonte a sa `AccMoveLine` source (`move_line`), elle-meme rattachee a
    un `AccAccount` dont le `.type` (`income`/`expense`/autre) est
    directement lisible sans jointure supplementaire couteuse — separe donc
    "produits"/"charges"/"net" par compte analytique plutot que de s'en
    tenir a un total plat V1. Un compte analytique jamais mouvemente par un
    produit ou une charge (cas marginal : RG-ACC-9 n'impose une distribution
    analytique que sur les lignes de charge/produit, rien n'empeche
    techniquement une autre nature de compte de porter une distribution) est
    range cote "charges" par defaut plutot que de creer un troisieme panier
    "autre" peu exploitable en V1 — documente ici, pas silencieux."""
    lines = AccAnalyticLine.objects.filter(
        analytic_account__plan=analytic_plan,
        move_line__move__period__fiscal_year=fiscal_year,
        move_line__move__state=AccMove.STATE_POSTED,
    ).select_related("analytic_account", "move_line__account")

    grouped: dict[Any, dict[str, Any]] = {}
    for line in lines:
        account = line.analytic_account
        entry = grouped.setdefault(
            account.id,
            {
                "analytic_account_id": str(account.id),
                "code": account.code,
                "name": account.name,
                "produits": Decimal(0),
                "charges": Decimal(0),
            },
        )
        if line.move_line.account.type == AccAccount.TYPE_INCOME:
            entry["produits"] += line.amount
        else:
            entry["charges"] += line.amount

    rows = []
    for entry in grouped.values():
        entry["net"] = entry["produits"] - entry["charges"]
        rows.append(entry)
    return sorted(rows, key=lambda row: row["code"])


def invoice_pdf(invoice: AccMove) -> bytes:
    """ACC-FAC — facture client (SAL-8), rendue par le gabarit legal partage.

    **Ce que ce rendu corrige.** `invoice_pdf` concatenait une f-string de
    douze lignes. Le document, pourtant declare `is_legal_document=True`
    (`services/reports_registration.py`) et atteignable en deux clics depuis
    l'ecran des rapports comme par `GET /api/accounting/invoices/{id}/pdf`,
    ne portait NI raison sociale, NI adresse, NI NIF de l'emetteur, NI
    identite du client (`partner_id` n'etait meme pas lu), NI ventilation
    HT/TVA/TTC. Ce n'etait pas une facture au sens ou l'administration
    fiscale l'entend — c'etait un releve de lignes.

    Et le libelle de chaque ligne etait interpole SANS ECHAPPEMENT dans le
    HTML : un libelle contenant du balisage se retrouvait interprete par
    WeasyPrint, dans un document archive et immuable. Le gabarit Django
    echappe par defaut, ce qui ferme ce chemin par construction plutot que
    par vigilance.

    **La ventilation vient des comptes, jamais d'un champ de totaux.** Un
    `AccMove` ne porte pas de `amount_untaxed`/`amount_tax` : le HT est la
    somme des lignes de compte de PRODUIT, la TVA celle des lignes de compte
    de TAXE, et le TTC le total au debit (la creance client). Lire les
    comptes plutot qu'un total denormalise garantit que le document dit ce
    que les livres disent."""
    from django.template.loader import render_to_string
    from weasyprint import HTML

    from apps.core.services.branding import get_tenant_logo_data_uri
    from apps.core.utils.formatting import format_mga
    from apps.partners.services.public import get_partner_display_name

    def money(amount: Decimal | int) -> str:
        """Regle UNIQUE de presentation de l'Ariary (`format_mga`), appliquee
        ici parce qu'un document legal est precisement l'endroit ou elle
        compte. Une facture libellee dans une AUTRE devise ne passe pas par
        cette regle — `format_mga` suffixe « Ar » en dur, l'appliquer a des
        euros afficherait un montant faux."""
        # `Decimal(str(...))` : un total denormalise vaut `0` (entier) tant
        # qu'aucune ligne n'a ete ajoutee, et `format_mga` attend un Decimal.
        # Meme coercition que le filtre `|mga` du depot.
        value = Decimal(str(amount))
        if invoice.currency == "MGA":
            return format_mga(value)
        return f"{value} {invoice.currency}"

    invoice_lines = []
    total_untaxed = Decimal(0)
    total_tax = Decimal(0)
    for line in invoice.lines.select_related("account").all():
        if line.account.type == AccAccount.TYPE_INCOME:
            total_untaxed += line.credit - line.debit
        elif line.account.type == AccAccount.TYPE_TAX:
            total_tax += line.credit - line.debit
        else:
            # Ligne de creance/contrepartie : elle porte le TTC, deja rendu
            # par le total ci-dessous — l'afficher en ligne le compterait
            # deux fois aux yeux du lecteur.
            continue
        invoice_lines.append({"label": line.label, "amount": money(line.credit or line.debit)})

    html = render_to_string(
        "reports/legal/invoice.html",
        {
            "invoice": invoice,
            "invoice_lines": invoice_lines,
            "total_untaxed": money(total_untaxed),
            "total_tax": money(total_tax),
            "total_incl_tax": money(invoice.total_debit),
            "partner_name": (
                get_partner_display_name(invoice.partner_id) if invoice.partner_id else ""
            ),
            "tenant": invoice.tenant,
            "tenant_logo_data_uri": get_tenant_logo_data_uri(invoice.tenant),
        },
    )
    result: bytes = HTML(string=html).write_pdf()
    return result


# ACC-TRESO (A15, ACC-TR1 deja nomme au CDC comme enrichissement WideHalo) :
# granularite du prevu 90 jours glissants. Choix documente : des paniers
# HEBDOMADAIRES (7 jours), pas quotidiens — un pas journalier sur 90 jours
# produirait 90 lignes par appel, une granularite superieure a ce qu'un
# tableau de bord de tresorerie exploite habituellement (l'attention utile
# porte sur "quelle semaine risque un creux", pas sur le jour exact), pour un
# cout de lecture/API bien moindre. `_BUCKET_DAYS` expose ici (pas prive) au
# cas ou un futur ecran voudrait un pas different sans reecrire la logique de
# bucketing.
_BUCKET_DAYS = 7


def treasury_forecast(
    tenant: Tenant, *, as_of_date: Any = None, horizon_days: int = 90
) -> dict[str, Any]:
    """ACC-TRESO — prevu de tresorerie sur `horizon_days` jours glissants
    (par defaut 90), decoupe en paniers hebdomadaires (cf. `_BUCKET_DAYS`
    ci-dessus pour le choix de granularite).

    Position de depart : solde CUMULE (memes principes que `balance_sheet` —
    toutes ecritures publiees depuis l'origine, date <= `as_of_date`) des
    comptes de type `AccAccount.TYPE_CASH`/`TYPE_BANK`.

    Entrees/sorties attendues : lignes `AccMoveLine` OUVERTES (memes criteres
    qu'`aged_receivables`/`aged_payables`, A9 : `matching_number == ""`) sur
    un compte `receivable`/`payable`, dont `due_date` tombe dans la fenetre
    `[as_of_date, as_of_date + horizon_days]`. Une ligne sans `due_date` (ou
    hors fenetre) n'apparait dans aucun panier — a la difference d'
    `aged_receivables`, un prevu de tresorerie n'a pas de sens pour une
    echeance inconnue ou hors horizon.

    Solde projete par panier = position de depart + entrees cumulees -
    sorties cumulees jusqu'a la fin de ce panier (cumul, pas panier isole).

    **Detection de creux (ACC-TR1)** : chaque panier dont le solde projete
    est negatif est signale dans `"dips"`. C'est un simple SEUIL (`< 0`),
    pas un modele statistique — meme discipline "explicabilite d'abord" que
    RG-SAL-8 (cf. plan) : un tenant doit pouvoir retrouver a la main pourquoi
    un creux est signale, jamais une boite noire.

    `tenant` : parametre expose pour la signature (coherent avec le reste de
    `services/dunning.py`/`services/mobile_money.py` d'A15) mais non utilise
    directement pour filtrer les requetes ci-dessous — `AccMoveLine.objects`
    (TenantManager) filtre deja systematiquement sur le tenant COURANT du
    contexte d'execution (meme convention que toutes les fonctions
    existantes de ce module, ex. `aged_receivables`, qui ne prennent pas non
    plus `tenant` en parametre)."""
    del tenant  # cf. docstring : filtrage deja assure par TenantManager
    as_of = as_of_date or dt.date.today()
    horizon_end = as_of + dt.timedelta(days=horizon_days)
    n_buckets = -(-horizon_days // _BUCKET_DAYS)  # division entiere arrondie au superieur

    cash_totals = AccMoveLine.objects.filter(
        account__type__in=[AccAccount.TYPE_CASH, AccAccount.TYPE_BANK],
        move__state=AccMove.STATE_POSTED,
        move__date__lte=as_of,
    ).aggregate(debit=Sum("debit"), credit=Sum("credit"))
    starting_cash = (cash_totals["debit"] or Decimal(0)) - (cash_totals["credit"] or Decimal(0))

    def _bucketed_open_amounts(account_type: str) -> list[Decimal]:
        lines = AccMoveLine.objects.filter(
            account__type=account_type,
            move__state=AccMove.STATE_POSTED,
            matching_number="",
            due_date__isnull=False,
            due_date__gte=as_of,
            due_date__lte=horizon_end,
        )
        totals = [Decimal(0) for _ in range(n_buckets)]
        for line in lines:
            assert line.due_date is not None  # garanti par due_date__isnull=False ci-dessus
            bucket_index = min((line.due_date - as_of).days // _BUCKET_DAYS, n_buckets - 1)
            amount = (
                line.debit - line.credit
                if account_type == AccAccount.TYPE_RECEIVABLE
                else line.credit - line.debit
            )
            totals[bucket_index] += amount
        return totals

    inflows_by_bucket = _bucketed_open_amounts(AccAccount.TYPE_RECEIVABLE)
    outflows_by_bucket = _bucketed_open_amounts(AccAccount.TYPE_PAYABLE)

    buckets: list[dict[str, Any]] = []
    dips: list[dict[str, Any]] = []
    cumulative_inflows = Decimal(0)
    cumulative_outflows = Decimal(0)
    for index in range(n_buckets):
        period_start = as_of + dt.timedelta(days=index * _BUCKET_DAYS)
        period_end = min(period_start + dt.timedelta(days=_BUCKET_DAYS - 1), horizon_end)
        cumulative_inflows += inflows_by_bucket[index]
        cumulative_outflows += outflows_by_bucket[index]
        projected_balance = starting_cash + cumulative_inflows - cumulative_outflows
        period_label = (
            f"Semaine {index + 1} ({period_start.isoformat()} - {period_end.isoformat()})"
        )
        buckets.append(
            {
                "period_label": period_label,
                "period_start": period_start,
                "period_end": period_end,
                "inflows_mga": inflows_by_bucket[index],
                "outflows_mga": outflows_by_bucket[index],
                "projected_balance_mga": projected_balance,
            }
        )
        if projected_balance < 0:
            dips.append({"period_label": period_label, "projected_balance_mga": projected_balance})

    return {
        "as_of_date": as_of,
        "horizon_days": horizon_days,
        "starting_cash_mga": starting_cash,
        "buckets": buckets,
        "dips": dips,
        "has_dip": bool(dips),
    }
