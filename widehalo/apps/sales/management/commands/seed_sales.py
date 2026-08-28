"""Jeu de demonstration `sales` (T10, couche 14 CDC — TST-3) : un devis
avec une ligne, envoye puis accepte puis converti en commande de vente
(`create_order_from_quotation`), la commande resultante avancee jusqu'a
`confirmed` via une vraie transition FSM — meme discipline que
`apps.mrp.management.commands.seed_mrp`.

Comble le trou laisse par T10 premiere moitie (ferme avant que `sales`
n'existe) : reutilise l'utilisateur demo `demo.commercial@...` deja cree par
`seed_core` (role `commercial`, qui a deja acces `sales` en plus de
`crm`/`partners` — cf. `ROLE_APP_PERMISSIONS`, aucun nouvel utilisateur
demo necessaire ici, a la difference de `seed_purchase`/`seed_stocks`).

**Idempotence** : le devis de demonstration n'est pas recree si un devis
`accepted` existe deja pour ce vendeur/tenant ; la commande resultante est
recuperee via `SalesOrder.quotation` plutot que recreee."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandParser

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tenant_context import activate_tenant
from apps.sales.models import SalesOrder, SalesQuotation
from apps.sales.services.orders import confirm_order, create_order_from_quotation
from apps.sales.services.quotations import accept_quotation, add_quotation_line, create_quotation
from apps.sales.services.quotations import send_quotation as _send_quotation

DEMO_PARTNER_ID = uuid.UUID("00000000-0000-0000-0000-000000000f01")


class Command(BaseCommand):
    help = (
        "Jeu de demonstration sales (devis accepte converti en commande "
        "confirmee) — prealable Schemathesis (T10)."
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
        user, _ = User.objects.get_or_create(
            email=f"demo.commercial@{tenant_code.lower()}.widehalo.local",
            defaults={"is_staff": False, "is_superuser": False},
        )

        quotation = SalesQuotation.objects.filter(
            tenant=tenant,
            partner_id=DEMO_PARTNER_ID,
            state__in=[SalesQuotation.STATE_ACCEPTED, SalesQuotation.STATE_SENT],
        ).first()
        if quotation is None:
            quotation = create_quotation(
                tenant=tenant,
                partner_id=DEMO_PARTNER_ID,
                date=dt.date(2026, 3, 1),
                salesperson=user,
            )
            add_quotation_line(
                quotation,
                description="T-shirt coton bio (demo)",
                qty=Decimal(50),
                unit_price=Decimal(15000),
                is_custom=True,
            )
        if quotation.state == SalesQuotation.STATE_DRAFT:
            _send_quotation(quotation)
        if quotation.state == SalesQuotation.STATE_SENT:
            accept_quotation(quotation)

        order = SalesOrder.objects.filter(tenant=tenant, quotation=quotation).first()
        if order is None:
            order = create_order_from_quotation(quotation)
        if order.state == SalesOrder.STATE_DRAFT:
            confirm_order(order, user)

        self.stdout.write(
            self.style.SUCCESS(
                f"sales: devis={quotation.reference} (etat={quotation.state}), "
                f"commande={order.reference} (etat={order.state})."
            )
        )
