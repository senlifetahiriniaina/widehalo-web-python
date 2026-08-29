"""Contrat public de l'app `automation` — seule surface qu'une autre app
aurait le droit d'importer (cf. tests/architecture/test_module_boundaries.py).
Vide pour ce premier chantier : aucun autre module ne consomme encore
`automation` (le sens du couplage est l'inverse — `automation` consomme les
`services.public` des autres modules via son registre d'actions, jamais le
contraire) — pose ici par coherence de structure avec tous les autres
modules, comme `apps.strategy.services.public`."""

from __future__ import annotations
