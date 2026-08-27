"""A12 — ACC-IS/ACC-IR : liasses fiscales assemblees.

Assemble automatiquement, selon `Tenant.fiscal_regime`, les etats financiers
deja produits par `services/reports.py` (A9/A10) en un unique document PDF
composite, une section par etat, chaque section portant un titre clair
("Bilan", "Compte de resultat par nature", ...) — meme pattern de generation
PDF que `services/reports.py::invoice_pdf` (ACC-FAC, phase 1) : une chaine
HTML construite en Python, rendue par WeasyPrint (`HTML(string=...).write_pdf()`),
pas de gabarit Django template — reste coherent avec le seul autre generateur
PDF de cette app plutot que d'introduire un second mecanisme.

- `generate_liasse_is` (§1.1 et §1.10 du document annexe) : bilan + compte de
  resultat par nature + compte de resultat par fonction + tableau des flux de
  tresorerie, pour un tenant au regime Impot Synthetique a la sous-strate
  "seuil haut" (au-dela de 200 M Ar de CA, partie double complete — cf. A8).
- `generate_liasse_ir` : les 5 etats financiers de base (les 4 precedents +
  variation des capitaux propres) PLUS les 4 annexes fiscales
  (`fixed_asset_annexes`, A10), pour un tenant au regime reel.

Ni l'une ni l'autre fonction ne verifie automatiquement la sous-strate de CA
du tenant (meme raisonnement que `cash_basis_report`, A8 : determiner la
sous-strate exacte exigerait un calcul de CA que l'appelant est mieux place
pour connaitre/confirmer) — seul le `fiscal_regime` du tenant est verifie,
avec une `ValidationError` i18n si l'appel ne correspond pas au regime
(meme discipline de garde que `services/ircm.py` pour ACC-IRCM).

Reserve OECFM/DGI (§0.5, §3.5 du document annexe, meme discipline que partout
ailleurs dans cette app) : l'ORDRE et le LIBELLE des sections de ces liasses
sont reconstruits par assemblage des etats deja produits, PAS retrouves dans
un formulaire officiel numerote malgache (contrairement aux liasses fiscales
francaises 2050-2059 ou aux canevas SYSCOHADA) — a confirmer aupres d'un
cabinet OECFM ou de la DGI avant tout usage en production reelle, jamais a
presenter comme un formulaire officiel definitif tel quel."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.accounting.models import AccFiscalYear
from apps.accounting.services.reports import (
    balance_sheet,
    cash_flow_statement,
    equity_variation_statement,
    fixed_asset_annexes,
    income_statement,
    income_statement_by_function,
)
from apps.core.models.tenant import Tenant

_REAL_REGIMES = (Tenant.FISCAL_REGIME_REAL_NO_VAT, Tenant.FISCAL_REGIME_REAL_WITH_VAT)


def _amount(value: Any) -> str:
    if isinstance(value, Decimal):
        return f"{value:,.4f}".replace(",", " ")
    return str(value)


def _rows_table(rows: list[dict[str, Any]], fields: list[str], headers: list[str]) -> str:
    thead = "".join(f"<th>{h}</th>" for h in headers)
    tbody_rows = []
    for row in rows:
        cells = "".join(f"<td>{_amount(row.get(f, ''))}</td>" for f in fields)
        tbody_rows.append(f"<tr>{cells}</tr>")
    return (
        '<table border="1" cellspacing="0" cellpadding="4">'
        f"<thead><tr>{thead}</tr></thead><tbody>{''.join(tbody_rows)}</tbody></table>"
    )


def _balance_sheet_section(fiscal_year: AccFiscalYear) -> str:
    data = balance_sheet(fiscal_year)
    fields = ["code", "name", "amount"]
    headers = ["Compte", "Libelle", "Montant"]
    sections = []
    for label, bucket_key, courant in (
        ("Actif courant", "actif", "courant"),
        ("Actif non courant", "actif", "non_courant"),
        ("Passif courant", "passif", "courant"),
        ("Passif non courant", "passif", "non_courant"),
    ):
        rows = data[bucket_key][courant]
        sections.append(f"<h3>{label}</h3>{_rows_table(rows, fields, headers)}")
    sections.append(
        f"<p>Total actif : {_amount(data['actif']['total'])} — "
        f"Total passif : {_amount(data['passif']['total'])}</p>"
    )
    return f"<h2>Bilan (ACC-BIL) — au {data['as_of_date']}</h2>" + "".join(sections)


def _income_statement_section(fiscal_year: AccFiscalYear) -> str:
    rows = income_statement(fiscal_year)
    table = _rows_table(rows, ["poste", "label", "amount"], ["Poste", "Libelle", "Montant"])
    return f"<h2>Compte de resultat par nature (ACC-CR)</h2>{table}"


def _income_statement_by_function_section(fiscal_year: AccFiscalYear) -> str:
    rows = income_statement_by_function(fiscal_year)
    table = _rows_table(rows, ["label", "amount"], ["Libelle", "Montant"])
    return f"<h2>Compte de resultat par fonction (ACC-CR-FCT)</h2>{table}"


def _cash_flow_section(fiscal_year: AccFiscalYear) -> str:
    data = cash_flow_statement(fiscal_year)
    summary = (
        "<p>"
        f"Operationnel : {_amount(data['operating'])} — "
        f"Investissement : {_amount(data['investing'])} — "
        f"Financement : {_amount(data['financing'])} — "
        f"Variation nette de tresorerie : {_amount(data['net_change_in_cash'])}"
        "</p>"
    )
    table = _rows_table(
        data["lines"],
        ["date", "reference", "section", "account", "label", "amount"],
        ["Date", "Reference", "Section", "Compte", "Libelle", "Montant"],
    )
    return f"<h2>Tableau des flux de tresorerie (ACC-CF)</h2>{summary}{table}"


def _equity_variation_section(fiscal_year: AccFiscalYear) -> str:
    rows = equity_variation_statement(fiscal_year)
    table = _rows_table(
        rows,
        ["code", "name", "opening", "movement", "closing"],
        ["Compte", "Libelle", "Ouverture", "Mouvement", "Cloture"],
    )
    return f"<h2>Variation des capitaux propres (ACC-VCP)</h2>{table}"


_ANNEX_TABLES: dict[str, tuple[list[str], list[str], str]] = {
    "actif_immobilise": (
        [
            "categorie_label",
            "valeur_brute_debut_exercice",
            "acquisitions",
            "cessions_mises_au_rebut",
            "virements_de_poste_a_poste",
            "valeur_brute_fin_exercice",
        ],
        ["Categorie", "Brut debut", "Acquisitions", "Cessions", "Virements", "Brut fin"],
        "Etat de l'actif immobilise",
    ),
    "amortissements": (
        [
            "categorie_label",
            "cumul_debut_exercice",
            "dotations_de_l_exercice",
            "amortissements_sur_sorties",
            "cumul_fin_exercice",
            "valeur_nette_comptable",
        ],
        ["Categorie", "Cumul debut", "Dotations", "Sorties", "Cumul fin", "VNC"],
        "Etat des amortissements",
    ),
    "provisions": (
        ["nature", "montant_debut_exercice", "dotations", "reprises", "montant_fin_exercice"],
        ["Nature", "Debut", "Dotations", "Reprises", "Fin"],
        "Etat des provisions",
    ),
    "creances_dettes": (
        ["nature", "moins_d_un_an", "un_a_cinq_ans", "plus_de_cinq_ans", "total"],
        ["Nature", "< 1 an", "1 a 5 ans", "> 5 ans", "Total"],
        "Etat des creances et dettes par tranche d'echeance",
    ),
}


def _fixed_asset_annexes_section(fiscal_year: AccFiscalYear) -> str:
    data = fixed_asset_annexes(fiscal_year)
    sections = ["<h2>Annexes fiscales (ACC-ANNEXE1)</h2>"]
    for key, (fields, headers, title) in _ANNEX_TABLES.items():
        sections.append(f"<h3>{title}</h3>{_rows_table(data[key], fields, headers)}")
    return "".join(sections)


def _wrap_html(title: str, sections_html: str) -> str:
    return f"""
    <html><head><meta charset="utf-8"></head><body>
      <h1>{title}</h1>
      {sections_html}
    </body></html>
    """


def generate_liasse_is(fiscal_year: AccFiscalYear) -> bytes:
    """ACC-IS — liasse fiscale du regime Impot Synthetique (seuil haut) :
    bilan + compte de resultat par nature + compte de resultat par fonction +
    tableau des flux de tresorerie, en un seul PDF compose de 4 sections.

    Leve une `ValidationError` i18n si `fiscal_year.tenant.fiscal_regime`
    n'est PAS `FISCAL_REGIME_SYNTHETIC` — l'appelant reste responsable de
    savoir si son tenant est effectivement a la sous-strate "seuil haut"
    (au-dela de 200 M Ar de CA) : aucune verification automatique du CA
    n'est faite ici, meme raisonnement que `cash_basis_report` (A8)."""
    tenant = fiscal_year.tenant
    if tenant.fiscal_regime != Tenant.FISCAL_REGIME_SYNTHETIC:
        raise ValidationError(
            _(
                "La liasse ACC-IS n'est applicable qu'aux entreprises au régime "
                "Impôt Synthétique — ce tenant est au régime réel."
            )
        )

    from weasyprint import HTML

    sections_html = (
        _balance_sheet_section(fiscal_year)
        + _income_statement_section(fiscal_year)
        + _income_statement_by_function_section(fiscal_year)
        + _cash_flow_section(fiscal_year)
    )
    html = _wrap_html(f"Liasse fiscale ACC-IS — {fiscal_year.code}", sections_html)
    result: bytes = HTML(string=html).write_pdf()
    return result


def generate_liasse_ir(fiscal_year: AccFiscalYear) -> bytes:
    """ACC-IR — liasse fiscale du regime reel : les 5 etats financiers de
    base (bilan, compte de resultat par nature, compte de resultat par
    fonction, tableau des flux de tresorerie, variation des capitaux propres)
    PLUS les 4 annexes fiscales (`fixed_asset_annexes`, A10), en un seul PDF
    compose de sections.

    Leve une `ValidationError` i18n si `fiscal_year.tenant.fiscal_regime`
    n'est PAS un regime reel (`FISCAL_REGIME_REAL_NO_VAT`/
    `FISCAL_REGIME_REAL_WITH_VAT`) — meme discipline de garde que
    `services/ircm.py::generate_ircm_declaration` pour ACC-IRCM."""
    tenant = fiscal_year.tenant
    if tenant.fiscal_regime not in _REAL_REGIMES:
        raise ValidationError(
            _(
                "La liasse ACC-IR n'est applicable qu'aux entreprises au régime "
                "réel — ce tenant est au régime synthétique."
            )
        )

    from weasyprint import HTML

    sections_html = (
        _balance_sheet_section(fiscal_year)
        + _income_statement_section(fiscal_year)
        + _income_statement_by_function_section(fiscal_year)
        + _cash_flow_section(fiscal_year)
        + _equity_variation_section(fiscal_year)
        + _fixed_asset_annexes_section(fiscal_year)
    )
    html = _wrap_html(f"Liasse fiscale ACC-IR — {fiscal_year.code}", sections_html)
    result: bytes = HTML(string=html).write_pdf()
    return result
