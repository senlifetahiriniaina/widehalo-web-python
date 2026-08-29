"""§5.11 reporting : enregistrement du rapport `feasibility` dans le
registre partage `core.services.reports_registry`, appele depuis
`apps.py::ready()` — meme patron que
`apps.strategy.services.reports_registration`/`apps.financing.services.
reports_registration`.

`FEA-STUDY` (rapport d'etude de faisabilite, `services/reports.py`) est
`render_pdf`-only (pas de `render_rows` — document composite multi-
sections, pas un tableau, cf. docstring `reports.py`), meme patron que
STRATEGY-BP/FIN-DOSSIER/ACC-FAC."""

from __future__ import annotations

from typing import Any

from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _

from apps.core.models.user import User
from apps.core.services.reports_registry import register_report
from apps.feasibility.models import FeaStudy


def _adapter_feasibility_study_pdf(params: dict[str, Any], actor: User | None) -> bytes:
    del actor  # non utilise : le scoping tenant/RLS suffit deja (pas de scope N3 par acteur)
    from apps.feasibility.services.reports import generate_feasibility_study_pdf

    study_id = params.get("study_id")
    if not study_id:
        raise ValueError(_("FEA-STUDY necessite le parametre 'study_id'"))
    study = get_object_or_404(FeaStudy, id=study_id)
    return generate_feasibility_study_pdf(study)


def register_reports() -> None:
    register_report(
        code="FEA-STUDY",
        module="feasibility",
        label="Etude de faisabilite",
        permission="feasibility.view_feastudy",
        render_pdf=_adapter_feasibility_study_pdf,
    )
