"""Contrat public de l'app `strategy` — seule surface qu'une autre app
aurait le droit d'importer (cf. tests/architecture/test_module_boundaries.py).
`strategy` est le DERNIER module metier de l'ordre acte du Lot 2 Madagascar
(cf. plan) : aucun autre module n'en depend pour l'instant, ce fichier reste
donc vide de gap concret — pose ici par coherence de structure avec tous les
autres modules (`apps.presence.services.public`, `apps.sales.services.
public`, etc.), pret pour un futur module (ex. `financing`) qui voudrait lire
un objectif/KPI strategique."""

from __future__ import annotations
