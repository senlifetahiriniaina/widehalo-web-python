"""Contrat public de l'app `projects` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/
test_module_boundaries.py).

Vide au demarrage du module (PJ1), comme `financing.services.public`/
`sales.services.public`/`purchase.services.public` l'etaient a leur
premiere etape. Sera peuple si un futur module a besoin de consommer une
donnee de ce module (aucun ne le fait a ce stade)."""

from __future__ import annotations
