"""Surface publique de `reporting` pour les autres apps — vide pour
l'instant : `reporting` est un point d'arrivee du modulith (il consomme les
`services/reports.py` des 9 modules metier via le registre partage
`core.services.reports_registry`), jamais une dependance d'un autre module
metier. Le fichier existe par convention transversale du projet (chaque app
expose un `services/public.py`, meme vide) — a completer si un futur module
(ex. `strategy`) a besoin d'interroger l'etat d'un `RptJob`/`RptSchedule`."""

from __future__ import annotations
