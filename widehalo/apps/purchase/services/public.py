"""Contrat public de l'app `purchase` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py).

PU1 du sous-sequencement (cf. plan) : rien a exposer pour l'instant (la
demande d'achat est encore une entite interne, consommee uniquement par
les ecrans/API de `purchase` lui-meme). Ce fichier existe des PU1, meme
vide de fonctions, pour que `logistics`/`stocks`/`financing` puissent s'y
brancher plus tard sans devoir le creer a ce moment-la."""

from __future__ import annotations
