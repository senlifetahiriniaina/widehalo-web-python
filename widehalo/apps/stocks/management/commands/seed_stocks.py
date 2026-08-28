"""Jeu de demonstration `stocks` (T10, couche 14 CDC — TST-3) : un entrepot,
un emplacement fournisseur (virtuel) + un emplacement interne, un mouvement
de reception cree puis valide (RG-STK-1 : materialise les deux `StkQuant`,
RG-STK-2 : cree une couche de valorisation) — meme discipline que
`apps.mrp.management.commands.seed_mrp`.

Comble le trou laisse par T10 premiere moitie (ferme avant que `stocks`
n'existe) : cree un utilisateur demo muni du role `magasinier` — le domaine
cible naturel de `stocks` (`ROLE_APP_PERMISSIONS["magasinier"]`, qui donne
aussi acces a `logistics`, cf. docstring de `rbac_policy`) — HORS
`settings.CORE_MFA_REQUIRED_ROLES`, pour un login JWT direct utilisable par
la campagne Schemathesis (cf. `tests/contract/test_openapi_schemathesis.
py`).

**Idempotence** : entrepot/emplacements crees directement via l'ORM (pas de
fonction `get_or_create`-friendly dans `services/warehouses.py`, cree ici
avec `Model.objects.get_or_create`) ; le mouvement de demonstration n'est
pas recree si un mouvement `done` existe deja entre ces deux emplacements
pour ce tenant."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandParser

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.rbac_policy import sync_group_permissions
from apps.core.tenant_context import activate_tenant
from apps.stocks.models import StkLocation, StkMove, StkWarehouse
from apps.stocks.services.moves import create_move, validate_move

DEMO_VARIANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000e01")


class Command(BaseCommand):
    help = (
        "Jeu de demonstration stocks (entrepot, emplacements, mouvement de "
        "reception valide) — prealable Schemathesis (T10)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant-code", default="DEMO")

    def handle(self, *args, **options) -> None:
        tenant_code = options["tenant_code"]

        tenant, _ = Tenant.objects.get_or_create(
            code=tenant_code, defaults={"name": "WideHalo Demo", "country_code": "MG"}
        )

        with activate_tenant(tenant.id):
            self._seed(tenant, tenant_code)

    def _seed(self, tenant: Tenant, tenant_code: str) -> None:
        user, was_created = User.objects.get_or_create(
            email=f"demo.magasinier@{tenant_code.lower()}.widehalo.local",
            defaults={"is_staff": False, "is_superuser": False},
        )
        if was_created:
            user.set_password("Str0ngPassw0rd!23")
            user.save(update_fields=["password"])
        group, _ = Group.objects.get_or_create(name="magasinier")
        sync_group_permissions(group, "magasinier")
        user.groups.add(group)

        warehouse, _ = StkWarehouse.objects.get_or_create(
            tenant=tenant, code="WH-DEMO", defaults={"name": "Entrepot principal (demo)"}
        )
        supplier_location, _ = StkLocation.objects.get_or_create(
            tenant=tenant,
            warehouse=warehouse,
            code="FRS-DEMO",
            defaults={"name": "Fournisseur (demo)", "type": StkLocation.TYPE_FOURNISSEUR},
        )
        internal_location, _ = StkLocation.objects.get_or_create(
            tenant=tenant,
            warehouse=warehouse,
            code="A1-DEMO",
            defaults={"name": "Rayon A1 (demo)", "type": StkLocation.TYPE_INTERNE},
        )

        move = StkMove.objects.filter(
            tenant=tenant,
            location_from=supplier_location,
            location_to=internal_location,
            state=StkMove.STATE_DONE,
        ).first()
        if move is None:
            move = create_move(
                tenant=tenant,
                variant_id=DEMO_VARIANT_ID,
                qty=Decimal(100),
                uom="m",
                location_from=supplier_location,
                location_to=internal_location,
                date=dt.date(2026, 3, 1),
                move_type=StkMove.TYPE_RECEPTION,
                unit_cost_mga=Decimal(2000),
                operator=user,
            )
            validate_move(move)

        self.stdout.write(
            self.style.SUCCESS(
                f"stocks: entrepot={warehouse.code}, mouvement={move.reference} "
                f"(etat={move.state})."
            )
        )
