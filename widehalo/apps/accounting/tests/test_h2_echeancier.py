"""H-2c (RG-ACC-6) — l'echeancier d'une facture, et les quatre ecrans qui
l'attendaient.

**Ce que ce fichier eprouve, et pourquoi il n'existait pas.**
`generate_due_lines` calcule « 30 % a la commande, 40 % a 30 jours, 30 % a
60 jours » depuis l'origine du projet et n'avait AUCUN appelant ; `AccMove`
n'avait aucune clef vers `AccPaymentTerm` ; rien en production n'ecrivait
`AccMoveLine.due_date`. Quatre fonctionnalites livrees filtrent pourtant
sur `due_date__isnull=False` — la relance client (G-3), la balance agee,
l'echeancier et la prevision de tresorerie. Elles etaient VIDES pour toute
facture, sans qu'aucune erreur ne le signale.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.accounting.models import (
    AccAccount,
    AccFiscalYear,
    AccJournal,
    AccMove,
    AccPaymentTerm,
    AccPaymentTermLine,
    AccPeriod,
)
from apps.accounting.services.dunning import overdue_receivables, seed_default_dunning_levels
from apps.accounting.services.invoices import (
    create_invoice,
    ensure_default_approval_thresholds,
    validate_invoice,
)
from apps.accounting.services.payment_terms import apply_payment_term
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_permissions, use_tenant

pytestmark = pytest.mark.django_db

#: Sous le premier palier d'approbation (2 000 000 Ar) : la validation ne
#: doit pas se heurter au moteur d'approbation, qui n'est pas l'objet ici.
MONTANT = Decimal("900000")


@pytest.fixture
def grand_livre():
    tenant = Tenant.objects.create(code="ACC-ECH", name="Societe Echeancier")
    with use_tenant(tenant.id):
        exercice = AccFiscalYear.objects.create(
            tenant=tenant,
            code="FY2026",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 12, 31),
        )
        periode = AccPeriod.objects.create(
            tenant=tenant,
            fiscal_year=exercice,
            code="2026-01",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 1, 31),
        )
        journal = AccJournal.objects.create(
            tenant=tenant,
            code="VTE",
            name="Ventes",
            type=AccJournal.TYPE_SALE,
            sequence_prefix="VTE",
        )
        creance = AccAccount.objects.create(
            tenant=tenant,
            code="411",
            name="Clients",
            account_class=4,
            type=AccAccount.TYPE_RECEIVABLE,
        )
        produit = AccAccount.objects.create(
            tenant=tenant,
            code="701",
            name="Ventes",
            account_class=7,
            type=AccAccount.TYPE_INCOME,
        )
        ensure_default_approval_thresholds(tenant)
        return tenant, periode, journal, creance, produit


def _condition(tenant: Tenant, *parts: tuple[str, Decimal | None, int]) -> AccPaymentTerm:
    """Une condition de paiement : (type de valeur, valeur, jours) par part."""
    terme = AccPaymentTerm.objects.create(tenant=tenant, name="Echelonne")
    for rang, (type_valeur, valeur, jours) in enumerate(parts):
        AccPaymentTermLine.objects.create(
            tenant=tenant,
            term=terme,
            sequence=rang,
            value_type=type_valeur,
            value=valeur,
            days=jours,
        )
    return terme


def _facture(grand_livre, *, terme: AccPaymentTerm | None = None, montant: Decimal = MONTANT):
    tenant, periode, journal, creance, produit = grand_livre
    piece = create_invoice(
        tenant=tenant,
        journal=journal,
        period=periode,
        date=dt.date(2026, 1, 15),
        partner_id=None,
        receivable_account=creance,
        income_lines=[{"account": produit, "amount": montant, "label": "Vente"}],
    )
    if terme is not None:
        piece.payment_term = terme
        piece.save(update_fields=["payment_term"])
    return piece


def test_a_three_instalment_term_splits_the_receivable_and_dates_each_part(grand_livre) -> None:
    """30 % comptant, 40 % a 30 jours, 30 % a 60 jours : trois lignes."""
    tenant, *_ = grand_livre
    with use_tenant(tenant.id):
        terme = _condition(
            tenant,
            (AccPaymentTermLine.VALUE_TYPE_PERCENT, Decimal("30"), 0),
            (AccPaymentTermLine.VALUE_TYPE_PERCENT, Decimal("40"), 30),
            (AccPaymentTermLine.VALUE_TYPE_BALANCE, None, 60),
        )
        piece = _facture(grand_livre, terme=terme)
        produites = apply_payment_term(piece)

        assert produites == 3
        lignes = list(
            piece.lines.filter(account__type=AccAccount.TYPE_RECEIVABLE).order_by("due_date")
        )
        assert [ligne.debit for ligne in lignes] == [
            Decimal("270000.0000"),
            Decimal("360000.0000"),
            Decimal("270000.0000"),
        ]
        assert [ligne.due_date for ligne in lignes] == [
            dt.date(2026, 1, 15),
            dt.date(2026, 2, 14),
            dt.date(2026, 3, 16),
        ]
        assert sum((ligne.debit for ligne in lignes), Decimal(0)) == MONTANT


def test_an_invoice_without_a_payment_term_is_due_on_its_own_date(grand_livre) -> None:
    """Le REPLI compte autant que le cas nominal.

    Sans lui, seules les factures a conditions echelonnees apparaitraient
    dans les quatre ecrans, et l'exploitant conclurait que la relance ne
    fonctionne pas."""
    tenant, *_ = grand_livre
    with use_tenant(tenant.id):
        piece = _facture(grand_livre)
        assert apply_payment_term(piece) == 1

        ligne = piece.lines.get(account__type=AccAccount.TYPE_RECEIVABLE)
        assert ligne.due_date == dt.date(2026, 1, 15)
        assert ligne.debit == MONTANT


def test_a_term_whose_percentages_do_not_close_still_balances(grand_livre) -> None:
    """Trois tiers a 33,3333 % ne redonnent pas le total.

    `post_move` compare debit et credit A L'EGALITE STRICTE : une derive
    d'un dix-millieme refuserait la publication d'une facture legitime. La
    derniere echeance absorbe donc le reliquat — et c'est le seul moyen de
    le prouver."""
    tenant, *_ = grand_livre
    with use_tenant(tenant.id):
        terme = _condition(
            tenant,
            (AccPaymentTermLine.VALUE_TYPE_PERCENT, Decimal("33.3333"), 0),
            (AccPaymentTermLine.VALUE_TYPE_PERCENT, Decimal("33.3333"), 30),
            (AccPaymentTermLine.VALUE_TYPE_PERCENT, Decimal("33.3333"), 60),
        )
        piece = _facture(grand_livre, terme=terme)
        apply_payment_term(piece)

        lignes = piece.lines.filter(account__type=AccAccount.TYPE_RECEIVABLE)
        assert sum((ligne.debit for ligne in lignes), Decimal(0)) == MONTANT

        totaux = piece.lines.all()
        debit = sum((ligne.debit for ligne in totaux), Decimal(0))
        credit = sum((ligne.credit for ligne in totaux), Decimal(0))
        assert debit == credit, "l'eclatement a desequilibre l'ecriture"


def test_applying_the_term_twice_never_splits_twice(grand_livre) -> None:
    """Idempotence — lecon de `record_analytic_lines`, qui doublait ses
    lignes au deuxieme passage."""
    tenant, *_ = grand_livre
    with use_tenant(tenant.id):
        terme = _condition(
            tenant,
            (AccPaymentTermLine.VALUE_TYPE_PERCENT, Decimal("50"), 0),
            (AccPaymentTermLine.VALUE_TYPE_BALANCE, None, 30),
        )
        piece = _facture(grand_livre, terme=terme)
        assert apply_payment_term(piece) == 2
        assert apply_payment_term(piece) == 0
        assert piece.lines.filter(account__type=AccAccount.TYPE_RECEIVABLE).count() == 2


def test_validating_an_invoice_dates_its_receivable_and_the_dunning_screen_sees_it(
    grand_livre,
) -> None:
    """Le bout en bout, et la raison d'etre du lot.

    La facture est validee par le chemin de production ; l'ecran de
    relance de G-3 — qui filtre sur `due_date__isnull=False` et ne pouvait
    donc RIEN afficher — trouve enfin la creance echue."""
    tenant, *_ = grand_livre
    with use_tenant(tenant.id):
        seed_default_dunning_levels(tenant)
        utilisateur = User.objects.create_user(
            email="echeancier@example.com", password="Str0ngPassw0rd!23"
        )
        # `AccMove.validate` declare `permission="accounting.validate_accmove"` :
        # c'est une des trois transitions du depot a en declarer une. Droit
        # NOMME plutot que module entier — la propriete testee ici est
        # l'echeancier, pas l'etendue des droits.
        grant_permissions(utilisateur, app_label="accounting", codenames=["validate_accmove"])
        terme = _condition(
            tenant,
            (AccPaymentTermLine.VALUE_TYPE_PERCENT, Decimal("50"), 0),
            (AccPaymentTermLine.VALUE_TYPE_BALANCE, None, 30),
        )
        piece = _facture(grand_livre, terme=terme)
        publiee = validate_invoice(piece, utilisateur)

        assert publiee.state == AccMove.STATE_POSTED
        echeances = list(
            publiee.lines.filter(account__type=AccAccount.TYPE_RECEIVABLE).order_by("due_date")
        )
        assert len(echeances) == 2
        assert all(ligne.due_date is not None for ligne in echeances)

        creances = overdue_receivables(tenant)
        assert creances, "la relance client ne voit toujours aucune créance échue"
        assert {str(ligne.id) for ligne in echeances} >= {
            ligne["move_line_id"] for ligne in creances
        }
