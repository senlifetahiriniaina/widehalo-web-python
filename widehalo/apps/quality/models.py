"""Modeles de `apps.quality` (Qualite/HACCP, cahier Phase 3 §3.5, decision
D2 — application dediee plutot qu'une fusion dans `apps.stocks`, cf. l'ADR
`docs/planning/2026-09-adr-qualite-haccp-app-dediee.md`).

Vide au demarrage du module (sprint P6, squelette uniquement) — meme
situation initiale que `apps.helpdesk.models`/`apps.feasibility.models` a
leur premiere etape. La modelisation reelle (plan de controle, point
critique, mesure, non-conformite bloquante, certificat obligatoire, dossier
de rappel) arrive au Bloc D (D1-D4 du plan Phase 3), avec des references
generiques `content_type`/`object_id` vers d'autres apps (meme patron que
`core.models.quality.QltInspection`/`core.models.risk.RiskItem`), jamais une
FK directe vers un modele metier d'une autre app."""

from __future__ import annotations
