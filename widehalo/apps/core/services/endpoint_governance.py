"""Registre explicite des endpoints django-ninja intentionnellement
ouverts a tout utilisateur authentifie (sans decorateur `require_permission`
ni `require_superuser`) — cf. cahier des charges WideHalo v3, Phase 1,
§6.4 : « Decoration obligatoire de tout endpoint ; test de CI listant les
endpoints sans declarations de permission et faisant echouer la
construction ».

`tests/architecture/test_endpoint_permissions.py` echoue la construction
si un endpoint authentifie (`auth_param` non explicitement `None`) n'est
NI garde par `require_permission`/`require_superuser`, NI enumere ici.
Ajouter une entree ici est donc une decision explicite et documentee
(comme les relevements de `BUDGET_MAX_*` dans `config/settings/base.py`),
jamais un contournement silencieux — chaque motif cite la regle metier ou
le document source qui justifie l'ouverture.

Cle : `f"{view_func.__module__}.{view_func.__qualname__}"` de la fonction
VUE D'ORIGINE (avant tout decorateur, cf. test)."""

from __future__ import annotations

INTENTIONALLY_OPEN_ENDPOINTS: dict[str, str] = {
    # docs/RBAC.md §3.2 : l'entree RBAC du module `ai` couvre uniquement
    # l'administration du budget de tokens/cout (`admin`/`direction`) ;
    # les fonctionnalites IA a usage large (assistant contextuel,
    # recherche naturelle, insights, recommandations, copilote donnees)
    # sont deliberement ouvertes a tout utilisateur authentifie, meme
    # posture que `chat` — chacune reste filtree en interne par tenant/RLS
    # et, pour le copilote donnees, par la liste blanche d'outils
    # `core.services.data_query_tool_registry` (deny-by-default par outil).
    "apps.ai.api.assist_endpoint": (
        "IA a usage large, ouverte a tout utilisateur authentifie (docs/RBAC.md §3.2)."
    ),
    "apps.ai.api.list_assist_modules_endpoint": "Idem assist_endpoint.",
    "apps.ai.api.nl_search_endpoint": "Idem assist_endpoint.",
    "apps.ai.api.generate_insights_endpoint": "Idem assist_endpoint.",
    "apps.ai.api.list_insights_endpoint": "Idem assist_endpoint.",
    "apps.ai.api.suggest_recommendations_endpoint": "Idem assist_endpoint.",
    "apps.ai.api.list_recommendations_endpoint": "Idem assist_endpoint.",
    "apps.ai.api.data_query_ask_endpoint": (
        "Copilote donnees : chaque outil invoque est filtre individuellement par "
        "`data_query_tool_registry` (required_permission verifie via user.has_perm() "
        "AVANT d'exposer l'outil au LLM) — la protection reelle est au niveau outil, "
        "pas au niveau de cet endpoint d'entree."
    ),
    # docs/RBAC.md §1 : `chat` exclu par principe de ROLE_APP_PERMISSIONS —
    # messagerie interne transversale, pas une donnee metier sensible ;
    # seule l'appartenance au canal (verifiee dans apps.chat.services)
    # protege son contenu.
    "apps.chat.api.list_channels": (
        "Messagerie interne transversale, non sensible (docs/RBAC.md §1)."
    ),
    "apps.chat.api.list_messages": (
        "Idem list_channels ; portee au canal dont l'appartenance est verifiee en service."
    ),
    "apps.chat.api.create_message": "Idem list_channels.",
    # Portee intrinsequement limitee a l'utilisateur courant (`request.auth`) :
    # une permission de module n'aurait aucun sens, il n'y a rien a
    # restreindre en plus du "soi-meme".
    "apps.core.api_tenants.list_tenants": (
        "Tout utilisateur authentifie doit pouvoir lister SES PROPRES tenants."
    ),
    "apps.core.api_tenants.select_tenant": (
        "Idem list_tenants — selection parmi ses propres tenants."
    ),
    "apps.core.api_notifications.list_notifications": (
        "Notifications de l'utilisateur courant uniquement (filtre `user=request.auth`)."
    ),
    "apps.core.api_notifications.mark_notification_read": (
        "Idem — ne peut marquer lue qu'une notification lui appartenant."
    ),
    "apps.core.api_workflow.pending_approvals": (
        "`approvals.pending_for_user` filtre deja par role approbateur/delegation/"
        "escalade de l'utilisateur courant — rien a restreindre en plus."
    ),
    "apps.core.api_workflow.decide_approval": (
        "Protege par `approvals.decide()` -> `is_eligible_approver()` (verification "
        "data-dependante : role approbateur de la regle, delegation ou escalade — "
        "pas une permission statique par module). Leve PermissionDenied -> 403 sinon."
    ),
    # `services/search.py::global_search` filtre deja par tenant ET par
    # permission RBAC objet par objet (cf. sa docstring) avant de renvoyer
    # le moindre resultat.
    "apps.core.api_search.search": (
        "Filtre par tenant et par permission RBAC a l'interieur de "
        "`services/search.py::global_search`."
    ),
    # Squelette non implemente (Etape 11 a venir) : ne renvoie aujourd'hui
    # jamais rien d'autre qu'une liste vide, aucune donnee exposee. A
    # RETIRER de ce registre des que l'implementation reelle sera ecrite —
    # elle devra alors declarer une vraie permission.
    "apps.core.api_export_import.list_exports": (
        'Squelette non implemente : retourne toujours {"results": []}, aucune donnee exposee.'
    ),
    # Point de demonstration du mecanisme d'idempotence transversal — ne
    # lit ni n'ecrit aucune donnee metier, se contente de renvoyer le
    # payload recu.
    "apps.core.api_meta.echo": (
        "Demo du mecanisme d'idempotence ; ne lit/n'ecrit aucune donnee metier."
    ),
}
