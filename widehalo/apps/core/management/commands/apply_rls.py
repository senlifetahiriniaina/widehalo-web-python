"""Applique la Row-Level Security PostgreSQL sur toutes les tables dont le
modele herite de BaseModel (colonne tenant_id). Execute automatiquement en
fin de `migrate` (signal post_migrate, cf. apps/core/apps.py) pour qu'aucune
table future de module metier ne puisse etre oubliee.

`FORCE ROW LEVEL SECURITY` est indispensable : sans elle, le proprietaire de
la table (souvent le role de connexion en dev) contournerait la policy.
"""

from __future__ import annotations

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection

from apps.core.models.base import BaseModel

POLICY_NAME = "tenant_isolation_policy"


def _tenant_scoped_tables() -> list[str]:
    tables = []
    for model in apps.get_models():
        if issubclass(model, BaseModel) and not model._meta.abstract:
            tables.append(model._meta.db_table)
    return tables


def apply_rls(verbose: bool = False) -> list[str]:
    if connection.vendor != "postgresql":
        return []
    applied = []
    with connection.cursor() as cursor:
        for table in _tenant_scoped_tables():
            cursor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            cursor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
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
                print(f"RLS applique sur {table}")
    return applied


class Command(BaseCommand):
    help = (
        "Active et applique la Row-Level Security PostgreSQL sur toutes les tables tenant-scoped."
    )

    def handle(self, *args, **options) -> None:
        applied = apply_rls(verbose=True)
        self.stdout.write(self.style.SUCCESS(f"RLS applique sur {len(applied)} table(s)."))
