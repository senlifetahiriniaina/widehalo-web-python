"""F-1 — les deux dernières chaînes que personne ne pouvait déclencher.

**Ce que la 0.1.8 a mesuré.** EFA-3 y est reclassée de *tenue* à
*partielle* pour une seule raison : le moteur de rejeu existe depuis T4,
il est correct, il est testé, et **ses trois fonctions n'ont aucun appelant
de production**. Un critère tenu par du code que rien n'invoque n'est pas
tenu.

Et le régime de trésorerie : `record_cash_movement` annonçait dans sa
docstring, depuis A8, « un futur écran qui exposera cette fonction comme
un formulaire à deux champs ». Cet écran n'existait pas, et
`cash_basis_report` — qui le relit — n'avait pas d'appelant non plus. Le
maître d'ouvrage a tranché : le régime est dans le périmètre.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccMove, AccPeriod
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.tests.utils import grant_module_access, grant_role, use_tenant
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
    tenant = Tenant.objects.create(code="F1", name="Societe tresorerie")
    user = User.objects.create_user(email="f1@example.com", password="Str0ngPassw0rd!23")
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
            code="2026-03",
            date_start=dt.date(2026, 3, 1),
            date_end=dt.date(2026, 3, 31),
        )
        journal = AccJournal.objects.create(
            tenant=tenant,
            code="CAI",
            name="Caisse",
            type=AccJournal.TYPE_CASH,
            sequence_prefix="CAI",
        )
        caisse = AccAccount.objects.create(
            tenant=tenant,
            code="531000",
            name="Caisse",
            account_class="5",
            type=AccAccount.TYPE_CASH,
        )
        vente = AccAccount.objects.create(
            tenant=tenant,
            code="701000",
            name="Ventes",
            account_class="7",
            type=AccAccount.TYPE_INCOME,
        )
        achat = AccAccount.objects.create(
            tenant=tenant,
            code="601000",
            name="Achats",
            account_class="6",
            type=AccAccount.TYPE_EXPENSE,
        )
    return {
        "tenant": tenant,
        "client": _connecte(user, tenant),
        "exercice": exercice,
        "periode": periode,
        "journal": journal,
        "caisse": caisse,
        "vente": vente,
        "achat": achat,
    }


def _mouvement(societe, *, sens: str, montant: str, libelle: str, contrepartie):
    return societe["client"].post(
        "/accounting/cash/",
        {
            "fiscal_year_id": str(societe["exercice"].id),
            "direction": sens,
            "amount": montant,
            "date": "2026-03-10",
            "cash_account_id": str(societe["caisse"].id),
            "counterpart_account_id": str(contrepartie.id),
            "journal_id": str(societe["journal"].id),
            "period_id": str(societe["periode"].id),
            "label": libelle,
        },
    )


def test_un_mouvement_de_caisse_saisi_apparait_dans_le_rapport(societe) -> None:
    reponse = _mouvement(
        societe,
        sens="in",
        montant="250000",
        libelle="Vente comptoir",
        contrepartie=societe["vente"],
    )
    assert reponse.status_code == 302, reponse.content

    with use_tenant(societe["tenant"].id):
        # Pas de registre parallèle : la partie double reste l'unique source
        # de vérité, et le mouvement est une écriture PUBLIÉE normale.
        ecriture = AccMove.objects.filter(narration="Vente comptoir").first()
        assert ecriture is not None, "Le mouvement n'a produit aucune écriture."
        assert ecriture.state == AccMove.STATE_POSTED
        assert ecriture.total_debit == Decimal("250000.0000")

    contenu = (
        societe["client"]
        .get(f"/accounting/cash/?fiscal_year_id={societe['exercice'].id}")
        .content.decode()
    )
    assert "Vente comptoir" in contenu, "Le mouvement n'apparaît pas dans le rapport."
    assert "250 000 Ar" in contenu
    assert "Encaissement" in contenu


def test_letat_avec_solde_cumule_est_un_choix_de_lexploitant(societe) -> None:
    """Le cahier distingue deux sous-strates ; deviner laquelle demanderait
    de calculer le chiffre d'affaires réel, et le service refuse
    explicitement de le supposer."""
    _mouvement(
        societe,
        sens="in",
        montant="250000",
        libelle="Vente comptoir",
        contrepartie=societe["vente"],
    )
    _mouvement(
        societe,
        sens="out",
        montant="90000",
        libelle="Achat fournitures",
        contrepartie=societe["achat"],
    )

    recap = (
        societe["client"]
        .get(f"/accounting/cash/?fiscal_year_id={societe['exercice'].id}&mode=recap")
        .content.decode()
    )
    assert "Solde" not in recap

    smt = (
        societe["client"]
        .get(f"/accounting/cash/?fiscal_year_id={societe['exercice'].id}&mode=smt")
        .content.decode()
    )
    assert "Solde" in smt
    # 250 000 encaissés puis 90 000 décaissés : le solde cumulé vaut 160 000.
    assert "160 000 Ar" in smt


def test_un_montant_negatif_est_refuse_sans_rien_ecrire(societe) -> None:
    reponse = _mouvement(
        societe, sens="in", montant="-500", libelle="Erreur", contrepartie=societe["vente"]
    )
    assert reponse.status_code == 200
    assert "doit être positif" in reponse.content.decode()
    with use_tenant(societe["tenant"].id):
        assert not AccMove.objects.filter(narration="Erreur").exists()


def test_la_file_de_soumission_fiscale_a_enfin_un_ecran(societe) -> None:
    contenu = societe["client"].get("/accounting/einvoices/").content.decode()
    assert "File de soumission fiscale" in contenu
    # EFA-2 interdit de présenter une erreur sur l'attente : l'écran
    # l'explique au lieu de la signaler comme une panne.
    assert "Aucune pièce en attente de soumission" in contenu
    assert "form-error" not in contenu


def test_le_rejeu_se_declenche_depuis_lecran_et_rend_son_compte(societe) -> None:
    """Le geste manquant : `replay_pending_submissions` n'avait aucun
    appelant de production. L'écran rend un rapport chiffré, parce qu'un
    exploitant doit savoir où il en est sans lire un journal."""
    reponse = societe["client"].post("/accounting/einvoices/", {"action": "replay"})
    assert reponse.status_code == 200, reponse.content
    contenu = reponse.content.decode()
    assert "pièce(s) considérée(s)" in contenu


def test_le_point_dentree_de_rejeu_refuse_une_lecture(societe) -> None:
    """La garde d'écriture est au décorateur, et la route n'accepte que
    POST : un GET rend 405, jamais une redirection qui ressemblerait à un
    refus de droit."""
    assert societe["client"].get("/accounting/einvoices/replay/").status_code == 405
    assert societe["client"].post("/accounting/einvoices/replay/").status_code == 302


def test_un_role_en_lecture_seule_lit_la_file_et_ne_la_rejoue_pas(societe) -> None:
    tenant = societe["tenant"]
    lecteur = User.objects.create_user(email="f1-lecture@example.com", password="Str0ngPassw0rd!23")
    grant_role(lecteur, "controleur_gestion")
    UserTenantMembership.objects.get_or_create(
        user=lecteur, tenant=tenant, defaults={"is_default": True}
    )
    session = _connecte(lecteur, tenant)

    lecture = session.get("/accounting/einvoices/")
    assert lecture.status_code == 200
    assert "Rejouer la file" not in lecture.content.decode()
    assert session.post("/accounting/einvoices/", {"action": "replay"}).status_code == 403
    assert session.get("/accounting/einvoices/replay/").status_code == 403


def test_la_commande_de_rejeu_existe_et_ne_leve_pas(societe) -> None:
    """Une commande qu'aucun test n'exécute est aussi inerte qu'une
    fonction sans appelant — le motif que ce lot corrige."""
    from io import StringIO

    from django.core.management import call_command

    sortie = StringIO()
    call_command("rejouer_efactures", stdout=sortie)
    assert "piece(s) consideree(s)" in sortie.getvalue()


def test_les_deux_ecrans_sont_atteignables_depuis_le_hub(societe) -> None:
    contenu = societe["client"].get("/accounting/operations/").content.decode()
    assert "/accounting/cash/" in contenu
    assert "/accounting/einvoices/" in contenu
