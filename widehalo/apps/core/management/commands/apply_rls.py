"""Applique la Row-Level Security PostgreSQL sur toutes les tables dont le
modele herite de BaseModel (colonne tenant_id). Execute automatiquement en
fin de `migrate` (signal post_migrate, cf. apps/core/apps.py) pour qu'aucune
table future de module metier ne puisse etre oubliee.

`FORCE ROW LEVEL SECURITY` est indispensable : sans elle, le proprietaire de
la table (souvent le role de connexion en dev, ici `widehalo_app` — ni
superuser ni `BYPASSRLS`, cf. `pg_roles`) contournerait la policy.

**Exception generique disclosee (PJ14, `apps.projects.models.
PrjGuestAccess`)** : un modele peut porter l'attribut de classe
`RLS_FORCE_FOR_OWNER = False` pour demander explicitement `NO FORCE ROW
LEVEL SECURITY` plutot que `FORCE` (la policy `tenant_isolation_policy`
reste creee et ACTIVE — `ENABLE ROW LEVEL SECURITY` — pour tout role futur
qui ne serait ni superuser ni proprietaire, ex. un futur role de lecture
seule pour la replication/le reporting ; seul le contournement par le
PROPRIETAIRE de la table est autorise). Sans cette derogation, une table
dont la LIGNE ELLE-MEME sert de jeton d'authentification anonyme (portail
invite externe, aucune session/JWT prealable) serait structurellement
introuvable par SON PROPRE TOKEN tant qu'aucun tenant n'est actif — la
resolution du tenant CORRECT depuis le token n'aurait alors plus aucun
moyen de s'executer (contrainte de poule et l'oeuf verifiee empiriquement :
`ALTER TABLE ... FORCE ROW LEVEL SECURITY` bloque meme le proprietaire de
la table cote Postgres, `all_objects` cote Django ne suffit pas a lui seul
a contourner la RLS **base de donnees**, seulement la RLS **applicative**
de `TenantManager`). A n'utiliser QUE pour une table dont l'unique voie
d'ecriture applicative reste `tenant`-scopee (`services/guest_portal.py::
create_guest_access` ecrit toujours avec un `tenant` explicite) et dont la
lecture cross-tenant par le PROPRIETAIRE de la table reste, de toute
facon, filtree explicitement par le SERVICE appelant (jamais un simple
listing brut) — jamais a utiliser pour eviter de reflechir a l'isolation
d'une table de donnees metier ordinaire."""

from __future__ import annotations

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection

from apps.core.models.base import BaseModel

POLICY_NAME = "tenant_isolation_policy"


def _tenant_scoped_tables() -> list[tuple[str, bool]]:
    """Renvoie `(nom_table, force_pour_proprietaire)` pour chaque table
    tenant-scopee — `force_pour_proprietaire` vaut `True` sauf derogation
    explicite du modele (`RLS_FORCE_FOR_OWNER = False`, cf. docstring de
    module)."""
    tables = []
    for model in apps.get_models():
        if issubclass(model, BaseModel) and not model._meta.abstract:
            force = bool(getattr(model, "RLS_FORCE_FOR_OWNER", True))
            tables.append((model._meta.db_table, force))
    return tables


def apply_rls(verbose: bool = False) -> list[str]:
    if connection.vendor != "postgresql":
        return []
    applied = []
    with connection.cursor() as cursor:
        for table, force in _tenant_scoped_tables():
            cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            if force:
                cursor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            else:
                cursor.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
            cursor.execute(
                "SELECT 1 FROM pg_policies WHERE tablename = %s AND policyname = %s",
                [table, POLICY_NAME],
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    f'CREATE POLICY {POLICY_NAME} ON "{table}" '
                    "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
                )
            applied.append(table)
            if verbose:
                print(f"RLS applique sur {table}" + ("" if force else " (NO FORCE, derogation)"))
    return applied


class Command(BaseCommand):
    help = (
        "Active et applique la Row-Level Security PostgreSQL sur toutes les tables tenant-scoped."
    )

    def handle(self, *args, **options) -> None:
        applied = apply_rls(verbose=True)
        self.stdout.write(self.style.SUCCESS(f"RLS applique sur {len(applied)} table(s)."))
