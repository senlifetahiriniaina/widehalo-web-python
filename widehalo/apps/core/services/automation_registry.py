"""Registre central des actions declenchables par un flux d'automatisation
(AUTO3, chantier Studio de workflow visuel) — meme patron que
`apps.core.services.reports_registry`/`apps.core.events` : chaque module
metier s'auto-enregistre via son propre `apps.py::ready()`, jamais un
import direct par `apps.automation` des fonctions `services.public` de
chaque module (regle de couplage n°1 — `automation` ne declare de
dependance que sur `core`).

**Decision de conception actee (cf. plan, section cadrage)** : jamais un
appel Python arbitraire, jamais une transition FSM generique dans ce
premier chantier (trop risque pour un contournement RBAC, explicitement
ecarte par l'utilisateur) — une action enregistree ici est TOUJOURS une
fonction `services.public` deja existante et explicitement whitelistee par
son module d'origine, jamais une reference dynamique construite depuis une
chaine de caracteres fournie par l'utilisateur du studio.

Signature uniforme imposee a toute action enregistree : `(tenant_id: str,
params: dict[str, Any]) -> Any` — `tenant_id` toujours en premier
(le moteur d'execution tourne hors contexte de requete HTTP, en tache
Django-Q2, jamais un `request.auth` disponible), `params` deja resolus
(valeurs statiques ou expressions evaluees contre le payload de
l'evenement declencheur, cf. `apps.automation.services.engine`)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

ActionFunction = Callable[[str, dict[str, Any]], Any]


@dataclass(frozen=True)
class RegisteredAction:
    code: str
    module: str
    label: str
    function: ActionFunction
    # Schema declaratif {nom_parametre: description} — pour l'ecran
    # constructeur (palette de noeuds), jamais valide programmatiquement
    # ici (chaque adaptateur reste responsable de valider/completer ses
    # propres parametres, comme les adaptateurs de `reports_registry`).
    param_schema: dict[str, str] = field(default_factory=dict)


_REGISTRY: dict[str, RegisteredAction] = {}


def register_action(
    *,
    code: str,
    module: str,
    label: str,
    function: ActionFunction,
    param_schema: dict[str, str] | None = None,
) -> None:
    """Appele depuis `apps.py::ready()` de chaque module metier. Idempotent
    (un meme `code` re-enregistre remplace simplement l'entree — utile en
    reload de dev), meme discipline que `reports_registry.register_report`."""
    _REGISTRY[code] = RegisteredAction(
        code=code,
        module=module,
        label=label,
        function=function,
        param_schema=dict(param_schema or {}),
    )


def get_registered_action(code: str) -> RegisteredAction | None:
    return _REGISTRY.get(code)


def list_registered_actions() -> list[RegisteredAction]:
    return sorted(_REGISTRY.values(), key=lambda a: a.code)


def registry_size() -> int:  # pragma: no cover - utilitaire de diagnostic
    return len(_REGISTRY)
