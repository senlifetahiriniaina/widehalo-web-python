"""Jeu de demonstration `mrp` (T10, couche 14 CDC — TST-3) : atelier +
poste de charge + operation + gamme, une nomenclature ACTIVE (creee ->
lignes ajoutees -> activee, via les vraies fonctions de service pour que la
regle d'immutabilite RG-MRP-5 soit reellement exercee), un ordre de
fabrication avance a travers de vraies transitions FSM
(confirme -> reserve -> demarre), un CRA cree+soumis+valide, un CRI et une
declaration de rebut.

**Idempotence** : les entites "referentiel" (atelier/poste/operation/gamme/
nomenclature) sont recuperees par `get_or_create` sur leur code naturel.
L'ordre de fabrication en revanche a un cycle de vie a etat (FSM) qui ne se
"retrouve" pas naturellement : relancer cette commande recupere l'ordre de
demo existant par sa `reference` stockee sur le premier passage et NE
rejoue PAS les transitions si l'ordre a deja depasse l'etat "draft" — un
second passage est donc un no-op sur l'ordre/CRA/CRI/rebut (pas de lignes
supplementaires), documente ainsi plutot que de forcer un nouvel ordre a
chaque execution.

Peut etre lance seul (cree son propre tenant/utilisateur via
`get_or_create` si `seed_core` n'a pas ete execute d'abord)."""

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
from apps.mrp.models import (
    MrpBom,
    MrpCra,
    MrpOperation,
    MrpOrder,
    MrpRouting,
    MrpRoutingStep,
    MrpWorkcenter,
    MrpWorkshop,
)
from apps.mrp.services.bom import activate_bom, add_bom_line, create_bom
from apps.mrp.services.cra import create_cra, submit_cra, validate_cra
from apps.mrp.services.interventions import create_cri, declare_scrap
from apps.mrp.services.orders import confirm_order, create_order, reserve_order, start_order

DEMO_PRODUCT_TEMPLATE_ID = uuid.UUID("00000000-0000-0000-0000-000000000c01")
DEMO_COMPONENT_TEMPLATE_ID = uuid.UUID("00000000-0000-0000-0000-000000000c02")


class Command(BaseCommand):
    help = (
        "Jeu de demonstration mrp (atelier, gamme, nomenclature active, ordre de "
        "fabrication, CRA/CRI/rebut) — prealable Schemathesis (T10)."
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
            email=f"demo.production@{tenant_code.lower()}.widehalo.local",
            defaults={"is_staff": False, "is_superuser": False},
        )
        if was_created:
            user.set_password("Str0ngPassw0rd!23")
            user.save(update_fields=["password"])
        group, _ = Group.objects.get_or_create(name="resp_production")
        sync_group_permissions(group, "resp_production")
        user.groups.add(group)

        workshop, _ = MrpWorkshop.objects.get_or_create(
            tenant=tenant,
            code="ATL-COUTURE",
            defaults={"name": "Atelier Couture Antananarivo", "capacity_hours_day": Decimal(8)},
        )
        cutting_center, _ = MrpWorkcenter.objects.get_or_create(
            tenant=tenant,
            workshop=workshop,
            code="WC-COUPE",
            defaults={
                "name": "Poste de coupe",
                "type": MrpWorkcenter.TYPE_CUTTING,
                "cost_per_hour_mga": Decimal("8000"),
            },
        )
        sewing_center, _ = MrpWorkcenter.objects.get_or_create(
            tenant=tenant,
            workshop=workshop,
            code="WC-COUTURE",
            defaults={
                "name": "Poste de couture",
                "type": MrpWorkcenter.TYPE_SEWING,
                "cost_per_hour_mga": Decimal("6000"),
            },
        )

        operation, _ = MrpOperation.objects.get_or_create(
            tenant=tenant,
            code="OP-ASSEMBLAGE",
            defaults={
                "name": "Assemblage chemise",
                "workcenter_type": MrpWorkcenter.TYPE_SEWING,
                "default_duration_min": 45,
            },
        )

        routing, _ = MrpRouting.objects.get_or_create(
            tenant=tenant,
            code="GAM-CHEMISE",
            defaults={
                "name": "Gamme chemise standard",
                "product_template_id": DEMO_PRODUCT_TEMPLATE_ID,
            },
        )
        MrpRoutingStep.objects.get_or_create(
            tenant=tenant,
            routing=routing,
            sequence=1,
            defaults={
                "operation": operation,
                "workcenter": sewing_center,
                "duration_min": 45,
            },
        )

        bom = MrpBom.objects.filter(
            tenant=tenant, product_template_id=DEMO_PRODUCT_TEMPLATE_ID, state=MrpBom.STATE_ACTIVE
        ).first()
        if bom is None:
            bom = create_bom(
                tenant=tenant,
                code="BOM-CHEMISE",
                product_template_id=DEMO_PRODUCT_TEMPLATE_ID,
                qty=Decimal(1),
                uom_code="unite",
                routing=routing,
            )
            add_bom_line(
                bom,
                component_template_id=DEMO_COMPONENT_TEMPLATE_ID,
                qty=Decimal("1.2"),
                uom_code="m",
                waste_pct=Decimal(5),
                qty_by_size={"S": "1.10", "M": "1.20", "L": "1.35"},
                operation=operation,
            )
            activate_bom(bom)

        order = MrpOrder.objects.filter(tenant=tenant, bom=bom, workshop=workshop).first()
        if order is None:
            order = create_order(
                tenant=tenant,
                bom=bom,
                workshop=workshop,
                qty=Decimal(20),
                uom_code="unite",
            )
        if order.state == MrpOrder.STATE_DRAFT:
            confirm_order(order, user)
            reserve_order(order, user)
            start_order(order, user)

        cra = MrpCra.objects.filter(tenant=tenant, employee=user, order=order).first()
        if cra is None:
            cra = create_cra(
                tenant=tenant,
                employee=user,
                workshop=workshop,
                date=dt.date(2026, 1, 15),
                hours=Decimal("7.5"),
                order=order,
                qty_done=Decimal(18),
                qty_rejected=Decimal(2),
                activity_type="couture",
                comment="Journee de production standard - jeu de demonstration.",
            )
        if cra.state == MrpCra.STATE_DRAFT:
            submit_cra(cra, user)
            validate_cra(cra, user)

        if not order.cri_entries.exists():
            create_cri(
                tenant=tenant,
                type="panne",
                workcenter=sewing_center,
                date=dt.date(2026, 1, 15),
                order=order,
                intervenant_user=user,
                duration_min=30,
                description="Reglage machine a coudre - jeu de demonstration.",
                downtime_min=15,
            )

        if not order.scraps.exists():
            declare_scrap(
                order,
                declared_by=user,
                qty=Decimal(2),
                reason="Defaut de couture - jeu de demonstration.",
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"mrp: atelier={workshop.code}, BOM active={bom.code} v{bom.version}, "
                f"ordre={order.reference} (etat={order.state}), CRA/CRI/rebut verifies."
            )
        )
