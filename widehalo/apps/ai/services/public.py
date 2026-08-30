"""Contrat public de l'app `ai` — seule surface qu'une autre app metier
aurait le droit d'importer (cf. tests/architecture/test_module_
boundaries.py).

Vide au demarrage du module (AI1, premiere etape du chantier) — meme
situation initiale que `apps.strategy.services.public`/`apps.feasibility.
services.public` a leur premiere etape. La direction de couplage retenue
pour `ai` est l'INVERSE : ce sont les autres modules qui s'enregistrent
dans les registres exposes par `core` (`ai_context_registry`,
`anomaly_registry`), jamais `ai` qui importe leurs services. Ce fichier
resterait donc probablement vide meme en fin de chantier, sauf besoin reel
qui apparaitrait plus tard (ex. un futur module consommant directement un
`AiInsight`)."""

from __future__ import annotations
