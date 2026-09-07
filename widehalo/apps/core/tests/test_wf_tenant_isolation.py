"""La fuite inter-sociétés du sous-système de validation.

**Trouvée en cherchant à répondre à une autre question**, et vérifiée
empiriquement avant d'être décrite : un utilisateur portant un rôle
d'approbateur voyait — et pouvait DÉCIDER — les demandes de validation de
n'importe quelle société dont une règle porte le même rôle.

Sur une instance multi-sociétés, le comptable d'une société pouvait donc
approuver les factures, périodes de paie, commandes d'achat et absences
d'une autre. Les deux moitiés sont exposées en HTTP :
`GET /api/v1/approvals/pending` et `POST /api/v1/approvals/{id}/decide`.

**Pourquoi rien ne l'a rattrapée.** `ApprovalRequest` n'a aucun champ
tenant : sa société se déduit par `rule.tenant`. Il n'y avait donc rien
d'évident à filtrer, et le filtre a été oublié — `pending_for_user` ne
filtrait sur aucun tenant, `is_eligible_approver` ne comparait que des
rôles, et les groupes Django sont globaux dans ce dépôt. Ni l'un ni
l'autre modèle n'étant sous `TenantManager` ni sous Row-Level Security,
aucun filet ne rattrapait l'oubli.

C'est la même faille que RG-CRM-5, fermée plus tôt dans ce chantier —
quatre endpoints CRM sans périmètre — mais un cran plus grave : ici on ne
consulte pas, on décide.
"""

from __future__ import annotations

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied

from apps.core.models.tenant import Tenant
from apps.core.models.workflow import ApprovalRequest, ApprovalRule
from apps.core.services import approvals
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import grant_role, use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def deux_societes():
    """Deux sociétés, chacune avec une règle de validation portant LE MÊME
    rôle d'approbateur — le cas nominal d'une instance multi-sociétés, où
    chaque société a son comptable."""
    a = Tenant.objects.create(code="ISO-A", name="Société A")
    b = Tenant.objects.create(code="ISO-B", name="Société B")
    ct = ContentType.objects.get_for_model(Tenant)

    demandeur_b = UserFactory(email="demandeur.b@example.com")
    regle_b = ApprovalRule.objects.create(
        tenant=b, content_type=ct, name="Validation B", approver_role="controleur_gestion"
    )
    demande_b = ApprovalRequest.objects.create(
        rule=regle_b, content_type=ct, object_id=str(b.id), requested_by=demandeur_b
    )

    comptable_a = UserFactory(email="comptable.a@example.com")
    grant_role(comptable_a, "controleur_gestion")
    return a, b, comptable_a, demande_b


def test_an_approver_never_sees_another_company_s_requests(deux_societes) -> None:
    """La première moitié de la fuite. Un rôle porté dans une société ne
    doit rien montrer d'une autre — les groupes Django étant globaux, le
    seul rôle ne peut pas suffire à décider ce qu'on voit."""
    societe_a, _societe_b, comptable_a, demande_b = deux_societes

    with use_tenant(societe_a.id):
        visibles = list(approvals.pending_for_user(comptable_a))

    assert demande_b.id not in [d.id for d in visibles], (
        "Un approbateur voit les demandes de validation d'une AUTRE société : sur une "
        "instance multi-sociétés, l'écran des validations en attente montre les "
        "documents des concurrents."
    )
    assert visibles == []


def test_an_approver_can_never_decide_another_company_s_request(deux_societes) -> None:
    """La seconde moitié, et la plus grave : voir est une indiscrétion,
    décider est un acte. Approuver la facture d'une autre société, c'est
    engager cette société."""
    societe_a, _societe_b, comptable_a, demande_b = deux_societes

    with use_tenant(societe_a.id):
        eligible = approvals.is_eligible_approver(demande_b, comptable_a)
        assert eligible is False, (
            "Un approbateur d'une société est déclaré éligible pour décider de la "
            "demande d'une AUTRE : il peut approuver ses factures, ses périodes de "
            "paie et ses commandes."
        )

        with pytest.raises(PermissionDenied):
            approvals.decide(demande_b, comptable_a, approved=True)

    demande_b.refresh_from_db()
    assert demande_b.status == ApprovalRequest.STATUS_PENDING


def test_an_approver_still_sees_and_decides_his_own_company_s_requests(deux_societes) -> None:
    """La falsification qui compte : sans elle, « on ne voit plus rien »
    et « on a réparé l'isolation » seraient indiscernables. Un filtre qui
    cache tout passerait les deux tests précédents."""
    societe_a, _societe_b, comptable_a, _demande_b = deux_societes
    ct = ContentType.objects.get_for_model(Tenant)

    demandeur_a = UserFactory(email="demandeur.a@example.com")
    regle_a = ApprovalRule.objects.create(
        tenant=societe_a, content_type=ct, name="Validation A", approver_role="controleur_gestion"
    )
    demande_a = ApprovalRequest.objects.create(
        rule=regle_a, content_type=ct, object_id=str(societe_a.id), requested_by=demandeur_a
    )

    with use_tenant(societe_a.id):
        visibles = list(approvals.pending_for_user(comptable_a))
        assert [d.id for d in visibles] == [demande_a.id]
        assert approvals.is_eligible_approver(demande_a, comptable_a)
        approvals.decide(demande_a, comptable_a, approved=True)

    demande_a.refresh_from_db()
    assert demande_a.status == ApprovalRequest.STATUS_APPROVED


def test_the_endpoint_refuses_a_request_from_another_company(deux_societes) -> None:
    """La fuite est atteignable en HTTP, et c'est là qu'elle doit être
    fermée pour de bon : un service correct derrière un endpoint qui ne
    l'appelle pas correctement ne protège rien."""
    from django.test import Client

    from apps.core.models.user import UserTenantMembership

    societe_a, _societe_b, comptable_a, demande_b = deux_societes
    comptable_a.set_password("Str0ngPassw0rd!23")
    comptable_a.save(update_fields=["password"])
    # Membre EN RÈGLE de la société A : sans cela le refus viendrait de
    # l'authentification, et ne prouverait rien du contrôle de société.
    UserTenantMembership.objects.create(user=comptable_a, tenant=societe_a)

    client = Client()
    jeton = client.post(
        "/api/v1/auth/login",
        {"email": comptable_a.email, "password": "Str0ngPassw0rd!23"},
        content_type="application/json",
    ).json()["access"]
    entetes = {
        "HTTP_AUTHORIZATION": f"Bearer {jeton}",
        "HTTP_X_TENANT_ID": str(societe_a.id),
    }

    reponse = client.post(
        f"/api/v1/approvals/{demande_b.id}/decide",
        data='{"approved": true}',
        content_type="application/json",
        **entetes,
    )
    assert reponse.status_code in (403, 404), (
        f"Statut {reponse.status_code} : l'endpoint de décision accepte une demande "
        "appartenant à une autre société."
    )
    demande_b.refresh_from_db()
    assert demande_b.status == ApprovalRequest.STATUS_PENDING


def test_outside_any_company_context_nothing_is_returned(deux_societes) -> None:
    """Deny-by-default, comme `TenantManager`.

    Une commande de gestion ou une tâche de fond qui appellerait cette
    fonction sans activer de société ne doit pas recevoir les demandes de
    TOUTES les sociétés. C'est le pire des cas possibles : le code
    appelant croirait légitimement travailler sur une seule.

    **Ce qui tient ce comportement, dit exactement.** La falsification a
    montré que retirer le garde-fou explicite ne change RIEN : sans
    contexte, `filter(rule__tenant_id=None)` ne remonte aucune ligne,
    puisque `ApprovalRule.tenant` est non nul. Le refus vient donc du
    filtre lui-même, pas du `if`. Le garde-fou rend la propriété LISIBLE
    plutôt qu'accidentelle — et ce test la fige, pour qu'un futur filtre
    plus permissif ne la perde pas en silence."""
    _societe_a, _societe_b, comptable_a, _demande_b = deux_societes

    # Hors de tout `use_tenant` : aucun contexte actif.
    visibles = list(approvals.pending_for_user(comptable_a))

    assert visibles == [], (
        f"{len(visibles)} demande(s) renvoyée(s) hors contexte de société : un appel "
        "depuis une commande ou une tâche de fond verrait les validations de toutes "
        "les sociétés de l'instance."
    )


def test_outside_any_company_context_nobody_is_eligible(deux_societes) -> None:
    """Le pendant pour la décision. Sans société active, on ne peut être
    l'approbateur de personne — pas même de sa propre société, qu'on n'a
    pas désignée."""
    _societe_a, _societe_b, comptable_a, demande_b = deux_societes

    assert approvals.is_eligible_approver(demande_b, comptable_a) is False
