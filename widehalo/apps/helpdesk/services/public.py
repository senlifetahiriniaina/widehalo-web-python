"""Contrat public de l'app `helpdesk` — seule surface qu'une autre app
metier aurait le droit d'importer (cf. tests/architecture/test_module_
boundaries.py).

Vide au demarrage du module (HD1, cf. plan) — meme situation initiale que
`apps.feasibility.services.public`/`apps.strategy.services.public` a leur
premiere etape : aucun autre module ne consomme encore de donnee de
`helpdesk`. A peupler si un besoin reel apparait plus tard (ex. HD5,
`automation_registry.register_action("helpdesk.create_ticket_from_event",
...)`, deja anticipe par le plan mais hors perimetre de ce premier lot)."""

from __future__ import annotations
