"""Contrat public de l'app `ai` — seule surface qu'une autre app metier
aurait le droit d'importer (cf. tests/architecture/test_module_
boundaries.py).

Reste vide pour la direction de couplage PRINCIPALE de `ai` (les autres
modules s'enregistrent dans les registres exposes par `core` —
`ai_context_registry`/`anomaly_registry`/etc. —, jamais l'inverse).

**Premier besoin reel apparu au chantier `helpdesk` (HD3)** :
`apps.helpdesk.services.ai_assist.suggest_reply` doit obtenir son
fournisseur IA via le point d'entree fallback-first mandate
(`apps.ai.services.usage_budget.get_budget_gated_provider`, cf. sa
docstring) et journaliser sa consommation (`record_request`/
`estimate_tokens`) — ces trois fonctions vivent dans `apps.ai.services.
usage_budget`, PAS dans ce fichier `public.py` (regle de couplage n°1 du
depot : une autre app ne peut importer QUE `apps.ai.services.public`,
jamais un autre sous-module de `ai`). Simples re-exports ci-dessous,
plutot qu'une duplication de logique — `usage_budget.py` reste l'implementation
et la source de verite unique."""

from __future__ import annotations

from apps.ai.services.usage_budget import (
    estimate_tokens,
    get_budget_gated_provider,
    record_request,
)

__all__ = ["estimate_tokens", "get_budget_gated_provider", "record_request"]
