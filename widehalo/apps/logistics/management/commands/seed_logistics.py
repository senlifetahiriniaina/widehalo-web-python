"""Jeu de demonstration `logistics` (T10, couche 14 CDC — TST-3) : un
transporteur, une expedition avancee a travers de vraies transitions FSM
(reservee -> enlevee -> en transit) — meme discipline que
`apps.mrp.management.commands.seed_mrp`.

Comble le trou laisse par T10 premiere moitie (ferme avant que `logistics`
n'existe) : reutilise le meme utilisateur demo `magasinier` que
`seed_stocks` (`get_or_create` sur l'email — le role `magasinier` a deja
acces `logistics` en plus de `stocks`, cf. docstring de `rbac_policy`) —
peut donc etre lance seul (cree son propre utilisateur si `seed_stocks` n'a
pas ete execute d'abord) ou apres, sans doublon.

**Idempotence** : transporteur recupere par `get_or_create` sur son code
naturel ; l'expedition de demonstration n'est pas recree si une expedition
`in_transit` existe deja pour ce transporteur/tenant."""

from __future__ import annotations

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.rbac_policy import sync_group_permissions
from apps.core.tenant_context import activate_tenant
from apps.logistics.models import LogServiceProvider, LogShipment
from apps.logistics.services.freight import create_service_provider
from apps.logistics.services.shipments import (
    book_shipment,
    create_shipment,
    mark_shipment_in_transit,
    pick_up_shipment,
)
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandParser


class Command(BaseCommand):
    help = (
        "Jeu de demonstration logistics (transporteur, expedition en "
        "transit) — prealable Schemathesis (T10)."
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

        carrier = LogServiceProvider.objects.filter(tenant=tenant, code="CAR-DEMO").first()
        if carrier is None:
            carrier = create_service_provider(
                tenant, code="CAR-DEMO", name="Transporteur maritime (demo)"
            )

        shipment = LogShipment.objects.filter(
            tenant=tenant, carrier=carrier, state=LogShipment.STATE_IN_TRANSIT
        ).first()
        if shipment is None:
            shipment = create_shipment(
                tenant, origin="Guangzhou", destination="Toamasina", carrier=carrier
            )
            book_shipment(shipment, user)
            pick_up_shipment(shipment, user)
            mark_shipment_in_transit(shipment, user)

        self.stdout.write(
            self.style.SUCCESS(
                f"logistics: transporteur={carrier.code}, expedition={shipment.reference} "
                f"(etat={shipment.state})."
            )
        )
