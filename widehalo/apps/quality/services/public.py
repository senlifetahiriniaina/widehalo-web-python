"""Contrat public de l'app `quality` — seule surface qu'une autre app
metier aurait le droit d'importer (cf. tests/architecture/test_module_
boundaries.py).

Vide au demarrage du module (sprint P6, cf. l'ADR `docs/planning/
2026-09-adr-qualite-haccp-app-dediee.md`) — meme situation initiale que
`apps.helpdesk.services.public`/`apps.feasibility.services.public` a leur
premiere etape : aucun autre module ne consomme encore de donnee de
`quality`. A peupler au Bloc D quand une consommation cross-app reelle
apparaitra (ex. `apps.purchase`/`apps.mrp` verifiant un certificat
obligatoire ou une non-conformite bloquante avant de faire progresser leur
propre workflow)."""

from __future__ import annotations
