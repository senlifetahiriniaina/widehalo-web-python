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

from apps.core.context import get_current_tenant_id, reset_current_tenant, set_current_tenant


@contextmanager
def activate_tenant(tenant_id: Any) -> Iterator[None]:
    """Active une societe pour la duree du bloc, puis RETABLIT celle qui
    precedait.

    **Retablir, et non remettre a zero — defaut trouve au sprint S6.** La
    version d'origine appelait `clear_current_tenant()` en sortie. Tant
    qu'`activate_tenant` n'etait employe qu'au premier niveau, cela
    revenait au meme. Des qu'un service qui BOUCLE sur les societes est
    appele depuis un contexte deja actif — une requete HTTP, dont le
    middleware a pose la societe, ou un test — la sortie du bloc imbrique
    laissait l'appelant SANS societe. Et `TenantManager` est
    deny-by-default : toute lecture suivante renvoyait un ensemble vide,
    sans erreur, sans journal, sans rien.

    Le defaut s'est manifeste sur la purge de charge utile de FLX-5 (un
    service qui boucle, appele depuis un test sous `use_tenant`), mais il
    ne lui appartient pas : `reporting.views`, `reporting.api` et toutes
    les boucles par societe du depot le portaient. Le contextvar rend un
    JETON precisement pour ca ; il n'etait pas utilise."""
    # La societe ENGLOBANTE, lue avant d'activer la nouvelle. Cote Django
    # et non cote PostgreSQL, et la nuance a coute un test rouge :
    # `current_setting('app.tenant_id')` peut porter le reliquat d'un bloc
    # DEJA SORTI — en test, ou pytest-django tient une transaction
    # englobante, le `SET LOCAL` d'un bloc de premier niveau survit a sa
    # sortie. Le contextvar, lui, est correctement porte : il dit ce qui
    # englobe REELLEMENT, jamais ce qui trainait.
    precedent = get_current_tenant_id()
    token = set_current_tenant(str(tenant_id))
    try:
        if connection.vendor == "postgresql":
            with transaction.atomic(), connection.cursor() as cursor:
                # Le reglage PostgreSQL se retablit lui aussi, et pour la
                # meme raison que le contextvar. `SET LOCAL` est porte par
                # la transaction : sur un bloc imbrique (donc un point de
                # sauvegarde), il n'est PAS repris au relachement, et la
                # session restait sur la societe INTERIEURE. Le filtre
                # Django disait alors une societe, la policy PostgreSQL une
                # autre, et l'appelant lisait un ensemble vide — sans
                # erreur. C'est sur, mais c'est muet, et muet est ce qu'on
                # ne veut pas.
                #
                # Uniquement le cas IMBRIQUE, et c'est une precision, pas
                # une timidite. Au premier niveau il n'y a rien a
                # retablir : le bloc atomique qui portait le `SET LOCAL`
                # se termine avec lui, et PostgreSQL oublie le reglage
                # tout seul. Retablir quand meme une chaine vide ne
                # changerait rien en production et couperait, en test —
                # ou pytest-django tient une transaction englobante — les
                # lectures qui passent par `_base_manager` (donc
                # `refresh_from_db`) apres la sortie du bloc. Ce serait
                # changer le contrat de tout le depot pour corriger un
                # defaut qui n'est pas la.
                cursor.execute("SET LOCAL app.tenant_id = %s", [str(tenant_id)])
                yield
                # Deux conditions avant de retablir, et chacune a coute un
                # test rouge.
                #
                # PAS dans un `finally` : si l'exception se propage,
                # l'annulation de la transaction reprend elle-meme les
                # `SET LOCAL` poses depuis le point de sauvegarde, et une
                # instruction de plus masquerait la cause.
                #
                # `needs_rollback` : le bloc a pu RATTRAPER une erreur de
                # base — c'est exactement ce que fait un test qui verifie
                # qu'une insertion inter-societes est refusee. La
                # transaction est alors avortee cote PostgreSQL, toute
                # instruction supplementaire leve, et l'annulation
                # retablira de toute facon le reglage.
                if precedent and not connection.needs_rollback:
                    cursor.execute("SET LOCAL app.tenant_id = %s", [precedent])
        else:
            yield
    finally:
        reset_current_tenant(token)
