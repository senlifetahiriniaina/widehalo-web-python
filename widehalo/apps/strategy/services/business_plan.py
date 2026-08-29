"""Rapport « business plan » (exigence actee pendant `reporting`) —
document composite multi-pages consolidant KPI multi-modules, previsions,
objectifs OKR et notes qualitatives.

**Decision de conception** (cf. plan) : ce n'est PAS un rapport tabulaire
simple, donc construit DIRECTEMENT en WeasyPrint (chaine HTML assemblee en
Python, `HTML(string=...).write_pdf()`) — meme patron que les autres gros
documents composites deja construits dans ce projet
(`apps.accounting.services.tax_returns::generate_liasse_is/generate_liasse_ir`)
— plutot que force dans le contrat `render_rows -> list[dict]` du moteur
`reporting` (celui-ci exclut deja explicitement les rapports non tabulaires,
cf. disclosure de `apps.accounting.services.reports_registration`).

**Neanmoins enregistre dans le catalogue** `reporting` (cf.
`services/reports_registration.py`, `STRATEGY-BP`, `render_pdf`-only, meme
patron que ACC-FAC/PAY-BULL) pour rester decouvrable/planifiable comme tout
autre rapport.

Sections assemblees, dans l'ordre : (1) KPI multi-modules — lus via les
`services.public` deja exposes par `sales`/`payroll`/`accounting` (jamais un
nouvel acces direct a leurs modeles) ; (2) previsions deja construites
(`sales_forecast` S6, `PAY-PROJ1` masse salariale, `ACC-TRESO` tresorerie
previsionnelle) ; (3) synthese des `StgObjective`/`StgKeyResult` actifs sur
la periode ; (4) `StgNote` rattachees a la periode/aux objectifs."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db.models import Q

from apps.strategy.models import StgNote, StgObjective

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant


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


def _period_bounds(period: str) -> tuple[dt.date, dt.date]:
    """`period` au format `AAAA-MM` (meme convention que `SalesForecast.
    period`) — renvoie les bornes `[premier jour, dernier jour]` du mois."""
    year, month = (int(part) for part in period.split("-"))
    period_start = dt.date(year, month, 1)
    next_month = period_start.replace(day=28) + dt.timedelta(days=4)
    period_end = next_month - dt.timedelta(days=next_month.day)
    return period_start, period_end


def _kpi_and_forecast_section(tenant: Tenant, period: str) -> str:
    """Section (1)+(2) : KPI/previsions multi-modules, lus EXCLUSIVEMENT
    via `services.public` (`sales`/`payroll`/`accounting`) — signatures
    verifiees dans le code reel de chaque module avant appel (cf. plan),
    jamais devinees."""
    from apps.accounting.services.public import get_treasury_forecast_summary
    from apps.payroll.services.public import get_payroll_mass_projection
    from apps.sales.services.public import get_forecast_summary

    period_start, period_end = _period_bounds(period)

    forecast_rows = get_forecast_summary(tenant, period_from=period, period_to=period)
    forecast_table = _rows_table(
        forecast_rows,
        ["period", "variant_id", "qty_forecast", "qty_actual", "confidence"],
        ["Periode", "Variante", "Prevu", "Realise", "Confiance"],
    )

    payroll_projection = get_payroll_mass_projection(tenant, months=1)
    payroll_table = _rows_table(
        [
            {
                "mois": row["month_index"],
                "masse_salariale": row["total_wage_base"],
                "charges_patronales": row["total_employer_social"],
            }
            for row in payroll_projection
        ],
        ["mois", "masse_salariale", "charges_patronales"],
        ["Mois", "Masse salariale", "Charges patronales"],
    )

    treasury = get_treasury_forecast_summary(tenant, as_of_date=period_end, horizon_days=90)
    dips = treasury.get("dips", [])
    treasury_summary = (
        f"<p>Solde de depart : {_amount(treasury.get('starting_cash_mga', Decimal(0)))} — "
        f"Creux detectes (ACC-TR1) : {len(dips)}</p>"
    )

    return (
        "<h2>Indicateurs et previsions</h2>"
        f"<h3>Prevision des ventes ({period})</h3>{forecast_table}"
        f"<h3>Projection de masse salariale (mois suivant {period_start})</h3>{payroll_table}"
        f"<h3>Tresorerie previsionnelle (90 jours a partir du {period_end})</h3>{treasury_summary}"
    )


def _objectives_section(tenant: Tenant, period: str) -> str:
    """Section (3) : synthese des `StgObjective`/`StgKeyResult` ACTIFS sur
    la periode (chevauchement `[period_start, period_end]`)."""
    period_start, period_end = _period_bounds(period)
    objectives = StgObjective.objects.filter(
        tenant=tenant,
        is_active=True,
        period_start__lte=period_end,
        period_end__gte=period_start,
    ).prefetch_related("key_results")

    rows: list[dict[str, Any]] = []
    for objective in objectives:
        for key_result in objective.key_results.filter(is_active=True):
            rows.append(
                {
                    "objectif": objective.title,
                    "niveau": objective.get_level_display(),
                    "statut": objective.get_status_display(),
                    "indicateur": key_result.metric_name,
                    "progression_pct": key_result.progress_pct(),
                }
            )
    table = _rows_table(
        rows,
        ["objectif", "niveau", "statut", "indicateur", "progression_pct"],
        ["Objectif", "Niveau", "Statut", "Indicateur", "Progression %"],
    )
    return f"<h2>Objectifs et resultats cles (OKR)</h2>{table}"


def _notes_section(tenant: Tenant, period: str) -> str:
    """Section (4) : `StgNote` rattachees a un objectif actif sur la
    periode, ou notes generales (`objective` vide) — jamais wrappees en
    `gettext` (contenu humain, cf. `models.py`)."""
    period_start, period_end = _period_bounds(period)
    notes = StgNote.objects.filter(tenant=tenant, is_active=True).filter(
        Q(objective__isnull=True)
        | Q(objective__period_start__lte=period_end, objective__period_end__gte=period_start)
    )
    sections = [f"<h3>{note.title}</h3><p>{note.body}</p>" for note in notes]
    return "<h2>Notes et commentaires qualitatifs</h2>" + "".join(sections)


def generate_business_plan_pdf(tenant: Tenant, period: str, lang: str = "fr") -> bytes:
    """`STRATEGY-BP` : document composite multi-sections. `period` au
    format `AAAA-MM` (meme convention que `SalesForecast.period`). `lang`
    reserve pour une future traduction complete du gabarit — le contenu
    genere aujourd'hui reste en francais quelle que soit la valeur (dette
    mineure, disclosed : aucun autre rapport composite de ce projet
    (`generate_liasse_is`/`generate_liasse_ir`) ne traite `lang` non plus)."""
    del lang  # cf. docstring : reserve, non exploite pour l'instant
    from weasyprint import HTML

    sections_html = (
        _kpi_and_forecast_section(tenant, period)
        + _objectives_section(tenant, period)
        + _notes_section(tenant, period)
    )
    html = f"""
    <html><head><meta charset="utf-8"></head><body>
      <h1>Business plan — {tenant.name} — {period}</h1>
      {sections_html}
    </body></html>
    """
    result: bytes = HTML(string=html).write_pdf()
    return result
