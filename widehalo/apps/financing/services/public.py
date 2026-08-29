"""Contrat public de l'app `financing` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py).

Vide au demarrage du module (FIN1), comme `sales.services.public`/
`purchase.services.public`/`logistics.services.public` l'etaient a leur
premiere etape. Sera peuple si un futur module a besoin de consommer une
donnee de ce module (aucun ne le fait a ce stade du Lot 2)."""

from __future__ import annotations
