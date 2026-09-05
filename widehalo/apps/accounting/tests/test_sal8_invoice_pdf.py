"""SAL-8 (L5) — la facture PDF porte enfin les mentions d'une facture.

**Ce que ces tests ferment.** `invoice_pdf` concatenait une f-string de
douze lignes. Le document est pourtant declare `is_legal_document=True`,
donc archive et immuable, et il est atteignable en deux clics depuis
l'ecran des rapports comme par `GET /api/accounting/invoices/{id}/pdf`. Il
ne portait NI raison sociale, NI adresse, NI NIF de l'emetteur, NI identite
du client, NI ventilation HT/TVA/TTC. L'audit classait SAL-8 🟡 « le
parametrage par tenant des mentions obligatoires n'a pas ete retrouve » :
c'est le document entier qui manquait.

Et les libelles etaient interpoles SANS ECHAPPEMENT : un libelle contenant
du balisage se retrouvait interprete dans un PDF archive. Le dernier test
ferme ce chemin.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.accounting.models import AccAccount, AccMove
from apps.accounting.services.moves import add_line, create_draft_move
from apps.accounting.services.reports import invoice_pdf
from apps.accounting.tests.factories import AccAccountFactory, AccJournalFactory, AccPeriodFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _invoice(tenant: Tenant, *, income_label: str = "Prestation") -> AccMove:
    journal = AccJournalFactory(tenant=tenant)
    period = AccPeriodFactory(
        tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 12, 31)
    )
    receivable = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_RECEIVABLE)
    income = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_INCOME)
    tax = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_TAX)
    move = create_draft_move(
        tenant=tenant,
        journal=journal,
        period=period,
        date=dt.date(2026, 3, 10),
        move_type=AccMove.TYPE_CUSTOMER_INVOICE,
    )
    move.partner_id = uuid.uuid4()
    move.save(update_fields=["partner_id"])
    add_line(move, account=receivable, label="Client", debit=Decimal("120000"))
    add_line(move, account=income, label=income_label, credit=Decimal("100000"))
    add_line(move, account=tax, label="TVA 20%", credit=Decimal("20000"))
    return move


def test_the_invoice_pdf_is_actually_produced() -> None:
    tenant = Tenant.objects.create(code="ACC-SAL8-1", name="Ma Societe SARL", nif="1234567890")
    with use_tenant(tenant.id):
        pdf = invoice_pdf(_invoice(tenant))

    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


def test_the_rendered_html_carries_every_legal_mention() -> None:
    """Le contenu est verifie sur le HTML rendu par le meme gabarit et le
    meme contexte que le PDF : chercher une chaine dans un flux PDF
    compresse ne prouverait rien."""
    from django.template.loader import render_to_string

    from apps.core.services.branding import get_tenant_logo_data_uri
    from apps.partners.services.public import get_partner_display_name

    tenant = Tenant.objects.create(
        code="ACC-SAL8-2",
        name="Atelier Antananarivo SARL",
        nif="9876543210",
        address="Lot II M 12 Antananarivo",
        legal_mentions="Escompte pour paiement anticipe : neant.",
    )
    with use_tenant(tenant.id):
        move = _invoice(tenant)
        html = render_to_string(
            "reports/legal/invoice.html",
            {
                "invoice": move,
                "invoice_lines": [{"label": "Prestation", "amount": Decimal("100000")}],
                "total_untaxed": Decimal("100000"),
                "total_tax": Decimal("20000"),
                "total_incl_tax": move.total_debit,
                "partner_name": get_partner_display_name(move.partner_id),
                "tenant": tenant,
                "tenant_logo_data_uri": get_tenant_logo_data_uri(tenant),
            },
        )

    # Identite de l'emetteur (rendue par `reports/_base.html`).
    assert "Atelier Antananarivo SARL" in html
    assert "9876543210" in html
    assert "Lot II M 12 Antananarivo" in html
    # Ventilation fiscale.
    assert "Total HT" in html
    assert "TVA" in html
    assert "Total TTC" in html
    # Mentions parametrees par le tenant.
    assert "Escompte pour paiement anticipe" in html
    # Reference du document.
    assert move.reference in html


def test_a_line_label_containing_markup_is_escaped() -> None:
    """Le gabarit Django echappe par defaut : un libelle malveillant ne
    peut plus injecter de balisage dans un document archive et immuable.
    L'ancienne f-string l'interpolait tel quel."""
    from django.template.loader import render_to_string

    tenant = Tenant.objects.create(code="ACC-SAL8-3", name="Societe")
    with use_tenant(tenant.id):
        move = _invoice(tenant)
        html = render_to_string(
            "reports/legal/invoice.html",
            {
                "invoice": move,
                "invoice_lines": [{"label": "<script>alert(1)</script>", "amount": Decimal("1")}],
                "total_untaxed": Decimal("1"),
                "total_tax": Decimal(0),
                "total_incl_tax": Decimal("1"),
                "partner_name": "",
                "tenant": tenant,
                "tenant_logo_data_uri": "",
            },
        )

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_an_invoice_without_a_partner_says_so_instead_of_printing_a_uuid() -> None:
    """Les gabarits legaux existants rendent `{{ ... .partner_id }}`, donc
    un UUID nu la ou un nom de client est attendu. Celui-ci resout le nom,
    et le dit clairement quand il n'y en a pas."""
    from django.template.loader import render_to_string

    tenant = Tenant.objects.create(code="ACC-SAL8-4", name="Societe")
    with use_tenant(tenant.id):
        move = _invoice(tenant)
        html = render_to_string(
            "reports/legal/invoice.html",
            {
                "invoice": move,
                "invoice_lines": [],
                "total_untaxed": Decimal(0),
                "total_tax": Decimal(0),
                "total_incl_tax": Decimal(0),
                "partner_name": "",
                "tenant": tenant,
                "tenant_logo_data_uri": "",
            },
        )

    assert "non renseigné" in html
    assert str(move.partner_id) not in html
