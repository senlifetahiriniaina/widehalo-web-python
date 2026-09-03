"""Surface publique de `reporting` pour les autres apps (regle de couplage
n1 : `apps.<module>.services.public` est le SEUL sous-module de `reporting`
qu'un autre module metier a le droit d'importer, verifie par `tests.
architecture.test_module_boundaries`).

`render_and_archive` (RPT-10) est le premier gap expose :
`accounting`/`payroll`/`sales` l'appellent chacun depuis leur propre
`services/reports_registration.py` pour archiver, respectivement, ACC-FAC/
PAY-BULL/SAL-BL — les 3 seuls documents legaux nommement cites par le CDC
(cf. plan §reporting). Ces 3 apps doivent declarer "reporting" dans leur
`module.py::dependencies`.

`enqueue_report_generation` (gap ajoute par le chantier module BI, cahier
Phase 2 §13.1, BI-8 "export asynchrone avec telechargement differe") :
reutilise integralement le mecanisme `RptJob`/`generate_report` deja
construit (seuil d'asynchronie RPT-6, notification a la fin, purge a 7
jours) plutot que d'en batir un second parallele — `bi` n'a donc AUCUN
modele de job d'export a lui. Retourne des primitives, jamais l'objet
`RptJob` (regle de couplage n1) ; le suivi/telechargement se fait via les
ecrans/API DEJA publics de `reporting` (`reporting:job_status`,
`/api/v1/reporting/jobs/{id}/download`), reutilisables tels quels par
n'importe quel appelant qui possede un `job_id`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.reporting.services.legal_documents import render_and_archive

if TYPE_CHECKING:
    from apps.core.models.user import User

__all__ = ["render_and_archive", "enqueue_report_generation"]


def enqueue_report_generation(
    *,
    code: str,
    params: dict[str, Any],
    format: str,
    lang: str,
    actor: User | None,
    tenant_id: str,
    estimated_row_count: int | None = None,
) -> dict[str, Any]:
    from apps.reporting.services.engine import generate_report

    job = generate_report(
        code=code,
        params=params,
        format=format,
        lang=lang,
        actor=actor,
        tenant_id=tenant_id,
        estimated_row_count=estimated_row_count,
    )
    return {"job_id": str(job.id), "state": job.state}
