"""Comment une requete designe sa societe — et comment un module peut en
ajouter un moyen sans que `core` le connaisse.

`TenantMiddleware` en connait deux depuis la Phase 1 : l'en-tete
`X-Tenant-Id` et la session. L'API publique en apporte un troisieme — la
CLE elle-meme designe sa societe — et il ne peut pas etre code dans le
middleware : `core` est le socle, il n'importe aucun module metier
(regle de couplage n°1), et `apps.flows` est un module.

**Meme patron que partout ailleurs dans ce depot** : un registre en
memoire, alimente depuis `apps.py::ready()` — comme les rapports, les
anomalies, les commandes periodiques, les adaptateurs de flux et les
operations publiques. Le sens de la dependance s'inverse : ce n'est pas
`core` qui va chercher `flows`, c'est `flows` qui se declare a `core`.

**Ordre de consultation, et pourquoi il n'est pas indifferent.** L'en-tete
et la session d'abord, les resolveurs ensuite. Une session ouverte
appartient a un humain qui a choisi sa societe ; une cle d'API appartient a
un integrateur. Si les deux etaient presents — un developpeur qui essaie
l'API publique depuis son navigateur connecte — c'est le choix explicite de
l'humain qui doit primer, sans quoi la page qu'il regarde changerait de
societe sous ses yeux.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

#: Un resolveur : une requete, un identifiant de societe ou rien.
TenantResolver = Callable[[Any], str | None]

_RESOLVERS: list[TenantResolver] = []


def register_tenant_resolver(resolver: TenantResolver) -> None:
    """Declare un moyen supplementaire de designer une societe.

    Idempotent sur l'identite de la fonction : `ready()` peut etre appele
    deux fois en developpement (rechargement automatique) sans empiler deux
    fois le meme resolveur."""
    if resolver not in _RESOLVERS:
        _RESOLVERS.append(resolver)


def resolve_tenant_from_request(request: Any) -> str | None:
    """Le premier resolveur qui reconnait la requete l'emporte.

    Un resolveur qui LEVE est ignore, et c'est deliberé : il s'execute dans
    le middleware, avant toute vue, et une exception y transformerait un
    moyen d'authentification optionnel en panne generale du produit. Un
    resolveur cassé prive de son propre canal, pas des deux autres."""
    for resolver in _RESOLVERS:
        try:
            tenant_id = resolver(request)
        except Exception:  # noqa: BLE001 - un résolveur cassé ne coupe pas le produit
            import logging

            logging.getLogger(__name__).exception(
                "Résolveur de société en échec ; la requête continue sans lui."
            )
            continue
        if tenant_id:
            return str(tenant_id)
    return None


def registered_resolver_count() -> int:
    """Pour les gardes et les tests : un registre vide se constate plutot
    qu'il ne se suppose."""
    return len(_RESOLVERS)


__all__ = [
    "TenantResolver",
    "register_tenant_resolver",
    "registered_resolver_count",
    "resolve_tenant_from_request",
]
