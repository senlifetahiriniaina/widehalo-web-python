"""L17 — la facturation projet portait le meme defaut que `sales` avant L5.

`sales.services.invoicing` etait le SEUL ecrivain de `tax_lines` dans tout
le depot. Un tenant parfaitement assujetti qui facturait une regie, un
forfait ou un jalon de projet emettait donc une facture SANS TVA — et son
PDF affichait « TVA : 0 Ar », exactement comme avant L5.

Le meme test existe cote `logistics` pour la refacturation de fret."""

from __future__ import annotations

import calendar
import datetime as dt
from decimal import Decimal

import pytest

from apps.accounting.models import AccAccount, AccJournal, AccMove, AccTax
from apps.accounting.tests.factories import AccAccountFactory, AccJournalFactory, AccPeriodFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _accounting(tenant: Tenant) -> None:
    AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_SALE)
    today = dt.date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    AccPeriodFactory(
        tenant=tenant, date_start=today.replace(day=1), date_end=today.replace(day=last_day)
    )
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_RECEIVABLE)
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_INCOME)
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_TAX, code="44571")


def _vat_credit(move_id) -> Decimal:
    move = AccMove.objects.get(id=move_id)
    return sum(
        (line.credit for line in move.lines.all() if line.account.type == AccAccount.TYPE_TAX),
        Decimal(0),
    )


def _receivable_debit(move_id) -> Decimal:
    """Le debit du client, LU SUR LES LIGNES.

    Pas `AccMove.total_debit` : ce champ denormalise n'est renseigne qu'a la
    PUBLICATION (`post_move`), et `create_customer_invoice_from_source`
    retourne toujours un brouillon — decision assumee du gap lui-meme, pour
    que le dispositif d'approbation a seuils puisse s'appliquer avant. Un
    premier jet de ce test l'ignorait et lisait un zero parfaitement
    legitime."""
    move = AccMove.objects.get(id=move_id)
    return sum((line.debit for line in move.lines.all()), Decimal(0))


def _billed_project_invoice(tenant: Tenant, email: str, amount: Decimal):
    """Facture un projet PAR LE CHEMIN DE PRODUCTION (`bill_fixed`).

    Un premier jet de ce fichier appelait
    `create_customer_invoice_from_source` + `default_sale_tax_lines` a la
    main : il testait le helper, jamais le CABLAGE. La falsification l'a
    montre — retirer `tax_lines` de `projects.services.billing` laissait le
    test parfaitement vert. C'est exactement le motif que ce chantier
    traque depuis le debut (« le code est juste, rien ne l'appelle »),
    reproduit dans un test cense le prouver."""
    from apps.core.models.user import User
    from apps.partners.tests.factories import PartnerFactory
    from apps.projects.services.billing import bill_fixed
    from apps.projects.tests.factories import PrjProjectFactory

    user = User.objects.create_user(email=email, password="Str0ngPassw0rd!23")
    partner = PartnerFactory(tenant=tenant)
    project = PrjProjectFactory(tenant=tenant, client_partner_id=partner.id)
    return bill_fixed(project, user, amount=amount)


def test_a_project_invoice_carries_the_vat_of_a_liable_tenant() -> None:
    """L'egalite qui etait fausse : 200 000 HT a 20 % font 40 000 de TVA, et
    la facture projet en creditait zero — `sales` etait le SEUL ecrivain de
    `tax_lines` dans tout le depot."""
    tenant = Tenant.objects.create(
        code="L17-PRJ", name="Projet SARL", fiscal_regime=Tenant.FISCAL_REGIME_REAL_WITH_VAT
    )
    with use_tenant(tenant.id):
        AccTax.objects.create(
            tenant=tenant,
            code="TVA20",
            name="TVA 20%",
            type=AccTax.TYPE_SALE,
            rate=Decimal("20.000"),
        )
        _accounting(tenant)
        move_id = _billed_project_invoice(tenant, "l17-prj@example.com", Decimal("200000"))

        assert move_id is not None
        assert _vat_credit(move_id) == Decimal("40000.0000")
        assert _receivable_debit(move_id) == Decimal("240000.0000")


def test_a_non_liable_tenant_project_invoice_carries_no_vat_line() -> None:
    """La falsification : meme montant, meme configuration comptable, meme
    `AccTax` en base — seul le regime change."""
    tenant = Tenant.objects.create(
        code="L17-PRJ-SYN",
        name="Projet synthetique SARL",
        fiscal_regime=Tenant.FISCAL_REGIME_SYNTHETIC,
    )
    with use_tenant(tenant.id):
        AccTax.objects.create(
            tenant=tenant,
            code="TVA20",
            name="TVA 20%",
            type=AccTax.TYPE_SALE,
            rate=Decimal("20.000"),
        )
        _accounting(tenant)
        move_id = _billed_project_invoice(tenant, "l17-prj-syn@example.com", Decimal("200000"))

        assert move_id is not None
        assert _vat_credit(move_id) == Decimal(0)
        assert _receivable_debit(move_id) == Decimal("200000.0000")
