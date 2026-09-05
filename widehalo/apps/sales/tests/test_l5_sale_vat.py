"""L5 — la TVA de vente, de la ligne de devis au compte de TVA collectee.

Ce que ces tests verrouillent, et pourquoi ils ne pouvaient pas exister
avant : `sales` forcait `amount_tax = Decimal(0)` sur les deux documents,
et `invoice_order` n'envoyait a `accounting` que des lignes HORS TAXE.
Aucune facture emise depuis une commande de vente ne creditait donc jamais
un compte de TVA collectee — sur aucun tenant, quel que soit son regime.

**Pourquoi la suite existante restait verte pendant tout ce temps.** Aucun
jeu de donnees de test du depot ne cree d'`AccTax` de vente sur le chemin
`sales`/facturation. Le taux applicable etait donc toujours nul, l'egalite
HT == TTC toujours vraie, et l'absence de TVA parfaitement invisible. Un
test qui ne cree pas de taxe ne prouve rien sur la TVA : chaque test
ci-dessous en cree une, et chacun a ete VU rouge avant d'etre garde."""

from __future__ import annotations

import calendar
import datetime as dt
from decimal import Decimal

import pytest

from apps.accounting.models import AccAccount, AccJournal, AccMove, AccTax
from apps.accounting.tests.factories import AccAccountFactory, AccJournalFactory, AccPeriodFactory
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.partners.tests.factories import PartnerFactory
from apps.sales.models import SalesOrder, SalesOrderLine
from apps.sales.services.invoicing import invoice_order
from apps.sales.services.orders import (
    add_order_line,
    confirm_order,
    create_order,
    create_order_from_quotation,
    mark_delivered,
    start_preparation,
)
from apps.sales.services.quotations import (
    accept_quotation,
    add_quotation_line,
    create_quotation,
    send_quotation,
)

pytestmark = pytest.mark.django_db

VAT_RATE = Decimal("20.000")


def _tenant(code: str, regime: str = Tenant.FISCAL_REGIME_REAL_WITH_VAT, **kwargs) -> Tenant:
    return Tenant.objects.create(code=code, name=f"Tenant {code}", fiscal_regime=regime, **kwargs)


def _sale_tax(tenant: Tenant, rate: Decimal = VAT_RATE, account: AccAccount | None = None):
    return AccTax.objects.create(
        tenant=tenant,
        code="TVA20",
        name="TVA 20%",
        type=AccTax.TYPE_SALE,
        rate=rate,
        account_collected=account,
    )


def _setup_accounting(tenant: Tenant, *, with_vat_account: bool = True) -> None:
    """Configuration comptable minimale de `create_customer_invoice_from_
    source`, plus — c'est l'ajout de L5 — un compte de TVA. Sans lui, la
    facture ne peut pas etre equilibree des lors qu'une TVA est due."""
    AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_SALE)
    today = dt.date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    AccPeriodFactory(
        tenant=tenant, date_start=today.replace(day=1), date_end=today.replace(day=last_day)
    )
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_RECEIVABLE)
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_INCOME)
    if with_vat_account:
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_TAX, code="44571")


def _user(email: str) -> User:
    return User.objects.create_user(email=email, password="Str0ngPassw0rd!23")


# --- Le devis ----------------------------------------------------------------


def test_a_quotation_line_carries_the_vat_of_the_tenant() -> None:
    """L'egalite qui etait fausse : 100 000 HT a 20 % font 120 000 TTC.

    Avant L5 cette assertion echouait sur `amount_tax == 0` puis sur
    `amount_total == 100000` — les deux valeurs que `_recompute_totals`
    ecrivait en dur."""
    tenant = _tenant("L5-DEVIS")
    with use_tenant(tenant.id):
        _sale_tax(tenant)
        partner = PartnerFactory(tenant=tenant)
        quotation = create_quotation(
            tenant=tenant, partner_id=partner.id, date=dt.date(2026, 3, 10)
        )
        line = add_quotation_line(
            quotation,
            description="Prestation",
            qty=Decimal("1"),
            unit_price=Decimal("100000"),
            is_custom=True,
        )

        assert line.tax_rate == VAT_RATE
        assert line.tax_id is not None
        quotation.refresh_from_db()
        assert quotation.amount_untaxed == Decimal("100000.0000")
        assert quotation.amount_tax == Decimal("20000.0000")
        assert quotation.amount_total == Decimal("120000.0000")
        assert quotation.amount_total_mga == Decimal("120000.0000")


def test_a_tenant_that_is_not_liable_to_vat_still_bills_nothing(  # noqa: D401
) -> None:
    """La falsification : MEME TAXE, meme montant, regime different.

    Sans ce test, « la TVA est appliquee » et « la TVA est appliquee a tort
    a tout le monde » seraient indiscernables. RG-ACC-5 : un tenant au
    regime reel SANS assujettissement ne collecte pas, meme si une `AccTax`
    de vente traine dans sa base — et c'etait precisement le cas que
    `vat_applicable` classait du mauvais cote avant ce lot."""
    tenant = _tenant("L5-SANS-TVA", regime=Tenant.FISCAL_REGIME_REAL_NO_VAT)
    with use_tenant(tenant.id):
        _sale_tax(tenant)
        partner = PartnerFactory(tenant=tenant)
        quotation = create_quotation(
            tenant=tenant, partner_id=partner.id, date=dt.date(2026, 3, 10)
        )
        line = add_quotation_line(
            quotation,
            description="Prestation",
            qty=Decimal("1"),
            unit_price=Decimal("100000"),
            is_custom=True,
        )

        assert line.tax_id is None
        assert line.tax_rate == Decimal(0)
        quotation.refresh_from_db()
        assert quotation.amount_tax == Decimal(0)
        assert quotation.amount_total == quotation.amount_untaxed


def test_the_vat_option_of_the_2026_finance_act_makes_the_tenant_liable() -> None:
    """`Tenant.vat_opted_in` (ACC-SMT1) trouve ici son PREMIER lecteur.

    Le champ existait, documente sur quinze lignes, et aucune decision du
    depot n'en dependait : un tenant qui exercait l'option restait non
    assujetti. Meme tenant, meme taxe, meme montant que le test precedent
    — seule l'option change, et le resultat doit changer avec elle."""
    tenant = _tenant("L5-OPTION", regime=Tenant.FISCAL_REGIME_REAL_NO_VAT, vat_opted_in=True)
    with use_tenant(tenant.id):
        _sale_tax(tenant)
        partner = PartnerFactory(tenant=tenant)
        quotation = create_quotation(
            tenant=tenant, partner_id=partner.id, date=dt.date(2026, 3, 10)
        )
        add_quotation_line(
            quotation,
            description="Prestation",
            qty=Decimal("1"),
            unit_price=Decimal("100000"),
            is_custom=True,
        )
        quotation.refresh_from_db()
        assert quotation.amount_tax == Decimal("20000.0000")


def test_a_rate_change_never_rewrites_a_document_already_issued() -> None:
    """L'instantane, vu depuis la seule chose qui compte : une loi de
    finances qui passe la TVA de 20 % a 18 % APRES l'emission du devis.

    Le devis garde 20 %, et la commande qui en decoule aussi — sans quoi le
    client se verrait facturer un montant qu'il n'a jamais accepte. C'est
    ce test qui justifie le champ `tax_rate` (et non une simple relecture
    de `AccTax` par `tax_id`)."""
    tenant = _tenant("L5-FIGE")
    with use_tenant(tenant.id):
        tax = _sale_tax(tenant)
        partner = PartnerFactory(tenant=tenant)
        quotation = create_quotation(
            tenant=tenant, partner_id=partner.id, date=dt.date(2026, 3, 10)
        )
        add_quotation_line(
            quotation,
            description="Prestation",
            qty=Decimal("1"),
            unit_price=Decimal("100000"),
            is_custom=True,
        )
        quotation.refresh_from_db()
        assert quotation.amount_tax == Decimal("20000.0000")

        tax.rate = Decimal("18.000")
        tax.save(update_fields=["rate"])

        send_quotation(quotation)
        accept_quotation(quotation)
        order = create_order_from_quotation(quotation)

        assert [line.tax_rate for line in order.lines.all()] == [VAT_RATE]
        assert order.amount_tax == Decimal("20000.0000")
        assert order.amount_total_mga == Decimal("120000.0000")


# --- La facture ---------------------------------------------------------------


def _delivered_order(tenant: Tenant, user: User, partner, **line_kwargs) -> SalesOrder:
    order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
    add_order_line(
        order,
        description="Ligne",
        qty=Decimal("2"),
        unit_price=Decimal("50000"),
        is_custom=True,
        **line_kwargs,
    )
    confirm_order(order, user)
    start_preparation(order, user)
    mark_delivered(order, user)
    order.refresh_from_db()
    return order


def test_the_invoice_credits_a_vat_account_for_exactly_the_document_vat() -> None:
    """L'egalite centrale de L5, cote comptable.

    Trois affirmations independantes, qui echouaient toutes les trois avant
    ce lot : l'ecriture porte une ligne creditee sur un compte de TAXE ;
    son montant est exactement l'`amount_tax` du document (pas un recalcul
    approche) ; et le debit du client est le TTC, donc l'ecriture equilibre
    HT + TVA. La derniere est celle qui compte : une facture qui debiterait
    le TTC en ne creditant que le HT ne serait pas equilibree du tout."""
    tenant = _tenant("L5-FACT")
    with use_tenant(tenant.id):
        _sale_tax(tenant)
        _setup_accounting(tenant)
        user = _user("l5-fact@example.com")
        partner = PartnerFactory(tenant=tenant)
        order = _delivered_order(tenant, user, partner)

        assert order.amount_untaxed == Decimal("100000.0000")
        assert order.amount_tax == Decimal("20000.0000")

        move_id = invoice_order(order, user)
        assert move_id is not None
        move = AccMove.objects.get(id=move_id)

        vat_lines = [line for line in move.lines.all() if line.account.type == AccAccount.TYPE_TAX]
        assert len(vat_lines) == 1
        assert vat_lines[0].credit == Decimal("20000.0000")
        assert vat_lines[0].tax_base == Decimal("100000.0000")
        assert vat_lines[0].tax_id is not None

        receivable = [
            line for line in move.lines.all() if line.account.type == AccAccount.TYPE_RECEIVABLE
        ]
        assert len(receivable) == 1
        assert receivable[0].debit == Decimal("120000.0000")

        totals = [
            sum(line.debit for line in move.lines.all()),
            sum(line.credit for line in move.lines.all()),
        ]
        assert totals[0] == totals[1] == Decimal("120000.0000")


def test_a_fully_invoiced_order_still_reaches_the_invoiced_state() -> None:
    """Le piege de ce lot, et la raison pour laquelle il ne se voit pas.

    `amount_total_mga` devient un TTC. Si `invoiced_amount_mga` continuait
    de cumuler du HT, l'ecart resterait egal a la TVA pour toujours : la
    commande resterait `delivered` indefiniment, entierement facturee et
    jamais marquee comme telle. Le symptome (un etat qui ne bouge plus) est
    a l'autre bout de la chaine de sa cause (deux montants qui ne parlent
    pas de la meme chose), et c'est exactement le genre de panne qu'un test
    de montant seul laisse passer."""
    tenant = _tenant("L5-ETAT")
    with use_tenant(tenant.id):
        _sale_tax(tenant)
        _setup_accounting(tenant)
        user = _user("l5-etat@example.com")
        partner = PartnerFactory(tenant=tenant)
        order = _delivered_order(tenant, user, partner)

        assert invoice_order(order, user) is not None
        order.refresh_from_db()

        assert order.invoiced_amount_mga == order.amount_total_mga == Decimal("120000.0000")
        assert order.state == SalesOrder.STATE_INVOICED


def test_a_partial_invoice_collects_only_the_vat_of_the_part_invoiced() -> None:
    """Une facture d'acompte de 30 % collecte 30 % de la TVA, pas 100 %.

    L'erreur naturelle serait de prendre `line.subtotal` comme base
    taxable : elle donnerait 20 000 de TVA sur une facture de 30 000 HT,
    soit un taux apparent de 66 %. La base est la part REELLEMENT facturee.
    """
    tenant = _tenant("L5-ACOMPTE")
    with use_tenant(tenant.id):
        _sale_tax(tenant)
        _setup_accounting(tenant)
        user = _user("l5-acompte@example.com")
        partner = PartnerFactory(tenant=tenant)
        order = create_order(tenant=tenant, partner_id=partner.id, date=dt.date.today())
        add_order_line(
            order,
            description="Ligne",
            qty=Decimal("2"),
            unit_price=Decimal("50000"),
            is_custom=True,
            billing_policy=SalesOrderLine.BILLING_ON_DEPOSIT,
            deposit_pct=Decimal("30"),
        )
        confirm_order(order, user)
        order.refresh_from_db()

        move_id = invoice_order(order, user)
        assert move_id is not None
        move = AccMove.objects.get(id=move_id)

        vat_lines = [line for line in move.lines.all() if line.account.type == AccAccount.TYPE_TAX]
        assert len(vat_lines) == 1
        assert vat_lines[0].credit == Decimal("6000.0000")
        assert vat_lines[0].tax_base == Decimal("30000.0000")

        order.refresh_from_db()
        assert order.invoiced_amount_mga == Decimal("36000.0000")
        assert order.state != SalesOrder.STATE_INVOICED


def test_no_invoice_is_posted_when_the_vat_has_nowhere_to_go() -> None:
    """Une TVA due sans compte ou l'imputer ne produit AUCUNE facture.

    Le contraire — poster la facture en oubliant la ligne de TVA — serait
    la pire des trois issues possibles : une piece comptable equilibree,
    d'apparence normale, et fausse. La discipline `None` de cette surface
    (« un gap de configuration n'est pas un bug de sales ») s'applique donc
    aussi a la TVA."""
    tenant = _tenant("L5-SANS-COMPTE")
    with use_tenant(tenant.id):
        _sale_tax(tenant)
        _setup_accounting(tenant, with_vat_account=False)
        user = _user("l5-sans-compte@example.com")
        partner = PartnerFactory(tenant=tenant)
        order = _delivered_order(tenant, user, partner)

        assert invoice_order(order, user) is None
        order.refresh_from_db()
        assert order.invoiced_amount_mga == Decimal(0)
        assert order.state == SalesOrder.STATE_DELIVERED
        assert not AccMove.objects.filter(
            tenant=tenant, move_type=AccMove.TYPE_CUSTOMER_INVOICE
        ).exists()


def test_the_vat_is_credited_on_the_account_configured_on_the_tax_itself() -> None:
    """`AccTax.account_collected` l'emporte sur le compte par defaut du
    tenant : un tenant a plusieurs taux (normal, reduit) peut vouloir les
    imputer separement, et c'est la taxe qui porte cette information."""
    tenant = _tenant("L5-COMPTE-TAXE")
    with use_tenant(tenant.id):
        _setup_accounting(tenant)
        dedicated = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_TAX, code="44572")
        _sale_tax(tenant, account=dedicated)
        user = _user("l5-compte-taxe@example.com")
        partner = PartnerFactory(tenant=tenant)
        order = _delivered_order(tenant, user, partner)

        move_id = invoice_order(order, user)
        assert move_id is not None
        move = AccMove.objects.get(id=move_id)
        vat_lines = [line for line in move.lines.all() if line.credit == Decimal("20000.0000")]
        assert len(vat_lines) == 1
        assert vat_lines[0].account_id == dedicated.id
