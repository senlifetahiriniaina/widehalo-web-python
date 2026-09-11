"""D-B — une facture au-dessus du seuil peut enfin être validée.

**Le défaut, mesuré avant d'écrire une ligne.** `validate_invoice` crée une
`ApprovalRequest` et lève `ApprovalRequiredError` dès que le montant dépasse
le palier ; les trois paliers sont semés EN PRODUCTION pour toute société
(`seed_accounting.py:121`) ; et `apps/accounting/views.py` ne traite aucune
approbation. Aucun écran du produit, pour aucun rôle, ne décidait une
demande — seul `POST /api/v1/approvals/{id}/decide` le pouvait. La facture
restait bloquée pour toujours.

Les quatre propriétés vérifiées ici portent sur ce qui ARRIVE AU
NAVIGATEUR, jamais sur le service seul :

1. Une facture au-dessus du seuil est refusée, et la demande apparaît sur
   l'écran de son approbateur.
2. Approuver depuis l'écran débloque réellement la validation.
3. Qui n'est pas approbateur ne peut pas décider, et l'écran le dit.
4. Sans rien à valider, l'écran dit quoi attendre plutôt que de rester vide.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccMove, AccPeriod
from apps.accounting.services.invoices import (
    DOUBLE_VALIDATION_THRESHOLD_MGA,
    ApprovalRequiredError,
    create_invoice,
    ensure_default_approval_thresholds,
    validate_invoice,
)
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.models.workflow import ApprovalRequest
from apps.core.services import mfa as mfa_service
from apps.core.tests.utils import grant_module_access, grant_role, use_tenant
from django.contrib.auth.models import Permission
from django.test import Client
from django_otp.oath import totp

pytestmark = pytest.mark.django_db


def _connecte(user: User, tenant: Tenant) -> Client:
    """Ouvre une session, en franchissant le MFA quand le rôle l'exige.

    `comptable` est dans `CORE_MFA_REQUIRED_ROLES` : `force_login` seul
    renverrait vers `/mfa/` et l'assertion échouerait pour une raison
    étrangère à ce qu'on teste."""
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


def _societe_avec_facture_au_dessus_du_seuil() -> tuple[Tenant, AccMove, User]:
    tenant = Tenant.objects.create(code="DB1", name="Societe validation")
    emetteur = User.objects.create_user(
        email="db-emetteur@example.com", password="Str0ngPassw0rd!23"
    )
    grant_module_access(emetteur, "accounting")
    emetteur.user_permissions.add(
        *Permission.objects.filter(
            codename__in=("validate_accmove", "cancel_accmove"),
            content_type__app_label="accounting",
        )
    )
    UserTenantMembership.objects.get_or_create(
        user=emetteur, tenant=tenant, defaults={"is_default": True}
    )

    with use_tenant(tenant.id):
        ensure_default_approval_thresholds(tenant)
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
            code="VTE",
            name="Ventes",
            type=AccJournal.TYPE_SALE,
            sequence_prefix="VTE",
        )
        client_compte = AccAccount.objects.create(
            tenant=tenant, code="411000", name="Clients", account_class="4", type="receivable"
        )
        produit = AccAccount.objects.create(
            tenant=tenant, code="701000", name="Ventes", account_class="7", type="income"
        )
        facture = create_invoice(
            tenant=tenant,
            journal=journal,
            period=periode,
            date=dt.date(2026, 1, 15),
            partner_id=None,
            receivable_account=client_compte,
            income_lines=[
                {
                    "account": produit,
                    "amount": DOUBLE_VALIDATION_THRESHOLD_MGA + Decimal("1000000"),
                    "label": "Marché",
                }
            ],
        )
    return tenant, facture, emetteur


def test_an_invoice_over_the_threshold_surfaces_on_its_approvers_screen() -> None:
    tenant, facture, emetteur = _societe_avec_facture_au_dessus_du_seuil()

    with use_tenant(tenant.id), pytest.raises(ApprovalRequiredError):
        validate_invoice(facture, emetteur)

    approbateur = User.objects.create_user(
        email="db-comptable@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(approbateur, "comptable")
    UserTenantMembership.objects.get_or_create(
        user=approbateur, tenant=tenant, defaults={"is_default": True}
    )

    contenu = _connecte(approbateur, tenant).get("/approvals/").content.decode()
    assert "Aucune validation en attente" not in contenu, (
        "La demande créée par la facture n'apparaît pas sur l'écran de son approbateur."
    )
    assert f"/accounting/{facture.id}/" in contenu, "L'écran ne mène pas à la pièce concernée."


def test_approving_from_the_screen_actually_unblocks_the_invoice() -> None:
    """La propriété qui fait tenir le lot.

    **Deux corrections successives, chacune imposée par la mesure.** La
    première version s'arrêtait au statut de la demande — et la
    falsification F111 ne mordait pas, à juste titre : « la demande est
    approuvée » ne dit rien de « la facture est débloquée ». La seconde
    approuvait tout avec un seul rôle, et recevait un refus : les paliers
    de `ensure_default_approval_thresholds` nomment des rôles DIFFÉRENTS
    (`comptable` puis `resp_commercial`), c'est-à-dire deux personnes. Le
    test suit donc la politique réelle, au lieu de la simplifier."""
    tenant, facture, emetteur = _societe_avec_facture_au_dessus_du_seuil()
    with use_tenant(tenant.id), pytest.raises(ApprovalRequiredError):
        validate_invoice(facture, emetteur)

    clients: dict[str, Client] = {}

    def _approbateur(role: str) -> Client:
        if role not in clients:
            user = User.objects.create_user(
                email=f"db-{role}@example.com", password="Str0ngPassw0rd!23"
            )
            grant_role(user, role)
            UserTenantMembership.objects.get_or_create(
                user=user, tenant=tenant, defaults={"is_default": True}
            )
            clients[role] = _connecte(user, tenant)
        return clients[role]

    for _tour in range(4):
        with use_tenant(tenant.id):
            demande = (
                ApprovalRequest.objects.filter(
                    object_id=str(facture.id), status=ApprovalRequest.STATUS_PENDING
                )
                .select_related("rule")
                .first()
            )
        if demande is None:
            break

        reponse = _approbateur(demande.rule.approver_role).post(
            "/approvals/",
            {"request_id": str(demande.id), "action": "approve", "comment": "Marché signé"},
        )
        assert reponse.status_code == 302, (
            f"Le rôle « {demande.rule.approver_role} » n'a pas pu décider de la demande "
            f"« {demande.rule.name} » qui lui revient."
        )
        demande.refresh_from_db()
        assert demande.status == ApprovalRequest.STATUS_APPROVED

        with use_tenant(tenant.id):
            try:
                validate_invoice(facture, emetteur)
            except ApprovalRequiredError:
                continue  # un palier de plus attend son approbateur
        break
    else:  # pragma: no cover - filet : un cycle d'approbation ne boucle pas
        raise AssertionError("Les approbations ne convergent pas vers une validation.")

    facture.refresh_from_db()
    assert facture.invoice_state == AccMove.INVOICE_STATE_VALIDATED, (
        f"La facture n'est toujours pas validée après approbation ({facture.invoice_state}) : "
        "l'écran enregistre la décision sans rien débloquer."
    )


def test_someone_who_is_not_an_approver_cannot_decide_and_is_told_so() -> None:
    tenant, facture, emetteur = _societe_avec_facture_au_dessus_du_seuil()
    with use_tenant(tenant.id), pytest.raises(ApprovalRequiredError):
        validate_invoice(facture, emetteur)

    with use_tenant(tenant.id):
        demande = ApprovalRequest.objects.filter(object_id=str(facture.id)).first()
    assert demande is not None

    intrus = User.objects.create_user(email="db-intrus@example.com", password="Str0ngPassw0rd!23")
    grant_role(intrus, "magasinier")
    UserTenantMembership.objects.get_or_create(
        user=intrus, tenant=tenant, defaults={"is_default": True}
    )
    reponse = _connecte(intrus, tenant).post(
        "/approvals/", {"request_id": str(demande.id), "action": "approve"}
    )
    assert reponse.status_code == 200, "Un refus doit rendre la page avec son message."
    assert "approbateur" in reponse.content.decode(), (
        "L'écran ne dit pas pourquoi la décision est refusée."
    )
    demande.refresh_from_db()
    assert demande.status == ApprovalRequest.STATUS_PENDING, (
        "Un utilisateur non approbateur a décidé d'une demande."
    )


def test_with_nothing_to_decide_the_screen_says_what_to_expect() -> None:
    tenant = Tenant.objects.create(code="DB4", name="Societe vide")
    user = User.objects.create_user(email="db-vide@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "magasinier")
    UserTenantMembership.objects.get_or_create(
        user=user, tenant=tenant, defaults={"is_default": True}
    )
    contenu = _connecte(user, tenant).get("/approvals/").content.decode()
    assert "Aucune validation en attente" in contenu, (
        "L'écran vide ne dit pas ce qu'on doit y attendre."
    )


def test_the_invoice_itself_says_it_is_waiting_for_a_validation() -> None:
    """La question se pose sur la pièce ; la réponse doit y être.

    Sans ce rappel, l'exploitant lit « en attente d'approbation » une seule
    fois — au moment du clic — et plus jamais ensuite : il revient sur sa
    facture le lendemain et ne comprend pas pourquoi elle refuse de se
    valider."""
    tenant, facture, emetteur = _societe_avec_facture_au_dessus_du_seuil()
    with use_tenant(tenant.id), pytest.raises(ApprovalRequiredError):
        validate_invoice(facture, emetteur)

    contenu = _connecte(emetteur, tenant).get(f"/accounting/{facture.id}/").content.decode()
    assert "En attente de validation" in contenu, (
        "La fiche de la facture ne dit pas qu'une validation est attendue."
    )
    assert "comptable" in contenu, "La fiche ne nomme pas le rôle qui doit décider."
