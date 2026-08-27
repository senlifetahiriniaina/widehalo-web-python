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
_ASSET_TYPE_ORDER = {
    AccAccount.TYPE_ASSET: 0,  # immobilisations incorporelles/corporelles/financieres
    AccAccount.TYPE_TAX: 1,  # actifs d'impot (lignes tax a solde debiteur)
    AccAccount.TYPE_STOCK: 2,  # stocks
    AccAccount.TYPE_RECEIVABLE: 3,  # clients et comptes rattaches
    AccAccount.TYPE_BANK: 4,  # tresorerie et equivalents
    AccAccount.TYPE_CASH: 4,
}
_LIABILITY_TYPE_ORDER = {
    AccAccount.TYPE_EQUITY: 0,  # capitaux propres
    AccAccount.TYPE_LIABILITY: 1,  # passifs financiers / provisions
    AccAccount.TYPE_PAYABLE: 2,  # fournisseurs et comptes rattaches / autres dettes
    AccAccount.TYPE_TAX: 3,  # passifs d'impot (lignes tax a solde crediteur)
}


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

    for bucket, order_map in (
        (actif_courant, _ASSET_TYPE_ORDER),
        (actif_non_courant, _ASSET_TYPE_ORDER),
        (passif_courant, _LIABILITY_TYPE_ORDER),
        (passif_non_courant, _LIABILITY_TYPE_ORDER),
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


# ACC-CR (§1.10.2 du document annexe, Art. 132-1 a 132-5, presentation Titre
# XII.32) — table de passage comptes -> postes retranscrite VERBATIM depuis
# la table du document annexe (Annexe II du PCG 2005). Chaque entree porte
# les comptes sources ("additive") et les elements soustractifs
# ("subtractive") de la colonne correspondante du document ; `natural`
# indique le sens naturel du poste (`"credit"` pour un poste de produit,
# `"debit"` pour un poste de charge) — les comptes `subtractive` sont
# toujours evalues dans le sens OPPOSE de `natural` (ce sont par construction
# des comptes contraires : rabais/ristournes obtenus sur achats, etc.).
_CR_NATURE_MAPPING: list[dict[str, Any]] = [
    # Ligne "Chiffre d'affaires" : comptes 701 a 708, 7091 a 7098 (additifs).
    {
        "label": "Chiffre d'affaires",
        "natural": "credit",
        "additive": (
            "701",
            "702",
            "703",
            "704",
            "705",
            "706",
            "707",
            "708",
            "7091",
            "7092",
            "7093",
            "7094",
            "7095",
            "7096",
            "7097",
            "7098",
        ),
        "subtractive": (),
    },
    # Ligne "Production stockee" : 713 (credit), 714 additifs ; 713 (debit)
    # soustractif — nette automatiquement par le solde credit-debit de 713.
    {
        "label": "Production stockee",
        "natural": "credit",
        "additive": ("713", "714"),
        "subtractive": (),
    },
    # Ligne "Production immobilisee" : 721, 722 additifs.
    {
        "label": "Production immobilisee",
        "natural": "credit",
        "additive": ("721", "722"),
        "subtractive": (),
    },
    # Ligne "Achats consommes" : 601 a 608 (dont 603 debit) additifs ; 603
    # (credit, netted dans le solde 601-608) et 6091-6098 soustractifs.
    {
        "label": "Achats consommes",
        "natural": "debit",
        "additive": ("601", "602", "603", "604", "605", "606", "607", "608"),
        "subtractive": ("6091", "6092", "6093", "6094", "6095", "6096", "6097", "6098"),
    },
    # Ligne "Subvention d'exploitation" : 741, 748 additifs.
    {
        "label": "Subvention d'exploitation",
        "natural": "credit",
        "additive": ("741", "748"),
        "subtractive": (),
    },
    # Ligne "Charges de personnel" : 641, 644-648 additifs.
    {
        "label": "Charges de personnel",
        "natural": "debit",
        "additive": ("641", "644", "645", "646", "647", "648"),
        "subtractive": (),
    },
    # Ligne "Impots, taxes et versements assimiles" : 631, 635, 638 additifs.
    {
        "label": "Impots, taxes et versements assimiles",
        "natural": "debit",
        "additive": ("631", "635", "638"),
        "subtractive": (),
    },
    # Ligne "Autres produits operationnels" : 751-758 additifs.
    {
        "label": "Autres produits operationnels",
        "natural": "credit",
        "additive": ("751", "752", "753", "754", "755", "756", "757", "758"),
        "subtractive": (),
    },
    # Ligne "(Autres charges operationnelles, dotations aux amortissements
    # et provisions)" : soustractif 68x uniquement (poste entierement une
    # charge, sources vides dans le document).
    {
        "label": "Dotations aux amortissements et provisions",
        "natural": "debit",
        "additive": ("68",),
        "subtractive": (),
    },
    # Ligne "Produits financiers" : 76x, 77x additifs.
    {
        "label": "Produits financiers",
        "natural": "credit",
        "additive": ("76", "77"),
        "subtractive": (),
    },
    # Ligne "Charges financieres" : soustractif 66x, 67x.
    {
        "label": "Charges financieres",
        "natural": "debit",
        "additive": ("66", "67"),
        "subtractive": (),
    },
    # Ligne "Impot sur les resultats" : soustractif 69x.
    {
        "label": "Impot sur les resultats",
        "natural": "debit",
        "additive": ("69",),
        "subtractive": (),
    },
]


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
    return _sum_natural(balances, entry["additive"], natural) - _sum_natural(
        balances, entry["subtractive"], opposite
    )


def income_statement(fiscal_year: AccFiscalYear) -> list[dict[str, Any]]:
    """ACC-CR — compte de resultat par nature (§1.10.2 du document annexe),
    presentation "en liste" avec soldes intermediaires en cascade (I a IX),
    calculee directement depuis `_CR_NATURE_MAPPING` (table de passage
    comptes -> postes transcrite du document annexe)."""
    balances = _account_balances(fiscal_year)
    postes = {entry["label"]: _poste_amount(balances, entry) for entry in _CR_NATURE_MAPPING}

    chiffre_affaires = postes["Chiffre d'affaires"]
    production_stockee = postes["Production stockee"]
    production_immobilisee = postes["Production immobilisee"]
    production_exercice = chiffre_affaires + production_stockee + production_immobilisee

    achats_consommes = postes["Achats consommes"]
    consommation_exercice = achats_consommes

    valeur_ajoutee = production_exercice - consommation_exercice

    subvention_exploitation = postes["Subvention d'exploitation"]
    charges_personnel = postes["Charges de personnel"]
    impots_taxes = postes["Impots, taxes et versements assimiles"]
    excedent_brut = valeur_ajoutee + subvention_exploitation - charges_personnel - impots_taxes

    autres_produits_operationnels = postes["Autres produits operationnels"]
    dotations_amortissements = postes["Dotations aux amortissements et provisions"]
    resultat_operationnel = excedent_brut + autres_produits_operationnels - dotations_amortissements

    produits_financiers = postes["Produits financiers"]
    charges_financieres = postes["Charges financieres"]
    resultat_financier = produits_financiers - charges_financieres

    resultat_activites_ordinaires = resultat_operationnel + resultat_financier

    # Elements extraordinaires : le document annexe ne fournit aucune plage
    # de comptes pour cette ligne (§1.10.2, "—"/"—") — toujours 0 en V1,
    # documente explicitement plutot que devine.
    elements_extraordinaires = Decimal(0)
    resultat_avant_impot = resultat_activites_ordinaires + elements_extraordinaires

    impot_resultats = postes["Impot sur les resultats"]
    resultat_net = resultat_avant_impot - impot_resultats

    return [
        {"poste": "", "label": "Chiffre d'affaires", "amount": chiffre_affaires},
        {"poste": "", "label": "Production stockee", "amount": production_stockee},
        {"poste": "", "label": "Production immobilisee", "amount": production_immobilisee},
        {"poste": "I", "label": "Production de l'exercice", "amount": production_exercice},
        {"poste": "", "label": "Achats consommes", "amount": achats_consommes},
        {"poste": "II", "label": "Consommation de l'exercice", "amount": consommation_exercice},
        {"poste": "III", "label": "VALEUR AJOUTEE D'EXPLOITATION", "amount": valeur_ajoutee},
        {"poste": "", "label": "Subvention d'exploitation", "amount": subvention_exploitation},
        {"poste": "", "label": "Charges de personnel", "amount": charges_personnel},
        {
            "poste": "",
            "label": "Impots, taxes et versements assimiles",
            "amount": impots_taxes,
        },
        {"poste": "IV", "label": "EXCEDENT BRUT D'EXPLOITATION", "amount": excedent_brut},
        {
            "poste": "",
            "label": "Autres produits operationnels",
            "amount": autres_produits_operationnels,
        },
        {
            "poste": "",
            "label": "Dotations aux amortissements et provisions",
            "amount": dotations_amortissements,
        },
        {"poste": "V", "label": "RESULTAT OPERATIONNEL", "amount": resultat_operationnel},
        {"poste": "", "label": "Produits financiers", "amount": produits_financiers},
        {"poste": "", "label": "Charges financieres", "amount": charges_financieres},
        {"poste": "VI", "label": "RESULTAT FINANCIER", "amount": resultat_financier},
        {
            "poste": "VII",
            "label": "RESULTAT DES ACTIVITES ORDINAIRES",
            "amount": resultat_activites_ordinaires,
        },
        {"poste": "", "label": "Elements extraordinaires", "amount": elements_extraordinaires},
        {"poste": "VIII", "label": "RESULTAT AVANT IMPOT", "amount": resultat_avant_impot},
        {"poste": "", "label": "Impot sur les resultats", "amount": impot_resultats},
        {"poste": "IX", "label": "RESULTAT NET DE L'EXERCICE", "amount": resultat_net},
    ]


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
    charge_entries = (
        AccMoveLine.objects.filter(
            move__period__fiscal_year=fiscal_year,
            move__state=AccMove.STATE_POSTED,
            account__account_class=6,
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
        account__account_class=7,
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


def _cash_flow_section(account: AccAccount) -> str:
    """ACC-CF (§1.10.3 du document annexe) : classification "methode
    directe" d'une ligne de contrepartie de mouvement de tresorerie —
    choix de methode documente sur `cash_flow_statement`."""
    if account.account_class == 2:
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
            section = _cash_flow_section(line.account)
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


def invoice_pdf(invoice: AccMove) -> bytes:
    """ACC-FAC — facture client, document PDF bilingue (FR/EN) minimal."""
    from weasyprint import HTML

    lines_html = "".join(
        f"<tr><td>{line.label}</td><td>{line.debit or line.credit}</td></tr>"
        for line in invoice.lines.all()
    )
    html = f"""
    <html><head><meta charset="utf-8"></head><body>
      <h1>Facture / Invoice {invoice.reference}</h1>
      <p>Date : {invoice.date}</p>
      <table border="1" cellspacing="0" cellpadding="4">
        <thead><tr><th>Libelle / Label</th><th>Montant / Amount</th></tr></thead>
        <tbody>{lines_html}</tbody>
      </table>
      <p>Total : {invoice.total_debit} {invoice.currency}</p>
    </body></html>
    """
    result: bytes = HTML(string=html).write_pdf()
    return result
