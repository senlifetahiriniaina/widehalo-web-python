"""T6 (bloc E, BNK-4) — l'ordre de virement, de son émission à son débit.

**Le critère** : « un ordre de virement exporté est **rattaché aux pièces
qu'il règle**, et son **état de remise est suivi jusqu'au rapprochement du
débit** correspondant. » Deux exigences, et la mesure disait qu'aucune
n'était tenue : rien de tel n'existait dans le dépôt.

**Ce que la mesure a trouvé au passage, et qui est plus grave que l'écart
lui-même.** Les deux générateurs de fichier de virement de `payroll`
(`generate_mobile_money_transfer_file`, `generate_bank_transfer_file`)
n'ont **aucun appelant de production** : ni vue, ni API, ni commande. Le
fichier n'était produisible que depuis un test. Un exploitant ne pouvait
donc pas payer ses salariés — la fonctionnalité était écrite, documentée,
testée, et inatteignable.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import AccAccount, AccBankStatementLine, AccTransferOrder
from apps.accounting.services.transfer_orders import (
    create_transfer_order,
    export_transfer_order,
    mark_remitted,
    orders_in_flight,
    reconcile_transfer_order,
)
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db

#: Les colonnes autorisées, écrites ICI et non lues depuis le module.
#:
#: **La falsification l'a exigé.** La première rédaction comparait le
#: fichier produit à `EXPORT_FIELDNAMES` — c'est-à-dire à la constante que
#: le test est censé surveiller. Ajouter une colonne « detail » au module
#: l'ajoutait donc des deux côtés, et la mutation ne mordait pas : le test
#: comparait la chose à elle-même. Un jeu fermé se vérifie contre une
#: liste indépendante, jamais contre sa propre source.
COLONNES_ATTENDUES = {"beneficiary", "account", "amount", "reference"}

MONTANT_A = Decimal("400000")
MONTANT_B = Decimal("350000")
TOTAL = MONTANT_A + MONTANT_B


@pytest.fixture
def societe():
    tenant = Tenant.objects.create(code="ACC-T6V", name="Ordres de virement")
    with use_tenant(tenant.id):
        banque = AccAccount.objects.create(
            tenant=tenant, code="512", name="Banque", account_class=5, type=AccAccount.TYPE_BANK
        )
    return tenant, banque


def _lignes(*montants: Decimal) -> list[dict]:
    return [
        {
            "document_type": "payroll.PayPayslip",
            "document_id": uuid.uuid4(),
            "beneficiary_label": f"Salarie {rang}",
            "beneficiary_account": f"03412345{rang:02d}",
            "amount": montant,
            "reference": f"BUL-{rang:03d}",
        }
        for rang, montant in enumerate(montants, start=1)
    ]


def _ordre(tenant, banque, *montants: Decimal) -> AccTransferOrder:
    return create_transfer_order(
        tenant,
        bank_account=banque,
        execution_date=dt.date(2026, 1, 31),
        lines=_lignes(*(montants or (MONTANT_A, MONTANT_B))),
        origin=AccTransferOrder.ORIGIN_PAYROLL,
    )


def _debit(tenant, banque, montant: Decimal, *, direction=AccBankStatementLine.DIRECTION_OUT):
    return AccBankStatementLine.objects.create(
        tenant=tenant,
        bank_account=banque,
        import_batch_id=uuid.uuid4(),
        statement_date=dt.date(2026, 2, 2),
        reference_external="DEB-001",
        label="Virement salaires",
        amount_mga=montant,
        direction=direction,
        state=AccBankStatementLine.STATE_UNMATCHED,
    )


def test_an_order_is_attached_to_the_documents_it_settles(societe) -> None:
    """**La première moitié du critère.** Un ordre qui ne dit pas ce qu'il
    règle est un montant sans justification : au moment où la banque
    débite, plus rien ne relie la sortie d'argent aux bulletins."""
    tenant, banque = societe
    with use_tenant(tenant.id):
        ordre = _ordre(tenant, banque)

        assert ordre.lines.count() == 2
        assert {ligne.document_type for ligne in ordre.lines.all()} == {"payroll.PayPayslip"}
        assert ordre.total_amount == TOTAL, (
            "Le total doit être CALCULÉ depuis les lignes : reçu en paramètre, "
            "un ordre pourrait annoncer une somme qui n'est pas celle qu'il règle."
        )


def test_an_empty_order_is_refused(societe) -> None:
    """Un ordre sans ligne produirait un fichier vide et attendrait pour
    toujours un débit de zéro : un ordre en vol permanent dans l'écran de
    suivi."""
    tenant, banque = societe
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        create_transfer_order(
            tenant,
            bank_account=banque,
            execution_date=dt.date(2026, 1, 31),
            lines=[],
            origin=AccTransferOrder.ORIGIN_PAYROLL,
        )


def test_the_exported_file_carries_only_the_closed_columns(societe) -> None:
    """**BNK-5 étendu à tout ordre.** Ce qui ne figure pas dans le fichier
    ne peut pas fuir ; le jeu de colonnes est donc fermé et vérifié sur le
    contenu produit, pas seulement déclaré."""
    tenant, banque = societe
    with use_tenant(tenant.id):
        ordre = _ordre(tenant, banque)
        contenu = export_transfer_order(ordre)

    lues = list(csv.DictReader(io.StringIO(contenu)))
    assert len(lues) == 2
    for ligne in lues:
        assert set(ligne) == COLONNES_ATTENDUES
    assert sorted(Decimal(ligne["amount"]) for ligne in lues) == sorted([MONTANT_B, MONTANT_A])


def test_exporting_moves_the_order_out_of_draft_once(societe) -> None:
    """Ré-exporter est permis — une banque perd un fichier — et ne change
    ni le contenu ni la date du PREMIER export.

    Refuser obligerait à recomposer un ordre identique sous une autre
    référence, c'est-à-dire à risquer un double débit pour éviter un
    doublon de fichier."""
    tenant, banque = societe
    with use_tenant(tenant.id):
        ordre = _ordre(tenant, banque)
        premier = export_transfer_order(ordre)
        ordre.refresh_from_db()
        date_premier_export = ordre.exported_at

        second = export_transfer_order(ordre)
        ordre.refresh_from_db()

        assert ordre.state == AccTransferOrder.STATE_EXPORTED
        assert premier == second
        assert ordre.exported_at == date_premier_export


def test_remittance_is_attested_never_deduced(societe) -> None:
    """Aucune banque ne nous dit qu'elle a reçu le fichier.

    Le déduire de l'export ferait passer pour remis un ordre resté sur un
    poste de travail — et l'écran de suivi montrerait un retard de la
    banque là où il n'y a qu'un oubli chez nous."""
    tenant, banque = societe
    with use_tenant(tenant.id):
        ordre = _ordre(tenant, banque)
        with pytest.raises(ValidationError):
            mark_remitted(ordre)  # encore en brouillon

        export_transfer_order(ordre)
        mark_remitted(ordre)
        ordre.refresh_from_db()

        assert ordre.state == AccTransferOrder.STATE_REMITTED
        assert ordre.remitted_at is not None
        assert ordre.is_in_flight


def test_the_order_is_followed_until_the_debit_appears(societe) -> None:
    """**La seconde moitié du critère, et c'est celle que rien ne portait**
    — « suivi jusqu'au rapprochement du débit correspondant »."""
    tenant, banque = societe
    with use_tenant(tenant.id):
        ordre = _ordre(tenant, banque)
        export_transfer_order(ordre)
        mark_remitted(ordre)

        assert [o.id for o in orders_in_flight(tenant)] == [ordre.id]

        reconcile_transfer_order(ordre, _debit(tenant, banque, TOTAL))
        ordre.refresh_from_db()

        assert ordre.state == AccTransferOrder.STATE_RECONCILED
        assert ordre.statement_line is not None
        assert not ordre.is_in_flight
        assert orders_in_flight(tenant) == [], (
            "Un ordre rapproché est clos : le laisser en vol noierait les ordres "
            "réellement en attente."
        )


def test_a_debit_that_does_not_match_is_refused(societe) -> None:
    """Une banque qui débite autre chose que ce qu'on lui a demandé est
    précisément l'incident que ce suivi existe pour rendre visible.

    L'absorber en silence — en rapprochant quand même — le rendrait
    invisible, et c'est le seul cas où le suivi aurait vraiment servi."""
    tenant, banque = societe
    with use_tenant(tenant.id):
        ordre = _ordre(tenant, banque)
        export_transfer_order(ordre)
        mark_remitted(ordre)

        with pytest.raises(ValidationError):
            reconcile_transfer_order(ordre, _debit(tenant, banque, TOTAL - Decimal("1")))

        ordre.refresh_from_db()
        assert ordre.state == AccTransferOrder.STATE_REMITTED


def test_an_incoming_line_never_settles_a_transfer_order(societe) -> None:
    """Un ordre fait SORTIR de l'argent. Le rapprocher d'un encaissement
    ferait disparaître deux mouvements réels d'un seul coup : l'ordre
    passerait pour exécuté, et l'encaissement pour justifié."""
    tenant, banque = societe
    with use_tenant(tenant.id):
        ordre = _ordre(tenant, banque)
        export_transfer_order(ordre)
        mark_remitted(ordre)

        with pytest.raises(ValidationError):
            reconcile_transfer_order(
                ordre, _debit(tenant, banque, TOTAL, direction=AccBankStatementLine.DIRECTION_IN)
            )


def test_one_debit_never_settles_two_orders(societe) -> None:
    """Deux ordres du même montant, un seul débit : le second doit être
    refusé, sans quoi les deux se déclareraient réglés et l'un des deux
    virements resterait à faire sans que personne ne le sache."""
    tenant, banque = societe
    with use_tenant(tenant.id):
        premier = _ordre(tenant, banque)
        second = _ordre(tenant, banque)
        for ordre in (premier, second):
            export_transfer_order(ordre)
            mark_remitted(ordre)

        debit = _debit(tenant, banque, TOTAL)
        reconcile_transfer_order(premier, debit)

        with pytest.raises(ValidationError):
            reconcile_transfer_order(second, debit)

        second.refresh_from_db()
        assert second.state == AccTransferOrder.STATE_REMITTED
