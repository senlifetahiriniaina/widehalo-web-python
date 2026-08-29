"""Surface publique de `reporting` pour les autres apps (regle de couplage
n1 : `apps.<module>.services.public` est le SEUL sous-module de `reporting`
qu'un autre module metier a le droit d'importer, verifie par `tests.
architecture.test_module_boundaries`).

`render_and_archive` (RPT-10) est le seul gap expose pour l'instant :
`accounting`/`payroll`/`sales` l'appellent chacun depuis leur propre
`services/reports_registration.py` pour archiver, respectivement, ACC-FAC/
PAY-BULL/SAL-BL — les 3 seuls documents legaux nommement cites par le CDC
(cf. plan §reporting). Ces 3 apps doivent declarer "reporting" dans leur
`module.py::dependencies`."""

from __future__ import annotations

from apps.reporting.services.legal_documents import render_and_archive

__all__ = ["render_and_archive"]
