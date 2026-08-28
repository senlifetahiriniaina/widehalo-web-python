"""Jeu de demonstration `purchase` (T10, couche 14 CDC — TST-3) : une
demande d'achat approuvee (avec une ligne), une commande d'achat avancee a
travers de vraies transitions FSM (soumise -> validee -> envoyee ->
confirmee), montant volontairement sous `LEVEL1_THRESHOLD_MGA` pour ne pas
declencher le routage d'approbation (PUR-ROUT1, hors-perimetre d'un jeu de
demonstration simple) — meme discipline que `apps.mrp.management.commands.
seed_mrp`.

Comble le trou laisse par T10 premiere moitie (ferme avant que `purchase`
n'existe) : le module etait jusqu'ici invisible a la campagne Schemathesis
(§8, couche 14), toujours route vers le jeton `resp_production` par defaut
(sans acces `purchase`, donc systematiquement 403). Ce seed cree un
utilisateur demo muni du role `acheteur` — le domaine cible naturel de
`purchase` (`ROLE_APP_PERMISSIONS["acheteur"]`) — et surtout HORS
`settings.CORE_MFA_REQUIRED_ROLES`, ce qui permet un vrai login JWT direct
pour la campagne de contrat (cf. `tests/contract/test_openapi_schemathesis.
py`).

**Idempotence** : entites de referentiel (variante catalogue) et le
document requisition/commande recuperes par cle naturelle
(`get_or_create`/filtre existant) — un second passage est un no-op."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandParser

from apps.catalog.models import ProductTemplate, ProductVariant, UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.rbac_policy import sync_group_permissions
from apps.core.tenant_context import activate_tenant
from apps.purchase.models import PurOrder, PurRequisition
from apps.purchase.services.orders import (
    confirm_order,
    create_order_from_requisition,
    send_order,
    submit_order_for_validation,
    validate_order,
)
from apps.purchase.services.requisitions import (
    add_requisition_line,
    approve_requisition,
    create_requisition,
    submit_requisition,
)

DEMO_PARTNER_ID = uuid.UUID("00000000-0000-0000-0000-000000000d01")


class Command(BaseCommand):
    help = (
        "Jeu de demonstration purchase (demande d'achat approuvee, commande "
        "d'achat confirmee) — prealable Schemathesis (T10)."
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
            email=f"demo.acheteur@{tenant_code.lower()}.widehalo.local",
            defaults={"is_staff": False, "is_superuser": False},
        )
        if was_created:
            user.set_password("Str0ngPassw0rd!23")
            user.save(update_fields=["password"])
        group, _ = Group.objects.get_or_create(name="acheteur")
        sync_group_permissions(group, "acheteur")
        user.groups.add(group)

        uom, _ = UnitOfMeasure.objects.get_or_create(
            tenant=tenant,
            code="M-PUR-DEMO",
            defaults={"name": "Metre (demo achat)", "category": UnitOfMeasure.CATEGORY_LENGTH},
        )
        template, _ = ProductTemplate.objects.get_or_create(
            tenant=tenant,
            reference="TPL-PUR-DEMO-0001",
            defaults={
                "name": "Fil polyester (demo achat)",
                "base_uom": uom,
                "base_price_mga": Decimal(2000),
            },
        )
        variant, _ = ProductVariant.objects.get_or_create(
            tenant=tenant, template=template, reference="VAR-PUR-DEMO-0001"
        )

        requisition = PurRequisition.objects.filter(
            tenant=tenant, requester=user, department="Production"
        ).first()
        if requisition is None:
            requisition = create_requisition(
                tenant=tenant,
                requester=user,
                department="Production",
                date_needed=dt.date(2026, 3, 1),
                justification="Reapprovisionnement fil polyester - jeu de demonstration.",
            )
            add_requisition_line(
                requisition,
                variant_id=variant.id,
                description="Fil polyester",
                qty=Decimal(200),
                uom="m",
            )
        if requisition.state == PurRequisition.STATE_DRAFT:
            submit_requisition(requisition)
        if requisition.state == PurRequisition.STATE_SUBMITTED:
            approve_requisition(requisition, approved_by=user)

        order = PurOrder.objects.filter(tenant=tenant, requisition=requisition).first()
        if order is None:
            order = create_order_from_requisition(requisition, partner_id=DEMO_PARTNER_ID)
        if order.state == PurOrder.STATE_DRAFT:
            submit_order_for_validation(order, user)
            validate_order(order, user)
            send_order(order, user)
            confirm_order(order, user)

        self.stdout.write(
            self.style.SUCCESS(
                f"purchase: requisition={requisition.reference} (etat={requisition.state}), "
                f"commande={order.reference} (etat={order.state})."
            )
        )
