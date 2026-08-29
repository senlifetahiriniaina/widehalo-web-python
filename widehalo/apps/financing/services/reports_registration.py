"""§5.11 reporting : enregistrement des rapports `financing` dans le
registre partage `core.services.reports_registry`, appele depuis
`apps.py::ready()` — meme patron que `apps.strategy.services.
reports_registration`/`apps.accounting.services.reports_registration`.

`FIN-DOSSIER` et `FIN-CREDOC` sont tous deux `render_pdf`-only (pas de
`render_rows` — documents composites, pas des tableaux, cf. docstring
`services/reports.py`), meme patron que ACC-FAC/PAY-BULL/STRATEGY-BP."""

from __future__ import annotations

from typing import Any

from apps.core.models.user import User
from apps.core.services.reports_registry import register_report
from apps.financing.models import FinCredoc, FinLoanApplication


def _adapter_dossier_pdf(params: dict[str, Any], actor: User | None) -> bytes:
    del actor  # non utilise : agrege des donnees de dossier, pas de scoping N3 par acteur
    from apps.financing.models import FinForecastScenario
    from apps.financing.services.reports import generate_dossier_pdf

    application = FinLoanApplication.objects.get(id=params["application_id"])
    scenario = None
    scenario_id = params.get("scenario_id")
    if scenario_id:
        scenario = FinForecastScenario.objects.filter(id=scenario_id).first()
    return generate_dossier_pdf(
        application,
        scenario=scenario,
        fiscal_year_id=params.get("fiscal_year_id"),
        sales_period_from=params.get("sales_period_from"),
        sales_period_to=params.get("sales_period_to"),
    )


def _adapter_credoc_pdf(params: dict[str, Any], actor: User | None) -> bytes:
    del actor
    from apps.financing.services.reports import generate_credoc_pdf

    credoc = FinCredoc.objects.get(id=params["credoc_id"])
    return generate_credoc_pdf(credoc)


def register_reports() -> None:
    register_report(
        code="FIN-DOSSIER",
        module="financing",
        label="Dossier de financement bancaire",
        permission="financing.view_finloanapplication",
        render_pdf=_adapter_dossier_pdf,
        is_legal_document=True,
    )
    register_report(
        code="FIN-CREDOC",
        module="financing",
        label="Demande d'ouverture de credit documentaire",
        permission="financing.view_fincredoc",
        render_pdf=_adapter_credoc_pdf,
        is_legal_document=True,
    )
