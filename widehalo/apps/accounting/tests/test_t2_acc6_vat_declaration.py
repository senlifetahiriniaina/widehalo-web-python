"""T2 (ACC-6) — « La déclaration de TVA d'une période se rapproche à
l'ariary près de la somme des écritures de TVA de la période, avec un état
justificatif ligne à ligne. »

**Ce qui existait avant ce lot : rien**, et le dépôt l'écrivait lui-même.
`services/fiscal_export.py` disait, à la ligne ACC-TVA de son registre :
« Aucune déclaration TVA dédiée (pas de modèle `acc_vat_declaration` à ce
stade) ». L'audit classait ACC-6 « le service de déclaration existe, le
rapprochement n'a pas été vérifié » — la mesure dit autre chose : il n'y
avait ni objet à rapprocher, ni état justificatif. La liasse ANNUELLE
(IS/IR) existait, la déclaration PÉRIODIQUE non.

**Le test qui porte réellement le critère est celui qui creuse l'écart.**
Vérifier qu'une déclaration bien formée tombe juste ne prouve pas
grand-chose : deux sommes calculées depuis les mêmes lignes tombent
toujours juste. Ce qui compte est qu'une écriture manuelle sur un compte de
TVA — parfaitement légale, et invisible côté déclaration — soit VUE, et que
le dépôt soit alors refusé.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import (
    AccAccount,
    AccMove,
    AccTax,
    AccVatDeclaration,
    AccVatDeclarationLine,
)
from apps.accounting.services.vat_declaration import (
    build_vat_declaration,
    file_vat_declaration,
    unjustified_book_lines,
    vat_declaration_detail,
)
from apps.accounting.tests.factories import (
    AccAccountFactory,
    AccJournalFactory,
    AccMoveFactory,
    AccMoveLineFactory,
    AccPeriodFactory,
    AccTaxFactory,
)
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def societe():
    return Tenant.objects.create(code="ACC6", name="Déclaration TVA SARL")


@pytest.fixture
def contexte(societe):
    """Une période, un compte de TVA collectée, une taxe de vente à 20 %,
    un compte de produit. Le strict nécessaire pour qu'une vente taxée
    existe."""
    with use_tenant(societe.id):
        periode = AccPeriodFactory(
            tenant=societe,
            code="2026-03",
            date_start=dt.date(2026, 3, 1),
            date_end=dt.date(2026, 3, 31),
        )
        compte_tva = AccAccountFactory(
            tenant=societe,
            code="44571",
            name="TVA collectée",
            account_class=4,
            type=AccAccount.TYPE_PAYABLE,
        )
        compte_produit = AccAccountFactory(
            tenant=societe,
            code="70100",
            name="Ventes",
            account_class=7,
            type=AccAccount.TYPE_INCOME,
        )
        taxe = AccTaxFactory(
            tenant=societe,
            code="TVA20",
            type=AccTax.TYPE_SALE,
            rate=Decimal("20.000"),
            account_collected=compte_tva,
        )
        journal = AccJournalFactory(tenant=societe)
    return periode, taxe, compte_tva, compte_produit, journal


def _vente_taxee(societe, contexte, *, ht: Decimal, tva: Decimal, publiee: bool = True):
    """Une vente : produit au crédit, TVA collectée au crédit, client au
    débit. Publiée par écriture directe de l'état — le service `post_move`
    exigerait un équilibre parfait et une séquence, ce qui n'ajouterait
    rien à ce que ce fichier mesure."""
    periode, taxe, compte_tva, compte_produit, journal = contexte
    ecriture = AccMoveFactory(
        tenant=societe, journal=journal, period=periode, date=dt.date(2026, 3, 10)
    )
    if publiee:
        AccMove.objects.filter(pk=ecriture.pk).update(state=AccMove.STATE_POSTED)
        ecriture.refresh_from_db()
    AccMoveLineFactory(
        tenant=societe,
        move=ecriture,
        account=compte_produit,
        label="Vente de mars",
        credit=ht,
        debit=Decimal(0),
    )
    AccMoveLineFactory(
        tenant=societe,
        move=ecriture,
        account=compte_tva,
        label="TVA collectée",
        credit=tva,
        debit=Decimal(0),
        tax=taxe,
        tax_base=ht,
    )
    return ecriture


def test_a_well_formed_period_reconciles_to_the_ariary(societe, contexte) -> None:
    """Le témoin. Sans lui, un rapprochement qui échouerait toujours
    donnerait le même vert que le test suivant."""
    with use_tenant(societe.id):
        _vente_taxee(societe, contexte, ht=Decimal("1000000"), tva=Decimal("200000"))
        declaration = build_vat_declaration(contexte[0])

        assert declaration.collected_mga == Decimal("200000.0000")
        assert declaration.collected_books_mga == Decimal("200000.0000")
        assert declaration.ecart_mga == Decimal(0)
        assert declaration.is_reconciled
        assert declaration.net_mga == Decimal("200000.0000")

        ligne = declaration.lines.get()
        assert ligne.sens == AccVatDeclarationLine.SENS_COLLECTED
        assert ligne.base_mga == Decimal("1000000.0000")
        assert ligne.move_line_count == 1


def test_a_manual_entry_on_the_vat_account_opens_a_measurable_gap(societe, contexte) -> None:
    """**LE critère.** Une écriture manuelle sur un compte de TVA sans taxe
    désignée est parfaitement légale — un rappel, une régularisation. Elle
    apparaît côté livres et pas côté déclaration.

    L'écart est alors la mesure exacte de ce qui reste à justifier, et il
    doit être NOMMÉ : « il manque 50 000 Ar côté collecté » désigne
    l'écriture à chercher, là où « ça ne tombe pas juste » n'aide
    personne."""
    periode, _taxe, compte_tva, _produit, journal = contexte
    with use_tenant(societe.id):
        _vente_taxee(societe, contexte, ht=Decimal("1000000"), tva=Decimal("200000"))
        regularisation = AccMoveFactory(
            tenant=societe, journal=journal, period=periode, date=dt.date(2026, 3, 20)
        )
        AccMove.objects.filter(pk=regularisation.pk).update(state=AccMove.STATE_POSTED)
        AccMoveLineFactory(
            tenant=societe,
            move=regularisation,
            account=compte_tva,
            label="Rappel TVA sur exercice antérieur",
            credit=Decimal("50000"),
            debit=Decimal(0),
        )

        declaration = build_vat_declaration(periode)
        assert not declaration.is_reconciled
        assert declaration.ecart_mga == Decimal("-50000.0000"), (
            "L'écart doit être signé et chiffré : c'est lui qui désigne l'écriture à retrouver."
        )

        non_justifiees = unjustified_book_lines(declaration)
        assert len(non_justifiees) == 1
        assert non_justifiees[0]["libelle"] == "Rappel TVA sur exercice antérieur"


def test_filing_is_refused_while_the_gap_stands(societe, contexte) -> None:
    """La moitié opérante du critère : déposer une déclaration qui ne tombe
    pas juste transmet à l'administration un montant que les livres ne
    justifient pas."""
    periode, _taxe, compte_tva, _produit, journal = contexte
    with use_tenant(societe.id):
        _vente_taxee(societe, contexte, ht=Decimal("1000000"), tva=Decimal("200000"))
        ecart = AccMoveFactory(
            tenant=societe, journal=journal, period=periode, date=dt.date(2026, 3, 21)
        )
        AccMove.objects.filter(pk=ecart.pk).update(state=AccMove.STATE_POSTED)
        AccMoveLineFactory(
            tenant=societe, move=ecart, account=compte_tva, credit=Decimal("7"), debit=Decimal(0)
        )

        declaration = build_vat_declaration(periode)
        with pytest.raises(ValidationError) as refus:
            file_vat_declaration(declaration)
    assert "cart" in " ".join(refus.value.messages)


def test_a_reconciled_declaration_can_be_filed_and_no_longer_regenerates(societe, contexte) -> None:
    """Ce qui a été transmis à l'administration ne se réécrit pas parce
    qu'une écriture a bougé depuis."""
    with use_tenant(societe.id):
        _vente_taxee(societe, contexte, ht=Decimal("1000000"), tva=Decimal("200000"))
        declaration = file_vat_declaration(build_vat_declaration(contexte[0]))
        assert declaration.state == AccVatDeclaration.STATE_FILED

        with pytest.raises(ValidationError):
            build_vat_declaration(contexte[0])


def test_a_gap_below_one_ariary_still_reconciles(societe, contexte) -> None:
    """« À l'ariary près », littéralement.

    L'ariary n'a pas de subdivision en circulation et les colonnes portent
    quatre décimales pour les calculs intermédiaires : juger le
    rapprochement au dix-millième refuserait des déclarations parfaitement
    correctes."""
    periode, _taxe, compte_tva, _produit, journal = contexte
    with use_tenant(societe.id):
        _vente_taxee(societe, contexte, ht=Decimal("1000000"), tva=Decimal("200000"))
        arrondi = AccMoveFactory(
            tenant=societe, journal=journal, period=periode, date=dt.date(2026, 3, 22)
        )
        AccMove.objects.filter(pk=arrondi.pk).update(state=AccMove.STATE_POSTED)
        AccMoveLineFactory(
            tenant=societe,
            move=arrondi,
            account=compte_tva,
            credit=Decimal("0.4000"),
            debit=Decimal(0),
        )
        declaration = build_vat_declaration(periode)
        assert declaration.ecart_mga != 0
        assert declaration.is_reconciled


def test_draft_moves_are_never_declared(societe, contexte) -> None:
    """Un brouillon n'est pas une écriture : le déclarer reviendrait à
    déclarer une intention."""
    with use_tenant(societe.id):
        _vente_taxee(societe, contexte, ht=Decimal("1000000"), tva=Decimal("200000"), publiee=False)
        declaration = build_vat_declaration(contexte[0])
        assert declaration.collected_mga == Decimal(0)
        assert not declaration.lines.exists()


def test_the_line_by_line_statement_returns_one_row_per_taxed_line(societe, contexte) -> None:
    """« Avec un état justificatif ligne à ligne » — au sens fort : une
    ligne d'écriture par ligne d'état, pas seulement un total par taxe."""
    with use_tenant(societe.id):
        _vente_taxee(societe, contexte, ht=Decimal("1000000"), tva=Decimal("200000"))
        _vente_taxee(societe, contexte, ht=Decimal("500000"), tva=Decimal("100000"))
        declaration = build_vat_declaration(contexte[0])
        detail = vat_declaration_detail(declaration)

    assert len(detail) == 2
    assert {ligne["taxe"] for ligne in detail} == {"TVA20"}
    assert sum(ligne["credit_mga"] for ligne in detail) == Decimal("300000.0000")


def test_the_statement_never_carries_a_full_account_number(societe, contexte) -> None:
    """§9.2 : « Aucun numéro de compte complet dans une trace ou une charge
    utile archivée. » Un état justificatif exporté EST une trace archivée —
    la même règle que la projection de sortie du hub de flux s'y applique."""
    with use_tenant(societe.id):
        _vente_taxee(societe, contexte, ht=Decimal("1000000"), tva=Decimal("200000"))
        detail = vat_declaration_detail(build_vat_declaration(contexte[0]))

    assert detail
    for ligne in detail:
        assert "44571" not in str(ligne.values()), (
            "Le numéro de compte complet figure dans l'état justificatif."
        )
        assert ligne["classe_pcg"] in {"4", "7"}


def test_a_second_generation_replaces_the_lines_rather_than_stacking_them(
    societe, contexte
) -> None:
    """Idempotence sur la période. Sans elle, chaque consultation d'écran
    doublerait l'état justificatif."""
    with use_tenant(societe.id):
        _vente_taxee(societe, contexte, ht=Decimal("1000000"), tva=Decimal("200000"))
        build_vat_declaration(contexte[0])
        declaration = build_vat_declaration(contexte[0])
        assert declaration.lines.count() == 1
        assert AccVatDeclaration.objects.count() == 1


def test_the_screen_shows_the_gap_and_where_it_comes_from(societe, contexte) -> None:
    """L'écran est ce qui rend le critère utilisable par un comptable.

    Un rapprochement qui ne vit qu'en service et en API est un
    rapprochement que personne ne lit — et le comptable est précisément
    celui qui doit voir d'où vient l'écart AVANT de déposer, plutôt que de
    le découvrir au contrôle."""
    from django.test import Client

    from apps.core.models.user import User

    periode, _taxe, compte_tva, _produit, journal = contexte
    with use_tenant(societe.id):
        _vente_taxee(societe, contexte, ht=Decimal("1000000"), tva=Decimal("200000"))
        rappel = AccMoveFactory(
            tenant=societe, journal=journal, period=periode, date=dt.date(2026, 3, 25)
        )
        AccMove.objects.filter(pk=rappel.pk).update(state=AccMove.STATE_POSTED)
        AccMoveLineFactory(
            tenant=societe,
            move=rappel,
            account=compte_tva,
            label="Rappel a justifier",
            credit=Decimal("12345"),
            debit=Decimal(0),
        )
        User.objects.create_user(email="acc6-ecran@example.com", password="Str0ngPassw0rd!23")

    client = Client()
    client.force_login(User.objects.get(email="acc6-ecran@example.com"))
    session = client.session
    session["tenant_id"] = str(societe.id)
    session.save()

    corps = client.get(
        "/accounting/reports/vat-declaration/", {"period_id": str(periode.id)}
    ).content.decode()

    assert "Rappel a justifier" in corps, (
        "L'écran n'affiche pas la ligne non justifiée : l'écart est annoncé sans dire où chercher."
    )
    assert "12345" in corps
    assert "44571" not in corps, (
        "Le numéro de compte complet figure à l'écran — §9.2 ne le tolère dans aucune trace."
    )
