"""Jeu de demonstration `accounting` (T10, CDC §8 couche 14 — prealable a
Schemathesis) : un tenant avec plan comptable PCG2005 charge, un exercice
ouvert avec sa periode de janvier, un journal de ventes et un journal de
banque, 3 factures client a des `invoice_state` differents (brouillon,
validee, payee partiellement — cette derniere avec un paiement enregistre et
lettre), et un utilisateur de demonstration muni du role `comptable` (seul
role avec acces `view/add/change` complet a `accounting` + les permissions
personnalisees `validate_accmove`/`cancel_accmove`, cf.
`apps.core.services.rbac_policy.ROLE_APP_PERMISSIONS`/`CUSTOM_PERMISSIONS`)
pour exercer l'API accounting de bout en bout.

Idempotence : la configuration (tenant, comptes PCG2005, exercice, periode,
journaux, utilisateur demo, seuils d'approbation) est creee via
`get_or_create`/fonctions deja idempotentes du module — rejouer la commande
ne duplique jamais ces lignes. Le jeu de 3 factures de demonstration, lui,
N'EST PAS recree si au moins une facture client existe deja dans le journal
de ventes de ce tenant (choix assume : plus simple qu'un marqueur dedie, et
suffisant puisque Schemathesis n'a besoin que d'un jeu d'etats stable, pas
d'un jeu qui grossit a chaque execution)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandParser

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccMove, AccPeriod
from apps.accounting.services.chart_of_accounts import load_pcg2005
from apps.accounting.services.invoices import (
    create_invoice,
    ensure_default_approval_thresholds,
    validate_invoice,
)
from apps.accounting.services.payments import register_payment
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.rbac_policy import sync_group_permissions
from apps.core.services.smart_defaults import apply_country_defaults
from apps.core.tenant_context import activate_tenant

DEMO_USER_EMAIL = "comptable.demo@widehalo.local"
DEMO_USER_PASSWORD = "DemoAccounting#2026!"  # noqa: S105 - compte de demonstration, jamais en production


class Command(BaseCommand):
    help = (
        "Cree un jeu de demonstration coherent pour le module accounting "
        "(plan comptable PCG2005, exercice/periode/journaux, 3 factures "
        "client en draft/validated/paid_partially avec paiement et lettrage, "
        "utilisateur demo muni du role comptable). Idempotent pour la "
        "configuration (get_or_create) ; les 3 factures de demonstration ne "
        "sont recreees que si le journal de ventes n'en contient encore "
        "aucune (voir docstring du module)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--tenant-code", default="DEMO", help="Code du tenant a creer/reutiliser."
        )

    def handle(self, *args, **options) -> None:
        tenant_code = options["tenant_code"]
        tenant, tenant_created = Tenant.objects.get_or_create(
            code=tenant_code,
            defaults={
                "name": "Societe demonstration WideHalo",
                "country_code": "MG",
                "fiscal_regime": Tenant.FISCAL_REGIME_REAL_WITH_VAT,
            },
        )
        if tenant_created:
            apply_country_defaults(tenant, "MG")

        with activate_tenant(tenant.id):
            accounts_created = load_pcg2005(tenant)

            fiscal_year, _ = AccFiscalYear.objects.get_or_create(
                tenant=tenant,
                code="FY2026",
                defaults={"date_start": dt.date(2026, 1, 1), "date_end": dt.date(2026, 12, 31)},
            )
            period, _ = AccPeriod.objects.get_or_create(
                tenant=tenant,
                fiscal_year=fiscal_year,
                code="2026-01",
                defaults={"date_start": dt.date(2026, 1, 1), "date_end": dt.date(2026, 1, 31)},
            )
            sale_journal, _ = AccJournal.objects.get_or_create(
                tenant=tenant,
                code="VTE",
                defaults={
                    "name": "Ventes",
                    "type": AccJournal.TYPE_SALE,
                    "sequence_prefix": "VTE",
                },
            )
            bank_journal, _ = AccJournal.objects.get_or_create(
                tenant=tenant,
                code="BQ1",
                defaults={
                    "name": "Banque",
                    "type": AccJournal.TYPE_BANK,
                    "sequence_prefix": "BQ1",
                },
            )

            receivable = AccAccount.objects.get(tenant=tenant, code="411")
            income = AccAccount.objects.get(tenant=tenant, code="701")
            cash = AccAccount.objects.get(tenant=tenant, code="512")
            # Comptes d'ecart de change : non fournis par le PCG2005 simplifie,
            # crees ici en config annexe (jamais exerces reellement puisque le
            # jeu de demonstration ne facture qu'en MGA = devise de base).
            gain_account, _ = AccAccount.objects.get_or_create(
                tenant=tenant,
                code="766",
                defaults={
                    "name": "Gains de change",
                    "account_class": 7,
                    "type": AccAccount.TYPE_INCOME,
                },
            )
            loss_account, _ = AccAccount.objects.get_or_create(
                tenant=tenant,
                code="666",
                defaults={
                    "name": "Pertes de change",
                    "account_class": 6,
                    "type": AccAccount.TYPE_EXPENSE,
                },
            )

            ensure_default_approval_thresholds(tenant)

            demo_user, user_created = User.objects.get_or_create(
                email=DEMO_USER_EMAIL,
                defaults={"first_name": "Demo", "last_name": "Comptable"},
            )
            if user_created:
                demo_user.set_password(DEMO_USER_PASSWORD)
                demo_user.save(update_fields=["password"])
            group, _ = Group.objects.get_or_create(name="comptable")
            sync_group_permissions(group, "comptable")
            demo_user.groups.add(group)

            invoices_created = 0
            if not AccMove.objects.filter(
                tenant=tenant, journal=sale_journal, move_type=AccMove.TYPE_CUSTOMER_INVOICE
            ).exists():
                # Facture 1 : brouillon, jamais validee.
                create_invoice(
                    tenant=tenant,
                    journal=sale_journal,
                    period=period,
                    date=dt.date(2026, 1, 10),
                    partner_id=uuid.uuid4(),
                    receivable_account=receivable,
                    income_lines=[
                        {
                            "account": income,
                            "amount": Decimal("350000"),
                            "label": "Vente tissus (brouillon)",
                        }
                    ],
                )
                invoices_created += 1

                # Facture 2 : validee (publiee), en dessous du seuil de
                # double validation (2M Ar) donc validee directement.
                invoice_validated = create_invoice(
                    tenant=tenant,
                    journal=sale_journal,
                    period=period,
                    date=dt.date(2026, 1, 15),
                    partner_id=uuid.uuid4(),
                    receivable_account=receivable,
                    income_lines=[
                        {
                            "account": income,
                            "amount": Decimal("900000"),
                            "label": "Vente confection",
                        }
                    ],
                )
                validate_invoice(invoice_validated, demo_user)
                invoices_created += 1

                # Facture 3 : validee puis payee partiellement (paiement +
                # lettrage reel via register_payment()).
                invoice_partial = create_invoice(
                    tenant=tenant,
                    journal=sale_journal,
                    period=period,
                    date=dt.date(2026, 1, 20),
                    partner_id=uuid.uuid4(),
                    receivable_account=receivable,
                    income_lines=[
                        {
                            "account": income,
                            "amount": Decimal("1200000"),
                            "label": "Vente EPI textile",
                        }
                    ],
                )
                validate_invoice(invoice_partial, demo_user)
                register_payment(
                    invoice=invoice_partial,
                    period=period,
                    journal=bank_journal,
                    cash_account=cash,
                    gain_account=gain_account,
                    loss_account=loss_account,
                    date=dt.date(2026, 1, 25),
                    amount=Decimal("500000"),
                    method="virement",
                    reference_external="VIR-DEMO-0001",
                )
                invoices_created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"accounting seed OK — tenant={tenant.code} "
                f"comptes_pcg2005_crees={accounts_created} factures_demo_creees={invoices_created} "
                f"utilisateur_demo={DEMO_USER_EMAIL} (role comptable)"
            )
        )
