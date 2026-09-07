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

**Corrigé en deux couches, et l'ordre a compté.** La couche 1 est le filtre
de service : elle a arrêté la fuite le jour même, sans migration ni
changement de signature. La couche 2 fait hériter les deux modèles de
`BaseModel` (migration `0039`) : la demande porte enfin sa propre société,
`TenantManager` filtre, et PostgreSQL refuse. La couche 1 seule protégeait
les lecteurs qu'elle traverse ; la couche 2 protège aussi les trente autres
sites d'appel mesurés dans le dépôt, dont un — `presence/services/
absences.py` — cherchait lui aussi une demande sans aucun filtre de
société.

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
    # Depuis la couche 2, les deux tables sont sous Row-Level Security :
    # une insertion hors contexte est refusée par PostgreSQL lui-même
    # (`new row violates row-level security policy`). La création se fait
    # donc dans la société propriétaire, comme en production.
    with use_tenant(b.id):
        regle_b = ApprovalRule.objects.create(
            tenant=b, content_type=ct, name="Validation B", approver_role="controleur_gestion"
        )
        demande_b = ApprovalRequest.objects.create(
            tenant=b,
            rule=regle_b,
            content_type=ct,
            object_id=str(b.id),
            requested_by=demandeur_b,
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

    with use_tenant(_societe_b.id):
        demande_b.refresh_from_db()
    assert demande_b.status == ApprovalRequest.STATUS_PENDING


def test_an_approver_still_sees_and_decides_his_own_company_s_requests(deux_societes) -> None:
    """La falsification qui compte : sans elle, « on ne voit plus rien »
    et « on a réparé l'isolation » seraient indiscernables. Un filtre qui
    cache tout passerait les deux tests précédents."""
    societe_a, _societe_b, comptable_a, _demande_b = deux_societes
    ct = ContentType.objects.get_for_model(Tenant)

    demandeur_a = UserFactory(email="demandeur.a@example.com")
    with use_tenant(societe_a.id):
        regle_a = ApprovalRule.objects.create(
            tenant=societe_a,
            content_type=ct,
            name="Validation A",
            approver_role="controleur_gestion",
        )
        demande_a = ApprovalRequest.objects.create(
            tenant=societe_a,
            rule=regle_a,
            content_type=ct,
            object_id=str(societe_a.id),
            requested_by=demandeur_a,
        )

    with use_tenant(societe_a.id):
        visibles = list(approvals.pending_for_user(comptable_a))
        assert [d.id for d in visibles] == [demande_a.id]
        assert approvals.is_eligible_approver(demande_a, comptable_a)
        approvals.decide(demande_a, comptable_a, approved=True)

    with use_tenant(societe_a.id):
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
    with use_tenant(_societe_b.id):
        demande_b.refresh_from_db()
    assert demande_b.status == ApprovalRequest.STATUS_PENDING


def test_outside_any_company_context_nothing_is_returned(deux_societes) -> None:
    """Deny-by-default, comme `TenantManager`.

    Une commande de gestion ou une tâche de fond qui appellerait cette
    fonction sans activer de société ne doit pas recevoir les demandes de
    TOUTES les sociétés. C'est le pire des cas possibles : le code
    appelant croirait légitimement travailler sur une seule.

    **Ce qui tient ce comportement, dit exactement — et cela a changé.**
    À la couche 1, la falsification avait montré que retirer le garde-fou
    explicite ne changeait RIEN : sans contexte,
    `filter(rule__tenant_id=None)` ne remonte aucune ligne, puisque
    `ApprovalRule.tenant` est non nul. Le refus venait du filtre, pas du
    `if`.

    Depuis la couche 2, TROIS mécanismes le tiennent : ce `if`, le filtre,
    et `TenantManager` qui rend `none()` hors contexte. Aucune mutation
    isolée ne fera donc rougir ce test — c'est le prix de la redondance, et
    il est écrit ici plutôt que laissé à découvrir."""
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


# ---------------------------------------------------------------------------
# Couche 2 — le filet sous le filtre
# ---------------------------------------------------------------------------
#
# Les tests ci-dessus vérifient le SERVICE. Ceux qui suivent vérifient que la
# base elle-même refuse, indépendamment de tout code applicatif : c'est la
# différence entre « le seul lecteur écrit filtre correctement » et « aucun
# lecteur ne PEUT lire ».


def test_the_manager_denies_by_default_outside_any_company(deux_societes) -> None:
    """`TenantManager`, appliqué aux deux modèles depuis la migration 0039.

    Un futur lecteur qui oublierait son filtre — c'est-à-dire exactement ce
    qui s'était produit — obtient désormais un ensemble vide plutôt que
    toutes les sociétés."""
    assert list(ApprovalRule.objects.all()) == []
    assert list(ApprovalRequest.objects.all()) == []


def test_a_company_s_manager_never_returns_another_s_rows(deux_societes) -> None:
    societe_a, societe_b, _comptable_a, demande_b = deux_societes

    with use_tenant(societe_a.id):
        assert list(ApprovalRequest.objects.all()) == []
        assert list(ApprovalRule.objects.all()) == []
    with use_tenant(societe_b.id):
        assert [d.id for d in ApprovalRequest.objects.all()] == [demande_b.id]


def test_postgresql_itself_refuses_the_other_company_s_rows(deux_societes) -> None:
    """**Le filet, testé SANS le manager.**

    `all_objects` est un `models.Manager` ordinaire : il ne filtre rien. Ce
    qui reste debout est donc la policy PostgreSQL seule. Sans elle, ce test
    verrait la demande de B depuis le contexte de A — c'est-à-dire que le
    dépôt n'aurait toujours qu'UNE couche de protection, celle qu'un
    développeur peut oublier.

    **Falsifié, et le premier essai avait donné un FAUX NÉGATIF.** Retirer la
    policy avec `ALTER TABLE core_approval_request DISABLE ROW LEVEL
    SECURITY` en `psql` avant de lancer pytest ne faisait PAS rougir ce
    test — j'ai d'abord cru que le test ne valait rien. La cause est
    ailleurs : `--reuse-db` conserve les données mais **rejoue `migrate`**,
    donc `post_migrate` rappelle `apply_rls` et remet la policy avant le
    premier test. La falsification qui mord se fait DANS la transaction du
    test, et avant toute écriture (PostgreSQL refuse un `ALTER TABLE` sur
    une table qui porte des déclencheurs de contrainte différés en
    attente) : le contexte de A voit alors bien la demande de B. La policy
    fait donc le travail.

    C'est noté ici pour que le prochain ne refasse pas le même essai
    invalide et n'en tire pas la même conclusion fausse."""
    societe_a, societe_b, _comptable_a, demande_b = deux_societes

    with use_tenant(societe_a.id):
        vues = list(ApprovalRequest.all_objects.filter(id=demande_b.id))
    assert vues == [], (
        "PostgreSQL laisse lire la demande d'une autre société : la Row-Level "
        "Security n'est pas appliquée sur `core_approval_request`."
    )

    with use_tenant(societe_b.id):
        assert [d.id for d in ApprovalRequest.all_objects.filter(id=demande_b.id)] == [
            demande_b.id
        ], "La société propriétaire ne voit plus sa propre demande : la policy est trop stricte."


def test_postgresql_refuses_to_write_a_row_into_another_company(deux_societes) -> None:
    """L'écriture, et pas seulement la lecture. Une policy `USING` sans
    `WITH CHECK` sert aussi de contrôle à l'INSERT : écrire une règle de la
    société B depuis le contexte de A est refusé par la base."""
    from django.db import ProgrammingError, transaction

    societe_a, societe_b, _comptable_a, _demande_b = deux_societes
    ct = ContentType.objects.get_for_model(Tenant)

    with use_tenant(societe_a.id), pytest.raises(ProgrammingError), transaction.atomic():
        ApprovalRule.objects.create(
            tenant=societe_b, content_type=ct, name="Règle intruse", approver_role="x"
        )


def test_a_request_always_carries_the_company_of_its_rule(deux_societes) -> None:
    """La colonne ajoutée par la couche 2 doit rester COHÉRENTE avec la
    règle, sans quoi elle créerait une seconde vérité.

    `request_approval` prend la société de LA RÈGLE, jamais du contexte
    actif : une divergence rendrait la demande invisible de sa propre
    lecture (qui vérifie les deux), et le service la rend impossible à la
    création plutôt qu'à la lecture."""
    societe_a, _societe_b, _comptable_a, _demande_b = deux_societes
    ct = ContentType.objects.get_for_model(Tenant)
    demandeur = UserFactory(email="demandeur.coherence@example.com")

    with use_tenant(societe_a.id):
        regle = ApprovalRule.objects.create(
            tenant=societe_a, content_type=ct, name="Cohérence", approver_role="x"
        )
        demande = approvals.request_approval(societe_a, regle, demandeur)
        assert demande.tenant_id == regle.tenant_id


def test_the_policy_is_really_installed_on_both_tables(deux_societes) -> None:
    """Le MÉCANISME, pas seulement son effet — et cette vérification
    n'existait nulle part dans le dépôt.

    `tests/architecture/test_rls_coverage.py` est purement statique : il
    regarde de quoi les modèles héritent, jamais ce que PostgreSQL porte
    réellement. Or `apply_rls` s'exécute sur `post_migrate` et ne dit jamais
    ce qu'il n'a pas couvert — sa propre docstring le reconnaît : « son
    silence ressemble exactement à une couverture complète ».

    `FORCE` compte autant que `ENABLE` : sans lui, le PROPRIÉTAIRE de la
    table contourne la policy, et le rôle applicatif de ce dépôt
    (`widehalo_app`) est justement le propriétaire. Une table simplement
    `ENABLE` serait donc protégée contre tout le monde sauf contre le seul
    rôle qui s'y connecte."""
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname IN ('core_approval_rule', 'core_approval_request') "
            "ORDER BY relname"
        )
        etat = {ligne[0]: (ligne[1], ligne[2]) for ligne in cursor.fetchall()}
        cursor.execute(
            "SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation_policy' "
            "AND tablename IN ('core_approval_rule', 'core_approval_request')"
        )
        avec_policy = {ligne[0] for ligne in cursor.fetchall()}

    for table in ("core_approval_rule", "core_approval_request"):
        assert etat.get(table) == (True, True), (
            f"{table} : Row-Level Security attendue en ENABLE + FORCE, trouvée "
            f"{etat.get(table)}. Sans FORCE, le propriétaire de la table — c'est-à-dire "
            "le rôle applicatif lui-même — contourne la policy."
        )
        assert table in avec_policy, (
            f"{table} n'a pas de policy `tenant_isolation_policy` : la table est sous "
            "RLS sans règle, donc VIDE pour tout le monde, ou pas protégée du tout "
            "selon la version. `apply_rls` ne l'a pas couverte."
        )
