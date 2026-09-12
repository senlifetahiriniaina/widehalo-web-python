"""G-2 — le patrimoine et le budget deviennent atteignables.

**Ce que la mesure disait avant ce lot.** `services/assets.py` et
`services/budgets.py` savent inscrire une immobilisation, calculer et
comptabiliser sa dotation, la céder, enregistrer un mouvement de provision,
construire un budget et produire son rapport d'écart. Tout cela est livré,
testé et documenté depuis la phase 2 — et **aucun de ces quatre modèles
n'apparaissait dans un seul gabarit**. Un exploitant devant un navigateur
ne pouvait inscrire aucune immobilisation, alors que l'annexe fiscale qui
les consomme, elle, était déjà produite.

Chaque test ci-dessous porte sur ce qui ARRIVE AU NAVIGATEUR ou sur ce qui
est ÉCRIT EN BASE après un POST — jamais sur un code de statut seul, que la
garde de E-6 refuse désormais.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from apps.accounting.models import (
    AccAccount,
    AccAsset,
    AccAssetDepreciation,
    AccBudget,
    AccFiscalYear,
    AccJournal,
    AccMove,
    AccPeriod,
    AccProvision,
)
from apps.accounting.services.budgets import add_budget_line, create_budget
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.models.workflow import ApprovalRequest
from apps.core.services import mfa as mfa_service
from apps.core.tests.utils import grant_module_access, grant_role, use_tenant
from django.test import Client
from django_otp.oath import totp

pytestmark = pytest.mark.django_db


def _connecte(user: User, tenant: Tenant) -> Client:
    """Ouvre une session, en franchissant le MFA quand le rôle l'exige.

    `direction` est dans `CORE_MFA_REQUIRED_ROLES` : `force_login` seul
    renverrait vers `/mfa/`, et l'assertion échouerait pour une raison
    étrangère à ce qu'on teste. Le piège a déjà coûté deux passes."""
    client = Client()
    reponse = client.post("/login/", {"email": user.email, "password": "Str0ngPassw0rd!23"})
    assert reponse.status_code == 302, reponse.content
    if mfa_service.mfa_required_for_user(user):
        client.get("/mfa/")
        device = mfa_service.enroll_device(user)
        reponse = client.post("/mfa/", {"token": str(totp(device.bin_key)).zfill(6)})
        assert reponse.status_code == 302, reponse.content
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


@pytest.fixture
def societe():
    """Une société comptable minimale, et un exploitant qui a les droits.

    `grant_module_access` plutôt que `grant_role` : les seuls rôles qui
    détiennent `accounting` en écriture sont soumis au MFA obligatoire."""
    tenant = Tenant.objects.create(code="G2", name="Societe patrimoine")
    user = User.objects.create_user(email="g2@example.com", password="Str0ngPassw0rd!23")
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
            code="2026-12",
            date_start=dt.date(2026, 12, 1),
            date_end=dt.date(2026, 12, 31),
        )
        journal = AccJournal.objects.create(
            tenant=tenant,
            code="OD",
            name="Operations diverses",
            type=AccJournal.TYPE_MISC,
            sequence_prefix="OD",
        )
        immobilisation = AccAccount.objects.create(
            tenant=tenant,
            code="215000",
            name="Materiel industriel",
            account_class="2",
            type=AccAccount.TYPE_ASSET,
        )
        dotation = AccAccount.objects.create(
            tenant=tenant,
            code="681100",
            name="Dotations aux amortissements",
            account_class="6",
            type=AccAccount.TYPE_EXPENSE,
        )
        cumul = AccAccount.objects.create(
            tenant=tenant,
            code="281500",
            name="Amortissements du materiel",
            account_class="2",
            type=AccAccount.TYPE_ASSET,
        )
        charge = AccAccount.objects.create(
            tenant=tenant,
            code="606000",
            name="Achats non stockes",
            account_class="6",
            type=AccAccount.TYPE_EXPENSE,
        )
    return {
        "tenant": tenant,
        "user": user,
        "client": _connecte(user, tenant),
        "exercice": exercice,
        "periode": periode,
        "journal": journal,
        "immobilisation": immobilisation,
        "dotation": dotation,
        "cumul": cumul,
        "charge": charge,
    }


def _inscrire(societe) -> AccAsset:
    reponse = societe["client"].post(
        "/accounting/assets/",
        {
            "label": "Presse hydraulique",
            "category": AccAsset.CATEGORY_CORPORELLE,
            "account_id": str(societe["immobilisation"].id),
            "acquisition_date": "2026-01-01",
            "acquisition_value_mga": "12000000",
            "useful_life_years": "10",
            "residual_value_mga": "0",
        },
    )
    assert reponse.status_code == 302, reponse.content
    with use_tenant(societe["tenant"].id):
        actif = AccAsset.objects.filter(label="Presse hydraulique").first()
    assert actif is not None, "L'écran n'a rien écrit en base."
    return actif


def test_une_immobilisation_sinscrit_depuis_lecran_et_apparait_en_liste(societe) -> None:
    actif = _inscrire(societe)

    with use_tenant(societe["tenant"].id):
        assert actif.state == AccAsset.STATE_ACTIVE
        assert actif.acquisition_value_mga == Decimal("12000000")
        # `register_asset` écrit AUSSI le mouvement d'acquisition : l'écran
        # passe bien par le service, il ne recrée pas l'objet à la main.
        assert actif.movements.count() == 1

    contenu = societe["client"].get("/accounting/assets/").content.decode()
    assert "Presse hydraulique" in contenu
    assert actif.reference in contenu


def test_le_plan_damortissement_se_calcule_sans_toucher_au_grand_livre(societe) -> None:
    """La distinction que la docstring du service défend, tenue à l'écran.

    `compute_annual_depreciation` sépare le CALCUL de sa COMPTABILISATION.
    Un plan qui se posterait au grand livre dès sa lecture interdirait de le
    relire avant de l'engager — la pratique comptable que le service nomme."""
    actif = _inscrire(societe)
    avant = AccMove.objects.filter(tenant=societe["tenant"]).count()

    reponse = societe["client"].post(
        f"/accounting/assets/{actif.id}/",
        {"action": "depreciate", "fiscal_year_id": str(societe["exercice"].id)},
    )
    assert reponse.status_code == 302, reponse.content

    with use_tenant(societe["tenant"].id):
        annuite = AccAssetDepreciation.objects.filter(asset=actif).first()
        assert annuite is not None, "Aucune annuité n'a été écrite."
        assert annuite.annual_dotation_mga == Decimal("1200000.0000")
        assert annuite.move is None, "Le calcul a posté une écriture sans qu'on le demande."
        assert AccMove.objects.filter(tenant=societe["tenant"]).count() == avant

    contenu = societe["client"].get(f"/accounting/assets/{actif.id}/").content.decode()
    assert "Calculée, non comptabilisée" in contenu
    # Le séparateur de milliers est une espace INSÉCABLE (U+00A0), pas une
    # espace ordinaire : le littéral est écrit ici plutôt que recopié de
    # `format_mga`, pour qu'ouvrir la convention n'ouvre pas aussi le test.
    assert "1\u00a0200\u00a0000\u00a0Ar" in contenu


def test_la_dotation_comptabilisee_produit_une_ecriture_publiee(societe) -> None:
    actif = _inscrire(societe)

    reponse = societe["client"].post(
        f"/accounting/assets/{actif.id}/",
        {
            "action": "depreciate_and_post",
            "fiscal_year_id": str(societe["exercice"].id),
            "journal_id": str(societe["journal"].id),
            "period_id": str(societe["periode"].id),
            "dotation_account_id": str(societe["dotation"].id),
            "accumulated_account_id": str(societe["cumul"].id),
        },
    )
    assert reponse.status_code == 302, reponse.content

    with use_tenant(societe["tenant"].id):
        annuite = AccAssetDepreciation.objects.filter(asset=actif).first()
        assert annuite is not None and annuite.move is not None, (
            "La dotation n'a produit aucune écriture."
        )
        assert annuite.move.state == AccMove.STATE_POSTED
        montants = sorted(
            (ligne.account.code, ligne.debit, ligne.credit) for ligne in annuite.move.lines.all()
        )
        assert montants == [
            ("281500", Decimal("0.0000"), Decimal("1200000.0000")),
            ("681100", Decimal("1200000.0000"), Decimal("0.0000")),
        ]


def test_la_cession_ferme_limmobilisation_et_lecran_le_dit(societe) -> None:
    actif = _inscrire(societe)

    reponse = societe["client"].post(
        f"/accounting/assets/{actif.id}/",
        {
            "action": "dispose",
            "disposal_date": "2026-06-30",
            "disposal_value_mga": "4000000",
        },
    )
    assert reponse.status_code == 302, reponse.content

    with use_tenant(societe["tenant"].id):
        actif.refresh_from_db()
        assert actif.state == AccAsset.STATE_DISPOSED
        assert actif.disposal_date == dt.date(2026, 6, 30)

    contenu = societe["client"].get(f"/accounting/assets/{actif.id}/").content.decode()
    assert "Cédée/mise au rebut" in contenu
    assert "Céder</" not in contenu, "L'écran propose encore de céder un actif déjà cédé."


def test_un_montant_illisible_devient_un_refus_lisible_jamais_un_500(societe) -> None:
    """La famille de défaut que T4bis a fermée sur les identifiants.

    `Decimal("douze millions")` lève `InvalidOperation`, qu'aucun
    gestionnaire de ce dépôt ne rattrape : sans la conversion gardée, ce
    formulaire rendait 500 sur une saisie maladroite."""
    reponse = societe["client"].post(
        "/accounting/assets/",
        {
            "label": "Presse",
            "category": AccAsset.CATEGORY_CORPORELLE,
            "account_id": str(societe["immobilisation"].id),
            "acquisition_date": "2026-01-01",
            "acquisition_value_mga": "douze millions",
            "useful_life_years": "10",
        },
    )
    assert reponse.status_code == 200, "Une saisie illisible ne doit ni passer ni faire 500."
    assert "Montant illisible" in reponse.content.decode()
    with use_tenant(societe["tenant"].id):
        assert not AccAsset.objects.filter(label="Presse").exists()


def test_un_mouvement_de_provision_sinscrit_et_sa_cloture_se_lit(societe) -> None:
    reponse = societe["client"].post(
        "/accounting/provisions/",
        {
            "nature": "Litige prud'homal",
            "account_id": str(societe["charge"].id),
            "fiscal_year_id": str(societe["exercice"].id),
            "opening_amount_mga": "500000",
            "dotation_mga": "300000",
            "reprise_mga": "100000",
        },
    )
    assert reponse.status_code == 302, reponse.content

    with use_tenant(societe["tenant"].id):
        provision = AccProvision.objects.filter(nature="Litige prud'homal").first()
        assert provision is not None
        assert provision.closing_amount_mga == Decimal("700000")

    contenu = societe["client"].get("/accounting/provisions/").content.decode()
    assert "Litige prud" in contenu
    assert "700\u00a0000\u00a0Ar" in contenu


def test_un_budget_recoit_sa_ligne_et_son_ecart_se_lit(societe) -> None:
    reponse = societe["client"].post(
        "/accounting/budgets/",
        {"name": "Budget 2026", "fiscal_year_id": str(societe["exercice"].id)},
    )
    assert reponse.status_code == 302, reponse.content
    with use_tenant(societe["tenant"].id):
        budget = AccBudget.objects.filter(name="Budget 2026").first()
    assert budget is not None

    reponse = societe["client"].post(
        f"/accounting/budgets/{budget.id}/",
        {
            "action": "add_line",
            "account_id": str(societe["charge"].id),
            "budgeted_amount_mga": "2000000",
        },
    )
    assert reponse.status_code == 302, reponse.content

    with use_tenant(societe["tenant"].id):
        assert budget.lines.count() == 1

    contenu = societe["client"].get(f"/accounting/budgets/{budget.id}/").content.decode()
    assert "606000" in contenu, "La ligne budgétée n'apparaît pas sur la fiche."
    assert "Tout l&#x27;exercice" in contenu or "Tout l'exercice" in contenu


def test_lapprobation_dun_budget_passe_par_lecran_de_validation(societe) -> None:
    """Le point du lot : l'écran SOUMET, l'approbateur DÉCIDE.

    Un bouton « Approuver » sur la fiche court-circuiterait le moteur qui
    devait gouverner la bascule. La réciproque de la règle posée en D-B."""
    tenant = societe["tenant"]
    with use_tenant(tenant.id):
        budget = create_budget(tenant=tenant, fiscal_year=societe["exercice"], name="Budget A")
        add_budget_line(budget, account=societe["charge"], budgeted_amount_mga=Decimal("1000000"))

    reponse = societe["client"].post(
        f"/accounting/budgets/{budget.id}/", {"action": "request_approval"}
    )
    assert reponse.status_code == 302, reponse.content

    with use_tenant(tenant.id):
        budget.refresh_from_db()
        assert budget.state == AccBudget.STATE_DRAFT, (
            "La demande a basculé le budget elle-même : le moteur d'approbation est contourné."
        )
        demande = ApprovalRequest.objects.filter(object_id=str(budget.id)).first()
        assert demande is not None, "Aucune demande d'approbation n'a été créée."
        assert demande.rule.approver_role == "direction"

    approbateur = User.objects.create_user(
        email="g2-direction@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(approbateur, "direction")
    UserTenantMembership.objects.get_or_create(
        user=approbateur, tenant=tenant, defaults={"is_default": True}
    )
    session_approbateur = _connecte(approbateur, tenant)

    contenu = session_approbateur.get("/approvals/").content.decode()
    assert f"/accounting/budgets/{budget.id}/" in contenu, (
        "L'écran de validation ne mène pas au budget concerné."
    )

    reponse = session_approbateur.post(
        "/approvals/",
        {"request_id": str(demande.id), "action": "approve", "comment": "Conforme au plan"},
    )
    assert reponse.status_code == 302, reponse.content

    with use_tenant(tenant.id):
        budget.refresh_from_db()
        assert budget.state == AccBudget.STATE_APPROVED, (
            "La décision d'approbation n'a produit aucun effet sur le budget."
        )


def test_un_refus_laisse_le_budget_modifiable(societe) -> None:
    """Un refus n'est pas une annulation : c'est une demande de révision."""
    tenant = societe["tenant"]
    with use_tenant(tenant.id):
        budget = create_budget(tenant=tenant, fiscal_year=societe["exercice"], name="Budget B")
        add_budget_line(budget, account=societe["charge"], budgeted_amount_mga=Decimal("50000"))

    societe["client"].post(f"/accounting/budgets/{budget.id}/", {"action": "request_approval"})
    with use_tenant(tenant.id):
        demande = ApprovalRequest.objects.filter(object_id=str(budget.id)).first()
    assert demande is not None

    approbateur = User.objects.create_user(
        email="g2-refus@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(approbateur, "direction")
    UserTenantMembership.objects.get_or_create(
        user=approbateur, tenant=tenant, defaults={"is_default": True}
    )
    _connecte(approbateur, tenant).post(
        "/approvals/",
        {"request_id": str(demande.id), "action": "reject", "comment": "Trop optimiste"},
    )

    with use_tenant(tenant.id):
        budget.refresh_from_db()
        assert budget.state == AccBudget.STATE_DRAFT

    # Et il accepte encore une ligne : un refus rend la main, il ne fige pas.
    reponse = societe["client"].post(
        f"/accounting/budgets/{budget.id}/",
        {
            "action": "add_line",
            "account_id": str(societe["charge"].id),
            "budgeted_amount_mga": "40000",
        },
    )
    assert reponse.status_code == 302
    with use_tenant(tenant.id):
        assert budget.lines.count() == 2


def test_un_role_en_lecture_seule_lit_et_ne_peut_pas_ecrire(societe) -> None:
    """La règle de C-1, sur les écrans neufs : on refuse à l'envoi ET on ne
    propose pas ce qu'on refusera."""
    tenant = societe["tenant"]
    lecteur = User.objects.create_user(email="g2-lecture@example.com", password="Str0ngPassw0rd!23")
    grant_role(lecteur, "controleur_gestion")
    UserTenantMembership.objects.get_or_create(
        user=lecteur, tenant=tenant, defaults={"is_default": True}
    )
    session = _connecte(lecteur, tenant)

    reponse = session.get("/accounting/assets/")
    assert reponse.status_code == 200
    contenu = reponse.content.decode()
    assert "Immobilisations" in contenu
    assert "Inscrire une immobilisation" not in contenu, (
        "L'écran propose un formulaire que l'envoi refusera."
    )

    refus = session.post(
        "/accounting/assets/",
        {
            "label": "Interdit",
            "category": AccAsset.CATEGORY_CORPORELLE,
            "account_id": str(societe["immobilisation"].id),
            "acquisition_date": "2026-01-01",
            "acquisition_value_mga": "1000",
            "useful_life_years": "5",
        },
    )
    assert refus.status_code == 403
    with use_tenant(tenant.id):
        assert not AccAsset.objects.filter(label="Interdit").exists()


def test_le_hub_des_operations_mene_aux_ecrans_neufs(societe) -> None:
    contenu = societe["client"].get("/accounting/operations/").content.decode()
    for chemin in ("/accounting/assets/", "/accounting/provisions/", "/accounting/budgets/"):
        assert chemin in contenu, f"Le hub ne mène pas à {chemin}."
