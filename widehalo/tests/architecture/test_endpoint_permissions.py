"""Garde-fou bloquant : cahier des charges WideHalo v3, Phase 1, §6.4 —
« Decoration obligatoire de tout endpoint ; test de CI listant les
endpoints sans declarations de permission et faisant echouer la
construction ». Ecart confirme par l'audit
`docs/audit/2026-09-cahier-des-charges-v3-audit.md` (§9) : ce garde-fou
n'existait pas avant ce test.

Tout endpoint django-ninja qui exige une authentification (n'a pas
explicitement `auth=None`) doit soit etre garde par
`require_permission`/`require_superuser`
(`apps.core.services.permissions`), soit figurer dans le registre
explicite et documente `apps.core.services.endpoint_governance.
INTENTIONALLY_OPEN_ENDPOINTS`. Un nouvel endpoint qui omet les deux
echoue la construction — exactement le comportement demande par le
cahier des charges."""

from __future__ import annotations

from ninja.constants import NOT_SET

from apps.core.services.endpoint_governance import INTENTIONALLY_OPEN_ENDPOINTS
from apps.core.services.permissions import _PermissionGuardedView, _SuperuserGuardedView


def _all_operations() -> list[tuple[str, list[str], object]]:
    """Une entree par (path, methodes, view_func) pour chaque operation
    django-ninja reellement enregistree — meme source que
    `tests.architecture.test_budget._counted_endpoints`, pour ne jamais
    diverger sur ce qui compte comme un "endpoint"."""
    from config.api import api

    operations: list[tuple[str, list[str], object]] = []
    for _prefix, router in api._routers:
        for path_view in router.path_operations.values():
            for op in path_view.operations:
                operations.append((op.path, list(op.methods), op))
    return operations


def _qualname(view_func: object) -> str:
    module = getattr(view_func, "__module__", "?")
    qualname = getattr(view_func, "__qualname__", getattr(view_func, "__name__", "?"))
    return f"{module}.{qualname}"


def test_every_authenticated_endpoint_declares_a_permission() -> None:
    violations: list[str] = []
    seen_registry_keys: set[str] = set()

    for path, methods, op in _all_operations():
        is_explicitly_public = op.auth_param is None or op.auth_param is False
        if is_explicitly_public:
            continue

        view_func = op.view_func
        is_guarded = isinstance(view_func, (_PermissionGuardedView, _SuperuserGuardedView))
        if is_guarded:
            continue

        key = _qualname(view_func)
        if key in INTENTIONALLY_OPEN_ENDPOINTS:
            seen_registry_keys.add(key)
            continue

        violations.append(f"{'/'.join(methods)} {path} -> {key}")

    assert not violations, (
        "Endpoint(s) authentifie(s) sans require_permission/require_superuser ni "
        "entree dans apps.core.services.endpoint_governance."
        "INTENTIONALLY_OPEN_ENDPOINTS (cahier Phase 1 §6.4) :\n"
        + "\n".join(sorted(violations))
    )

    # Registre a jour : une entree qui ne correspond plus a AUCUN endpoint
    # reel (module renomme/retire) doit etre nettoyee, pas laissee comme
    # une exemption fantome qui masquerait un futur oubli sur le meme nom.
    stale = set(INTENTIONALLY_OPEN_ENDPOINTS) - seen_registry_keys
    assert not stale, (
        "Entree(s) obsolete(s) dans INTENTIONALLY_OPEN_ENDPOINTS (aucun endpoint "
        "authentifie correspondant n'existe plus) : " + ", ".join(sorted(stale))
    )


def test_not_set_sentinel_still_imported() -> None:
    # Garde-fou de non-regression sur l'API interne de django-ninja
    # utilisee ci-dessus (`op.auth_param`) : si une mise a jour de
    # django-ninja retire/renomme `NOT_SET`, ce test echoue avant le test
    # principal plutot que de le laisser silencieusement classer tous les
    # endpoints comme publics.
    assert NOT_SET is not None
