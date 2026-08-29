"""Contrat public de l'app `feasibility` — seule surface qu'une autre app
metier aurait le droit d'importer (cf. tests/architecture/test_module_
boundaries.py).

Vide au demarrage du module (FEA1-3, dernier chantier du sous-sequencement
courant, cf. plan) — meme situation initiale que `apps.strategy.services.
public`/`apps.financing.services.public` a leur premiere etape : aucun
autre module ne consomme encore de donnee de `feasibility` (une etude de
faisabilite est un outil de decision autonome, pas une source de donnees
pour un autre module metier). A peupler si un besoin reel apparait plus
tard (ex. transformer une etude validee en devis reel cote `sales`)."""

from __future__ import annotations
