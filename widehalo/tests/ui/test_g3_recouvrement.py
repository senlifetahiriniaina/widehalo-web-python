"""G-3 — le recouvrement, les virements, les échéances, la monnaie
électronique : quatre chaînes qui n'avaient aucune porte.

**La mesure qui décide de ce lot.** Les quatre services sont livrés,
testés, exposés en API — et deux transitions du cycle BNK-4,
`mark_remitted` et `reconcile_transfer_order`, **n'avaient aucun appelant
de production**. Le critère dit « son état de remise est suivi jusqu'au
rapprochement du débit correspondant » ; le suivi s'arrêtait à l'export.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from apps.accounting.models import (
    AccAccount,
    AccBankStatementLine,
    AccDunningAction,
    AccDunningLevel,
    AccFiscalYear,
    AccJournal,
    AccMobileMoneyStatementLine,
    AccMove,
    AccMoveLine,
    AccPayment,
    AccPeriod,
    AccTaxCalendar,
    AccTransferOrder,
)
from apps.accounting.services.moves import add_line, create_draft_move, post_move
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.tests.utils import grant_module_access, grant_role, use_tenant
from apps.partners.models import Partner
from django.test import Client

pytestmark = pytest.mark.django_db


def _connecte(user: User, tenant: Tenant) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


@pytest.fixture
def societe():
    tenant = Tenant.objects.create(code="G3", name="Societe tresorerie")
    user = User.objects.create_user(email="g3@example.com", password="Str0ngPassw0rd!23")
    grant_module_access(user, "accounting")
    UserTenantMembership.objects.get_or_create(
        user=user, tenant=tenant, defaults={"is_default": True}
    )
    with use_tenant(tenant.id):
        exercice = AccFiscalYear.objects.create(
            tenant=tenant,
            code="2026",
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
            code="OD",
            name="Operations diverses",
            type=AccJournal.TYPE_MISC,
            sequence_prefix="OD",
        )
        creance = AccAccount.objects.create(
            tenant=tenant,
            code="411000",
            name="Clients",
            account_class="4",
            type=AccAccount.TYPE_RECEIVABLE,
        )
        dette = AccAccount.objects.create(
            tenant=tenant,
            code="401000",
            name="Fournisseurs",
            account_class="4",
            type=AccAccount.TYPE_PAYABLE,
        )
        produit = AccAccount.objects.create(
            tenant=tenant,
            code="701000",
            name="Ventes",
            account_class="7",
            type=AccAccount.TYPE_INCOME,
        )
        charge = AccAccount.objects.create(
            tenant=tenant,
            code="606000",
            name="Achats",
            account_class="6",
            type=AccAccount.TYPE_EXPENSE,
        )
        banque = AccAccount.objects.create(
            tenant=tenant,
            code="512000",
            name="Banque",
            account_class="5",
            type=AccAccount.TYPE_BANK,
        )
        client_tiers = Partner.objects.create(tenant=tenant, name="Cliente Rasoa", nif="1234567890")
        fournisseur = Partner.objects.create(
            tenant=tenant, name="Fournisseur Andry", nif="9876543210"
        )
    return {
        "tenant": tenant,
        "user": user,
        "client": _connecte(user, tenant),
        "exercice": exercice,
        "periode": periode,
        "journal": journal,
        "creance": creance,
        "dette": dette,
        "produit": produit,
        "charge": charge,
        "banque": banque,
        "client_tiers": client_tiers,
        "fournisseur": fournisseur,
    }


def _creance_echue(societe) -> AccMoveLine:
    """Une créance client publiée, non lettrée, échue depuis longtemps."""
    with use_tenant(societe["tenant"].id):
        brouillon = create_draft_move(
            tenant=societe["tenant"],
            journal=societe["journal"],
            period=societe["periode"],
            date=dt.date(2026, 1, 10),
            narration="Facture cliente",
        )
        ligne = add_line(
            brouillon,
            account=societe["creance"],
            label="Cliente Rasoa",
            debit=Decimal("800000"),
        )
        add_line(brouillon, account=societe["produit"], label="Vente", credit=Decimal("800000"))
        ligne.partner_id = societe["client_tiers"].id
        ligne.due_date = dt.date(2026, 1, 20)
        ligne.save(update_fields=["partner_id", "due_date"])
        post_move(brouillon)
    return ligne


def _dette_ouverte(societe) -> AccMoveLine:
    with use_tenant(societe["tenant"].id):
        brouillon = create_draft_move(
            tenant=societe["tenant"],
            journal=societe["journal"],
            period=societe["periode"],
            date=dt.date(2026, 1, 12),
            narration="Facture fournisseur",
        )
        add_line(brouillon, account=societe["charge"], label="Achat", debit=Decimal("450000"))
        ligne = add_line(
            brouillon,
            account=societe["dette"],
            label="Fournisseur Andry",
            credit=Decimal("450000"),
        )
        ligne.partner_id = societe["fournisseur"].id
        ligne.save(update_fields=["partner_id"])
        post_move(brouillon)
    return ligne


def test_une_creance_echue_apparait_avec_son_palier_et_le_nom_du_client(societe) -> None:
    _creance_echue(societe)
    reponse = societe["client"].post("/accounting/dunning/", {"action": "seed_levels"})
    assert reponse.status_code == 302, reponse.content

    contenu = societe["client"].get("/accounting/dunning/").content.decode()
    assert "Cliente Rasoa" in contenu, "L'écran ne nomme pas le client de la créance."
    assert str(societe["client_tiers"].id) not in contenu, (
        "L'écran rend l'identifiant technique du tiers."
    )
    assert "800 000 Ar" in contenu
    with use_tenant(societe["tenant"].id):
        assert AccDunningLevel.objects.count() == 3


def test_une_relance_enregistree_se_relit(societe) -> None:
    ligne = _creance_echue(societe)
    societe["client"].post("/accounting/dunning/", {"action": "seed_levels"})
    with use_tenant(societe["tenant"].id):
        palier = AccDunningLevel.objects.order_by("level").first()
    assert palier is not None

    reponse = societe["client"].post(
        "/accounting/dunning/",
        {
            "action": "record",
            "move_line_id": str(ligne.id),
            "level_id": str(palier.id),
            "date_sent": "2026-03-01",
            "notes": "Appel telephonique",
        },
    )
    assert reponse.status_code == 302, reponse.content

    with use_tenant(societe["tenant"].id):
        relance = AccDunningAction.objects.filter(move_line=ligne).first()
        assert relance is not None
        assert relance.date_sent == dt.date(2026, 3, 1)

    contenu = societe["client"].get("/accounting/dunning/").content.decode()
    assert "Appel telephonique" in contenu


def test_lordre_de_virement_se_compose_a_partir_des_dettes_quil_regle(societe) -> None:
    dette = _dette_ouverte(societe)

    reponse = societe["client"].post(
        "/accounting/transfer-orders/",
        {
            "bank_account_id": str(societe["banque"].id),
            "execution_date": "2026-02-05",
            "move_line_ids": [str(dette.id)],
        },
    )
    assert reponse.status_code == 302, reponse.content

    with use_tenant(societe["tenant"].id):
        ordre = AccTransferOrder.objects.first()
        assert ordre is not None
        assert ordre.total_amount == Decimal("450000.0000")
        ligne = ordre.lines.first()
        assert ligne is not None
        # **Le lien vers la pièce est établi à la composition.** C'est la
        # moitié du critère qu'un formulaire de bénéficiaires libres aurait
        # perdue.
        assert str(ligne.document_id) == str(dette.id)
        assert ligne.beneficiary_label == "Fournisseur Andry"


def test_le_cycle_complet_va_jusquau_rapprochement_du_debit(societe) -> None:
    """La propriété qui fait tenir BNK-4.

    `mark_remitted` et `reconcile_transfer_order` n'avaient aucun appelant :
    le suivi s'arrêtait à l'export, et un ordre jamais exécuté ne se voyait
    qu'au moment où le fournisseur appelait."""
    dette = _dette_ouverte(societe)
    societe["client"].post(
        "/accounting/transfer-orders/",
        {
            "bank_account_id": str(societe["banque"].id),
            "execution_date": "2026-02-05",
            "move_line_ids": [str(dette.id)],
        },
    )
    with use_tenant(societe["tenant"].id):
        ordre = AccTransferOrder.objects.first()
    assert ordre is not None

    export = societe["client"].post(
        f"/accounting/transfer-orders/{ordre.id}/", {"action": "export"}
    )
    assert export.status_code == 200
    assert export["Content-Type"] == "text/csv"
    fichier = export.content.decode()
    assert "beneficiary,account,amount,reference" in fichier
    assert "Fournisseur Andry" in fichier
    with use_tenant(societe["tenant"].id):
        ordre.refresh_from_db()
        assert ordre.state == AccTransferOrder.STATE_EXPORTED

    remise = societe["client"].post(f"/accounting/transfer-orders/{ordre.id}/", {"action": "remit"})
    assert remise.status_code == 302, remise.content
    with use_tenant(societe["tenant"].id):
        ordre.refresh_from_db()
        assert ordre.state == AccTransferOrder.STATE_REMITTED

    # L'écran de liste doit signaler l'ordre « en vol ».
    liste = societe["client"].get("/accounting/transfer-orders/").content.decode()
    assert "En vol" in liste

    with use_tenant(societe["tenant"].id):
        debit = AccBankStatementLine.objects.create(
            tenant=societe["tenant"],
            bank_account=societe["banque"],
            import_batch_id="00000000-0000-0000-0000-000000000001",
            statement_date=dt.date(2026, 2, 6),
            label="Virement fournisseurs",
            reference_external="VIR-001",
            amount_mga=ordre.total_amount,
            direction=AccBankStatementLine.DIRECTION_OUT,
        )

    rapprochement = societe["client"].post(
        f"/accounting/transfer-orders/{ordre.id}/",
        {"action": "reconcile", "statement_line_id": str(debit.id)},
    )
    assert rapprochement.status_code == 302, rapprochement.content
    with use_tenant(societe["tenant"].id):
        ordre.refresh_from_db()
        assert ordre.state == AccTransferOrder.STATE_RECONCILED
        assert ordre.statement_line_id == debit.id


def test_un_debit_discordant_est_refuse_et_lecran_le_dit(societe) -> None:
    dette = _dette_ouverte(societe)
    societe["client"].post(
        "/accounting/transfer-orders/",
        {
            "bank_account_id": str(societe["banque"].id),
            "execution_date": "2026-02-05",
            "move_line_ids": [str(dette.id)],
        },
    )
    with use_tenant(societe["tenant"].id):
        ordre = AccTransferOrder.objects.first()
    assert ordre is not None
    societe["client"].post(f"/accounting/transfer-orders/{ordre.id}/", {"action": "export"})
    societe["client"].post(f"/accounting/transfer-orders/{ordre.id}/", {"action": "remit"})

    with use_tenant(societe["tenant"].id):
        debit = AccBankStatementLine.objects.create(
            tenant=societe["tenant"],
            bank_account=societe["banque"],
            import_batch_id="00000000-0000-0000-0000-000000000002",
            statement_date=dt.date(2026, 2, 6),
            label="Virement partiel",
            reference_external="VIR-002",
            amount_mga=Decimal("400000"),
            direction=AccBankStatementLine.DIRECTION_OUT,
        )

    reponse = societe["client"].post(
        f"/accounting/transfer-orders/{ordre.id}/",
        {"action": "reconcile", "statement_line_id": str(debit.id)},
    )
    assert reponse.status_code == 200
    assert "ne correspond pas au montant de l" in reponse.content.decode()
    with use_tenant(societe["tenant"].id):
        ordre.refresh_from_db()
        assert ordre.state == AccTransferOrder.STATE_REMITTED


def test_lecheancier_fiscal_se_seme_et_se_lit(societe) -> None:
    reponse = societe["client"].post("/accounting/tax-calendar/", {"action": "seed"})
    assert reponse.status_code == 302, reponse.content
    with use_tenant(societe["tenant"].id):
        assert AccTaxCalendar.objects.count() > 0

    # L'horizon par défaut est de 90 jours : les échéances semées portent des
    # dates réelles, donc on élargit pour que l'écran en montre forcément.
    contenu = societe["client"].get("/accounting/tax-calendar/?within_days=730").content.decode()
    assert "Aucune échéance dans cet horizon" not in contenu, (
        "Les échéances semées n'apparaissent pas à l'écran."
    )


def test_une_echeance_saisie_a_la_main_apparait(societe) -> None:
    """L'écran ne montre que l'À-VENIR : la date du test suit l'horloge.

    Écrire une date fixe faisait passer ce test jusqu'au jour où elle est
    devenue passée — et il aurait alors accusé l'écran d'un défaut qui
    n'existe pas."""
    echeance = dt.date.today() + dt.timedelta(days=30)
    reponse = societe["client"].post(
        "/accounting/tax-calendar/",
        {
            "action": "create",
            "declaration_type": AccTaxCalendar.DECLARATION_TVA,
            "label": "TVA de janvier",
            "due_date": echeance.isoformat(),
            "periodicity": AccTaxCalendar.PERIODICITY_MONTHLY,
        },
    )
    assert reponse.status_code == 302, reponse.content
    contenu = societe["client"].get("/accounting/tax-calendar/?within_days=730").content.decode()
    assert "TVA de janvier" in contenu


def test_une_echeance_deja_passee_le_dit_au_lieu_de_disparaitre(societe) -> None:
    """La perte silencieuse que la mesure a trouvée en écrivant ce lot.

    `upcoming_deadlines` écarte les dates passées. Une saisie rétrospective
    était donc enregistrée puis **disparaissait de l'écran sans un mot** :
    l'utilisateur croit avoir raté son enregistrement et recommence."""
    passee = dt.date.today() - dt.timedelta(days=10)
    reponse = societe["client"].post(
        "/accounting/tax-calendar/",
        {
            "action": "create",
            "declaration_type": AccTaxCalendar.DECLARATION_TVA,
            "label": "TVA rétrospective",
            "due_date": passee.isoformat(),
            "periodicity": AccTaxCalendar.PERIODICITY_MONTHLY,
        },
        follow=True,
    )
    assert reponse.status_code == 200
    assert "en dehors de l" in reponse.content.decode()
    with use_tenant(societe["tenant"].id):
        assert AccTaxCalendar.objects.filter(label="TVA rétrospective").exists()


def test_un_releve_de_monnaie_electronique_se_charge_puis_se_rapproche(societe) -> None:
    from django.core.files.uploadedfile import SimpleUploadedFile

    csv = b"date,reference,amount,direction\n2026-01-20,MVOLA-1,120000,in\n"
    reponse = societe["client"].post(
        "/accounting/mobile-money/",
        {
            "action": "import",
            "statement": SimpleUploadedFile("releve.csv", csv, content_type="text/csv"),
        },
    )
    assert reponse.status_code == 200
    assert "1 ligne chargée" in reponse.content.decode()

    with use_tenant(societe["tenant"].id):
        ligne = AccMobileMoneyStatementLine.objects.first()
        assert ligne is not None
        reglement = AccPayment.objects.create(
            tenant=societe["tenant"],
            journal=societe["journal"],
            date=dt.date(2026, 1, 20),
            amount=Decimal("120000"),
            direction=AccPayment.DIRECTION_INBOUND,
            method=AccPayment.METHOD_MOBILE_MONEY,
            reference_external="MVOLA-1",
        )

    reponse = societe["client"].post(
        "/accounting/mobile-money/",
        {"action": "reconcile", "line_id": str(ligne.id), "payment_id": str(reglement.id)},
    )
    assert reponse.status_code == 302, reponse.content
    with use_tenant(societe["tenant"].id):
        ligne.refresh_from_db()
        assert ligne.state == AccMobileMoneyStatementLine.STATE_MATCHED
        assert ligne.matched_payment_id == reglement.id

    contenu = societe["client"].get("/accounting/mobile-money/").content.decode()
    assert "Aucune ligne en attente" in contenu


def test_un_releve_illisible_est_refuse_sans_rien_ecrire(societe) -> None:
    from django.core.files.uploadedfile import SimpleUploadedFile

    csv = b"date,reference,amount,direction\n2026-01-20,MVOLA-1,beaucoup,in\n"
    reponse = societe["client"].post(
        "/accounting/mobile-money/",
        {
            "action": "import",
            "statement": SimpleUploadedFile("releve.csv", csv, content_type="text/csv"),
        },
    )
    assert reponse.status_code == 200
    assert "Montant invalide" in reponse.content.decode()


def test_un_role_en_lecture_seule_ne_peut_pas_composer_un_ordre(societe) -> None:
    tenant = societe["tenant"]
    lecteur = User.objects.create_user(email="g3-lecture@example.com", password="Str0ngPassw0rd!23")
    grant_role(lecteur, "controleur_gestion")
    UserTenantMembership.objects.get_or_create(
        user=lecteur, tenant=tenant, defaults={"is_default": True}
    )
    session = _connecte(lecteur, tenant)

    lecture = session.get("/accounting/transfer-orders/")
    assert lecture.status_code == 200
    assert "Composer un ordre" not in lecture.content.decode()

    dette = _dette_ouverte(societe)
    refus = session.post(
        "/accounting/transfer-orders/",
        {
            "bank_account_id": str(societe["banque"].id),
            "execution_date": "2026-02-05",
            "move_line_ids": [str(dette.id)],
        },
    )
    assert refus.status_code == 403
    with use_tenant(tenant.id):
        assert not AccTransferOrder.objects.exists()


def test_le_hub_mene_aux_quatre_ecrans_de_g3(societe) -> None:
    contenu = societe["client"].get("/accounting/operations/").content.decode()
    for chemin in (
        "/accounting/dunning/",
        "/accounting/transfer-orders/",
        "/accounting/tax-calendar/",
        "/accounting/mobile-money/",
    ):
        assert chemin in contenu, f"Le hub ne mène pas à {chemin}."


def test_lecriture_nest_jamais_postee_par_un_ordre_de_virement(societe) -> None:
    """L'interdit du §4.4, tenu à l'écran.

    Un ordre de virement est une INSTRUCTION donnée à la banque ; l'écriture
    naît du débit constaté, par le rapprochement bancaire."""
    dette = _dette_ouverte(societe)
    with use_tenant(societe["tenant"].id):
        avant = AccMove.objects.count()
    societe["client"].post(
        "/accounting/transfer-orders/",
        {
            "bank_account_id": str(societe["banque"].id),
            "execution_date": "2026-02-05",
            "move_line_ids": [str(dette.id)],
        },
    )
    with use_tenant(societe["tenant"].id):
        ordre = AccTransferOrder.objects.first()
        assert ordre is not None
    societe["client"].post(f"/accounting/transfer-orders/{ordre.id}/", {"action": "export"})
    with use_tenant(societe["tenant"].id):
        assert AccMove.objects.count() == avant
