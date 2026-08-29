"""§5.11 reporting : enregistrement des rapports `strategy` dans le registre
partage `core.services.reports_registry`, appele depuis `apps.py::ready()`.

**STR1/STR2** : aucun rapport encore construit — fonction no-op en attente
de STR3 (rapport business plan `STRATEGY-BP`), qui remplira
`register_reports()` en suivant le meme patron que
`apps.accounting.services.reports_registration`/
`apps.payroll.services.reports_registration` (`register_report(...)`)."""

from __future__ import annotations


def register_reports() -> None:
    """Complete en STR3 avec `STRATEGY-BP` (rapport business plan,
    `render_pdf`-only, meme patron que ACC-FAC/PAY-BULL)."""
