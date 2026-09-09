"""T6 (bloc E, BNK-5) — le fichier de virement de paie ne laisse rien fuir.

**Le critère, et il désigne lui-même son moyen de preuve** : « l'ordre de
virement de paie n'expose que bénéficiaire, montant et référence : aucune
donnée de rubrique n'est présente dans le fichier produit, **vérifié par un
test sur le contenu généré** ». Le cahier redit la même chose dans son
tableau de recette, sous « Cloisonnement de la paie ».

**Ce que la mesure a trouvé.** Le contenu produit EST conforme — le
générateur n'écrit que cinq colonnes, dont aucune ne porte de rubrique. Mais
il l'est **par accident** : les deux seuls tests qui touchent ce fichier
(`test_enrichments`, `test_pay9_regularization_delta`) assèrent ce qui doit
être PRÉSENT — le numéro de téléphone, le montant — et jamais ce qui doit
être ABSENT. Rien n'empêchait donc d'ajouter demain une colonne « détail des
retenues » pour rendre service à un client, et aucun test n'aurait rougi.

Un critère dont la propriété tient par chance n'est pas tenu : il est
seulement pas encore violé.

**Pourquoi la vérification porte sur le CONTENU et pas sur les en-têtes
seuls.** Un en-tête fermé ne dit rien de ce qu'on met dedans : écrire le
détail des cotisations dans la colonne `label` respecterait la liste des
colonnes et violerait le critère. Les deux sont donc vérifiés — le jeu de
colonnes ET l'absence de toute valeur de rubrique dans le texte produit.
"""

from __future__ import annotations

import csv
import io
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.payroll.models import PayPayslip, PayPayslipLine
from apps.payroll.services.batches import create_batch
from apps.payroll.services.mobile_money import (
    MOBILE_MONEY_FIELDNAMES,
    generate_bank_transfer_file,
    generate_mobile_money_transfer_file,
)
from apps.payroll.services.payslip import compute_payslip
from apps.payroll.tests.factories import (
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
)

pytestmark = pytest.mark.django_db

#: Les seules colonnes que le critère autorise, traduites dans les noms du
#: dépôt. « Bénéficiaire » se dit ici de deux façons — `employee_id` et la
#: coordonnée de paiement (téléphone ou IBAN) —, ce qui reste du
#: bénéficiaire et de rien d'autre. `label` porte le motif du virement, que
#: toute banque exige, et il est vérifié séparément.
COLONNES_AUTORISEES = {"employee_id", "reference", "phone", "iban", "amount_mga", "label"}

#: Un libellé de rubrique volontairement reconnaissable. S'il apparaît dans
#: le fichier, c'est qu'une donnée de paie en est sortie.
RUBRIQUE_TEMOIN = "RETENUE-SYNDICALE-TEMOIN"
MONTANT_RUBRIQUE_TEMOIN = Decimal("13579.0000")


@pytest.fixture
def lot_de_paie():
    tenant = Tenant.objects.create(code="PAY-BNK5", name="Cloisonnement paie")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        contrat = make_active_contract(
            tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1000000")
        )
        periode = make_period(tenant)
        bulletin = PayPayslip.objects.create(
            tenant=tenant,
            employee_id=contrat.employee_id,
            contract=contrat,
            period=periode,
            date_from=periode.date_from,
            date_to=periode.date_to,
            payment_method=PayPayslip.PAYMENT_MOBILE_MONEY,
        )
        compute_payslip(bulletin)
        # Une rubrique reconnaissable, écrite sur le bulletin : c'est
        # exactement le genre de ligne qui n'a rien à faire dans un ordre
        # de virement.
        PayPayslipLine.objects.create(
            tenant=tenant,
            payslip=bulletin,
            sequence=999,
            code="RSYND",
            label=RUBRIQUE_TEMOIN,
            category="deduction",
            amount=MONTANT_RUBRIQUE_TEMOIN,
        )
        bulletin.state = PayPayslip.STATE_COMPUTED
        bulletin.save(update_fields=["state"])
        lot = create_batch(periode)
        bulletin.refresh_from_db()
    return tenant, lot, bulletin, contrat


def test_the_transfer_file_declares_only_the_allowed_columns(lot_de_paie) -> None:
    """Le jeu de colonnes est FERMÉ, et le test le compare à la liste
    autorisée plutôt qu'à lui-même.

    Une assertion du genre « les colonnes sont celles du module » ne
    dirait rien : elle passerait encore le jour où quelqu'un ajoute
    `detail_retenues` aux deux endroits."""
    assert set(MOBILE_MONEY_FIELDNAMES) <= COLONNES_AUTORISEES, (
        f"Colonne(s) hors du minimum autorisé par BNK-5 : "
        f"{set(MOBILE_MONEY_FIELDNAMES) - COLONNES_AUTORISEES}"
    )


def test_no_payroll_item_leaks_into_the_mobile_money_file(lot_de_paie) -> None:
    """**Le critère mot pour mot** : aucune donnée de rubrique dans le
    fichier produit."""
    tenant, lot, bulletin, _contrat = lot_de_paie
    with use_tenant(tenant.id):
        contenu = generate_mobile_money_transfer_file(
            lot, phone_by_employee={str(bulletin.employee_id): "0341234567"}
        )

    assert RUBRIQUE_TEMOIN not in contenu, (
        "Un libellé de rubrique est présent dans l'ordre de virement : la paie "
        "n'est plus cloisonnée."
    )
    assert str(MONTANT_RUBRIQUE_TEMOIN) not in contenu
    assert "RSYND" not in contenu

    lues = list(csv.DictReader(io.StringIO(contenu)))
    assert lues, "Le fichier ne porte aucune ligne : le test ne vérifierait rien."
    for ligne in lues:
        assert set(ligne) <= COLONNES_AUTORISEES


def test_no_payroll_item_leaks_into_the_bank_file(lot_de_paie) -> None:
    """La même exigence sur l'autre voie.

    Deux générateurs, deux fichiers, un seul critère : ne vérifier que le
    premier laisserait la moitié du cloisonnement sans preuve — et c'est
    la voie bancaire classique, donc la plus utilisée."""
    tenant, lot, bulletin, _contrat = lot_de_paie
    with use_tenant(tenant.id):
        bulletin.payment_method = PayPayslip.PAYMENT_BANK
        bulletin.save(update_fields=["payment_method"])
        contenu = generate_bank_transfer_file(
            lot, iban_by_employee={str(bulletin.employee_id): "MG4600005030010101010101018"}
        )

    assert RUBRIQUE_TEMOIN not in contenu
    assert str(MONTANT_RUBRIQUE_TEMOIN) not in contenu
    lues = list(csv.DictReader(io.StringIO(contenu)))
    assert lues
    for ligne in lues:
        assert set(ligne) <= COLONNES_AUTORISEES


def test_the_label_carries_no_payroll_detail(lot_de_paie) -> None:
    """**Un jeu de colonnes fermé ne suffit pas.** Écrire le détail des
    cotisations dans `label` respecterait la liste des colonnes et
    violerait le critère : c'est le contenu qui est vérifié, pas seulement
    sa forme."""
    tenant, lot, bulletin, _contrat = lot_de_paie
    with use_tenant(tenant.id):
        contenu = generate_mobile_money_transfer_file(
            lot, phone_by_employee={str(bulletin.employee_id): "0341234567"}
        )
        libelles_de_rubriques = {
            ligne.label for ligne in PayPayslipLine.objects.filter(payslip=bulletin) if ligne.label
        }

    lues = list(csv.DictReader(io.StringIO(contenu)))
    for ligne in lues:
        motif = ligne.get("label") or ""
        fuites = {libelle for libelle in libelles_de_rubriques if libelle and libelle in motif}
        assert not fuites, f"Le motif du virement porte des rubriques : {fuites}"
