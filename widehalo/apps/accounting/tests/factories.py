"""Factories factory_boy pour les modeles du module `accounting` — une par
modele concret, pour amorcer les tests (couche T1 du plan de durcissement,
CDC §14 couches).

`tenant` est toujours resolu via un `SubFactory` a chemin pointe vers
`apps.core.tests.factories.TenantFactory` : la resolution factory_boy est
paresseuse (import differe a l'instanciation reelle), ce qui fonctionne
meme si ce module est ecrit en parallele par un autre agent. Les sous-objets
d'un meme graphe (ex. `AccMove.journal`/`period`) partagent systematiquement
le tenant du parent via `factory.SelfAttribute("..tenant")`.

Aucune reference cross-app (`partner_id`, etc.) n'est un FK Django — toujours
un UUID genere via `factory.LazyFunction(uuid.uuid4)`, jamais un objet cree
dans une autre app (regle de couplage n°1 du CDC)."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import factory

from apps.accounting.models import (
    AccAccount,
    AccAnalyticAccount,
    AccAnalyticLine,
    AccAnalyticPlan,
    AccAsset,
    AccAssetDepreciation,
    AccAssetMovement,
    AccBankStatementLine,
    AccBudget,
    AccBudgetLine,
    AccDcomDeclaration,
    AccDcomLine,
    AccDunningAction,
    AccDunningLevel,
    AccExchangeRate,
    AccFiscalYear,
    AccIrcmDeclaration,
    AccJournal,
    AccLocalTax,
    AccMobileMoneyStatementLine,
    AccMove,
    AccMoveLine,
    AccPayment,
    AccPaymentAllocation,
    AccPaymentTerm,
    AccPaymentTermLine,
    AccPeriod,
    AccProvision,
    AccReconcileRule,
    AccTax,
    AccTaxCalendar,
)


class AccFiscalYearFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccFiscalYear

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"FY{2020 + n}")
    date_start = datetime.date(2026, 1, 1)
    date_end = datetime.date(2026, 12, 31)


class AccPeriodFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccPeriod

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    fiscal_year = factory.SubFactory(AccFiscalYearFactory, tenant=factory.SelfAttribute("..tenant"))
    code = factory.Sequence(lambda n: f"2026-{(n % 12) + 1:02d}")
    date_start = datetime.date(2026, 1, 1)
    date_end = datetime.date(2026, 1, 31)


class AccAccountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccAccount

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"6{n:04d}")
    name = factory.Sequence(lambda n: f"Compte {n}")
    account_class = 6
    type = AccAccount.TYPE_EXPENSE


class AccJournalFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccJournal

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"JRN{n}")
    name = factory.Sequence(lambda n: f"Journal {n}")
    type = AccJournal.TYPE_SALE
    sequence_prefix = "INV"


class AccMoveFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccMove

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    journal = factory.SubFactory(AccJournalFactory, tenant=factory.SelfAttribute("..tenant"))
    period = factory.SubFactory(AccPeriodFactory, tenant=factory.SelfAttribute("..tenant"))
    date = datetime.date(2026, 1, 15)
    move_type = AccMove.TYPE_ENTRY
    # `state`/`invoice_state` restent aux valeurs par defaut du modele
    # (draft) — ne jamais appeler une methode @transition depuis une
    # factory (RG-ACC-1..4 : le workflow est gouverne par les services).


class AccTaxFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccTax

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"TVA{n}")
    name = factory.Sequence(lambda n: f"Taxe {n}")
    type = AccTax.TYPE_SALE
    rate = Decimal("20.000")


class AccPaymentTermFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccPaymentTerm

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Condition {n}")


class AccPaymentTermLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccPaymentTermLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    term = factory.SubFactory(AccPaymentTermFactory, tenant=factory.SelfAttribute("..tenant"))
    value_type = AccPaymentTermLine.VALUE_TYPE_BALANCE
    days = 30


class AccExchangeRateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccExchangeRate

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    currency = "USD"
    date = factory.Sequence(lambda n: datetime.date(2026, 1, 1) + datetime.timedelta(days=n))
    rate_to_mga = Decimal("4500.000000")


class AccMoveLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccMoveLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    move = factory.SubFactory(AccMoveFactory, tenant=factory.SelfAttribute("..tenant"))
    account = factory.SubFactory(AccAccountFactory, tenant=factory.SelfAttribute("..tenant"))
    label = factory.Sequence(lambda n: f"Ligne {n}")
    debit = Decimal("100.0000")
    credit = Decimal("0.0000")


class AccPaymentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccPayment

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    journal = factory.SubFactory(AccJournalFactory, tenant=factory.SelfAttribute("..tenant"))
    date = datetime.date(2026, 1, 20)
    amount = Decimal("1000.0000")
    direction = AccPayment.DIRECTION_INBOUND
    method = AccPayment.METHOD_CASH
    partner_id = factory.LazyFunction(uuid.uuid4)


class AccPaymentAllocationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccPaymentAllocation

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    payment = factory.SubFactory(AccPaymentFactory, tenant=factory.SelfAttribute("..tenant"))
    move_line = factory.SubFactory(AccMoveLineFactory, tenant=factory.SelfAttribute("..tenant"))
    amount = Decimal("100.0000")


class AccTaxCalendarFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccTaxCalendar

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    declaration_type = AccTaxCalendar.DECLARATION_TVA
    label = "TVA — declaration mensuelle"
    due_date = datetime.date(2026, 2, 15)
    periodicity = AccTaxCalendar.PERIODICITY_MONTHLY


class AccAnalyticPlanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccAnalyticPlan

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"AXE{n}")
    name = factory.Sequence(lambda n: f"Axe {n}")


class AccAnalyticAccountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccAnalyticAccount

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    plan = factory.SubFactory(AccAnalyticPlanFactory, tenant=factory.SelfAttribute("..tenant"))
    code = factory.Sequence(lambda n: f"AA{n}")
    name = factory.Sequence(lambda n: f"Compte analytique {n}")


class AccAnalyticLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccAnalyticLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    analytic_account = factory.SubFactory(
        AccAnalyticAccountFactory, tenant=factory.SelfAttribute("..tenant")
    )
    move_line = factory.SubFactory(AccMoveLineFactory, tenant=factory.SelfAttribute("..tenant"))
    date = datetime.date(2026, 1, 15)
    amount = Decimal("50.0000")


class AccAssetFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccAsset

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    reference = factory.Sequence(lambda n: f"IMMO-{n}")
    category = AccAsset.CATEGORY_CORPORELLE
    label = factory.Sequence(lambda n: f"Immobilisation {n}")
    account = factory.SubFactory(AccAccountFactory, tenant=factory.SelfAttribute("..tenant"))
    acquisition_date = datetime.date(2026, 1, 1)
    acquisition_value_mga = Decimal("1000000.0000")
    depreciation_method = AccAsset.METHOD_LINEAIRE
    useful_life_years = 5


class AccAssetMovementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccAssetMovement

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    asset = factory.SubFactory(AccAssetFactory, tenant=factory.SelfAttribute("..tenant"))
    movement_type = AccAssetMovement.MOVEMENT_ACQUISITION
    date = datetime.date(2026, 1, 1)
    amount_mga = Decimal("1000000.0000")


class AccAssetDepreciationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccAssetDepreciation

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    asset = factory.SubFactory(AccAssetFactory, tenant=factory.SelfAttribute("..tenant"))
    fiscal_year = factory.SubFactory(AccFiscalYearFactory, tenant=factory.SelfAttribute("..tenant"))
    opening_accumulated_mga = Decimal("0.0000")
    annual_dotation_mga = Decimal("200000.0000")
    closing_accumulated_mga = Decimal("200000.0000")


class AccProvisionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccProvision

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    reference = factory.Sequence(lambda n: f"PROV-{n}")
    nature = factory.Sequence(lambda n: f"Provision {n}")
    account = factory.SubFactory(AccAccountFactory, tenant=factory.SelfAttribute("..tenant"))
    fiscal_year = factory.SubFactory(AccFiscalYearFactory, tenant=factory.SelfAttribute("..tenant"))
    opening_amount_mga = Decimal("0.0000")
    closing_amount_mga = Decimal("0.0000")


class AccBudgetFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccBudget

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    fiscal_year = factory.SubFactory(AccFiscalYearFactory, tenant=factory.SelfAttribute("..tenant"))
    reference = factory.Sequence(lambda n: f"BUD-{n}")
    name = factory.Sequence(lambda n: f"Budget {n}")


class AccBudgetLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccBudgetLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    budget = factory.SubFactory(AccBudgetFactory, tenant=factory.SelfAttribute("..tenant"))
    account = factory.SubFactory(AccAccountFactory, tenant=factory.SelfAttribute("..tenant"))
    budgeted_amount_mga = Decimal("100000.0000")


class AccDcomDeclarationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccDcomDeclaration

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    fiscal_year = factory.SubFactory(AccFiscalYearFactory, tenant=factory.SelfAttribute("..tenant"))


class AccDcomLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccDcomLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    declaration = factory.SubFactory(
        AccDcomDeclarationFactory, tenant=factory.SelfAttribute("..tenant")
    )
    partner_id = factory.LazyFunction(uuid.uuid4)
    classification = "achats"
    amount_mga = Decimal("100000.0000")


class AccIrcmDeclarationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccIrcmDeclaration

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    fiscal_year = factory.SubFactory(AccFiscalYearFactory, tenant=factory.SelfAttribute("..tenant"))
    taxable_base_mga = Decimal("1000000.0000")
    rate_pct = Decimal("20.00")
    amount_due_mga = Decimal("200000.0000")


class AccLocalTaxFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccLocalTax

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    tax_type = AccLocalTax.TAX_TYPE_IFT
    property_label = factory.Sequence(lambda n: f"Terrain {n}")
    assessed_value_mga = Decimal("10000000.0000")
    rate_pct = Decimal("1.00")
    fiscal_year = factory.SubFactory(AccFiscalYearFactory, tenant=factory.SelfAttribute("..tenant"))
    amount_due_mga = Decimal("100000.0000")


class AccDunningLevelFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccDunningLevel

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    level = factory.Sequence(lambda n: (n % 3) + 1)
    label = factory.Sequence(lambda n: f"Niveau {n}")
    days_overdue_threshold = 15


class AccDunningActionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccDunningAction

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    move_line = factory.SubFactory(AccMoveLineFactory, tenant=factory.SelfAttribute("..tenant"))
    level = factory.SubFactory(AccDunningLevelFactory, tenant=factory.SelfAttribute("..tenant"))
    date_sent = datetime.date(2026, 2, 1)


class AccMobileMoneyStatementLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccMobileMoneyStatementLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    import_batch_id = factory.LazyFunction(uuid.uuid4)
    statement_date = datetime.date(2026, 2, 1)
    reference_external = factory.Sequence(lambda n: f"MVOLA-{n}")
    amount_mga = Decimal("1000.0000")
    direction = AccMobileMoneyStatementLine.DIRECTION_IN


class AccBankStatementLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccBankStatementLine

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    bank_account = factory.SubFactory(
        AccAccountFactory, tenant=factory.SelfAttribute("..tenant"), type=AccAccount.TYPE_BANK
    )
    import_batch_id = factory.LazyFunction(uuid.uuid4)
    statement_date = datetime.date(2026, 2, 1)
    reference_external = factory.Sequence(lambda n: f"VIR-{n}")
    label = factory.Sequence(lambda n: f"Virement {n}")
    amount_mga = Decimal("1000.0000")
    direction = AccBankStatementLine.DIRECTION_IN


class AccReconcileRuleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccReconcileRule

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Regle {n}")
    match_on_amount = True
