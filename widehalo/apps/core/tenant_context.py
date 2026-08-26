"""Activation explicite du contexte tenant (contextvar applicatif + session
Postgres pour la Row-Level Security) en dehors du cycle de requete HTTP
normalement gere par `TenantMiddleware` — necessaire pour les operations
administratives inter-tenant (sandbox, migrations de donnees, commandes de
management) qui doivent ecrire dans un tenant precis sans passer par une
requete web.

Point d'attention Postgres important : `SET LOCAL` n'a d'effet que pour la
transaction EN COURS. En dehors d'un bloc atomique explicite, Django (comme
Postgres) traite chaque instruction comme sa propre transaction implicite
(autocommit) : le `SET LOCAL` serait alors immediatement perdu avant meme
la requete suivante, ce qui viderait la RLS de tout effet reel. On englobe
donc systematiquement le `SET LOCAL` et le bloc appelant dans un
`transaction.atomic()` pour garantir que le reglage tient pour toute la
duree du bloc `with activate_tenant(...):`, quel que soit l'appelant
(vue HTTP hors ATOMIC_REQUESTS, commande de management, tache Django-Q2,
consumer WebSocket asynchrone...)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from django.db import connection, transaction

from apps.core.context import clear_current_tenant, set_current_tenant


@contextmanager
def activate_tenant(tenant_id: Any) -> Iterator[None]:
    set_current_tenant(str(tenant_id))
    try:
        if connection.vendor == "postgresql":
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute("SET LOCAL app.tenant_id = %s", [str(tenant_id)])
                yield
        else:
            yield
    finally:
        clear_current_tenant()
