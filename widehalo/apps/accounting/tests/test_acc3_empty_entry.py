"""ACC-3 (L16) — une ecriture VIDE ne doit pas pouvoir etre publiee.

`post_move` ne verifiait que l'equilibre debit/credit. Zero egale zero : une
ecriture sans AUCUNE ligne passait donc le controle, consommait un numero de
la sequence legale (RG-ACC-3, attribue dans la foulee) et devenait
immediatement IMMUABLE par declencheur base.

L'ecran de saisie rapide aggravait le cas en affichant un badge vert
« Equilibree » sur ce brouillon vide. Un comptable qui tabulait jusqu'au
premier bouton et validait — exactement le parcours clavier que ce meme
critere ACC-3 exige — publiait une piece numerotee vide, definitivement au
journal.

Un trou dans une numerotation legale ne se repare pas : la garde vit donc
dans le service, en amont de l'attribution du numero, et l'ecran cesse de
la contredire.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import AccAccount, AccMove
from apps.accounting.services.moves import add_line, create_draft_move, post_move
from apps.accounting.tests.factories import AccAccountFactory, AccJournalFactory, AccPeriodFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _draft(tenant: Tenant) -> AccMove:
    return create_draft_move(
        tenant=tenant,
        journal=AccJournalFactory(tenant=tenant),
        period=AccPeriodFactory(
            tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 12, 31)
        ),
        date=dt.date(2026, 5, 4),
        move_type=AccMove.TYPE_ENTRY,
    )


def test_an_entry_without_any_line_is_refused() -> None:
    tenant = Tenant.objects.create(code="ACC-L16-1", name="ACC-3 vide")
    with use_tenant(tenant.id):
        move = _draft(tenant)

        with pytest.raises(ValidationError, match="sans aucune ligne"):
            post_move(move)

        move.refresh_from_db()
        assert move.state == AccMove.STATE_DRAFT


def test_refusing_it_consumes_no_sequence_number() -> None:
    """Le coeur du defaut : ce n'est pas la publication qui coute, c'est le
    NUMERO. Une ecriture legitime publiee juste apres doit obtenir le
    premier numero de la sequence, pas le second."""
    tenant = Tenant.objects.create(code="ACC-L16-2", name="ACC-3 sequence")
    with use_tenant(tenant.id):
        empty = _draft(tenant)
        with pytest.raises(ValidationError):
            post_move(empty)

        real = _draft(tenant)
        debit_account = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)
        credit_account = AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_PAYABLE)
        add_line(real, account=debit_account, label="Achat", debit=Decimal("1000"))
        add_line(real, account=credit_account, label="Fournisseur", credit=Decimal("1000"))
        posted = post_move(real)

        assert posted.state == AccMove.STATE_POSTED
        assert posted.reference.endswith("0001"), posted.reference


def test_a_real_entry_is_still_posted() -> None:
    """La garde ne doit pas empecher le cas normal — sans quoi elle casserait
    toute la comptabilite."""
    tenant = Tenant.objects.create(code="ACC-L16-3", name="ACC-3 normale")
    with use_tenant(tenant.id):
        move = _draft(tenant)
        add_line(
            move,
            account=AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE),
            label="Achat",
            debit=Decimal("500"),
        )
        add_line(
            move,
            account=AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_PAYABLE),
            label="Fournisseur",
            credit=Decimal("500"),
        )

        posted = post_move(move)

        assert posted.state == AccMove.STATE_POSTED
        assert posted.total_debit == Decimal("500")
