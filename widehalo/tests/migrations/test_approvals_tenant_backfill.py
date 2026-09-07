"""La migration `core.0039` remplit une colonne — et rien ne l'exerçait.

**Le trou, avant ce fichier.** La suite tourne sur une base créée de zéro :
le `RunPython` de `0039` s'exécute alors sur ZÉRO ligne, et un remplissage
qui ne remplit rien passe tous les tests. Or c'est précisément le contraire
qui arrive en production — la table `core_approval_request` y contient des
demandes écrites depuis le premier lot, et si `tenant_id` n'était pas
renseigné, l'`AlterField` qui suit (`NOT NULL`) ferait échouer le
déploiement.

C'est le motif que ce dépôt corrige depuis le début, appliqué à une
migration : du code correct, correctement documenté, que rien n'invoque
dans les conditions où il compte.

`django-test-migrations` rejoue l'historique réel : on écrit des demandes
AVANT `0039`, dans la forme qu'avait alors la table (aucune colonne de
société), puis on applique la migration et on regarde.

Recrée tout le schéma : marqué `slow`, comme `test_mig1_expand_contract.py`.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.slow

_AVANT = ("core", "0038_holiday")
_APRES = ("core", "0039_approvals_under_row_level_security")


@pytest.mark.django_db
def test_preexisting_requests_inherit_the_company_of_their_rule(migrator) -> None:
    """Le cas réel : des demandes existent déjà, elles n'ont pas de société,
    et deux sociétés différentes coexistent — sinon le remplissage pourrait
    poser n'importe quelle valeur constante et passer."""
    etat = migrator.apply_initial_migration(_AVANT)

    tenant_model = etat.apps.get_model("core", "Tenant")
    user_model = etat.apps.get_model("core", "User")
    content_type_model = etat.apps.get_model("contenttypes", "ContentType")
    regle_model = etat.apps.get_model("core", "ApprovalRule")
    demande_model = etat.apps.get_model("core", "ApprovalRequest")

    a = tenant_model.objects.create(code="MIG39-A", name="Société A")
    b = tenant_model.objects.create(code="MIG39-B", name="Société B")
    ct = content_type_model.objects.get_or_create(app_label="core", model="tenant")[0]
    demandeur = user_model.objects.create(email="mig39@example.com", password="x")

    regle_a = regle_model.objects.create(tenant=a, content_type=ct, name="A", approver_role="r")
    regle_b = regle_model.objects.create(tenant=b, content_type=ct, name="B", approver_role="r")
    demande_a = demande_model.objects.create(
        rule=regle_a, content_type=ct, object_id=str(a.id), requested_by=demandeur
    )
    demande_b = demande_model.objects.create(
        rule=regle_b, content_type=ct, object_id=str(b.id), requested_by=demandeur
    )

    # Avant la migration, la colonne n'existe pas — pas même à renseigner.
    assert not hasattr(demande_a, "tenant_id")

    nouvel_etat = migrator.apply_tested_migration(_APRES)
    demande_apres = nouvel_etat.apps.get_model("core", "ApprovalRequest")

    assert str(demande_apres.objects.get(pk=demande_a.pk).tenant_id) == str(a.id), (
        "La demande préexistante n'a pas hérité de la société de sa règle : "
        "sur une base réelle, l'`AlterField` NOT NULL qui suit ferait échouer "
        "le déploiement."
    )
    assert str(demande_apres.objects.get(pk=demande_b.pk).tenant_id) == str(b.id), (
        "Les deux demandes portent la même société : le remplissage pose une "
        "valeur constante au lieu de lire la règle."
    )


@pytest.mark.django_db
def test_the_column_is_not_null_after_the_backfill(migrator) -> None:
    """La troisième opération de la migration. Sans elle, la colonne
    resterait nullable et une demande future pourrait n'appartenir à
    personne — ce qui, sous Row-Level Security, la rendrait invisible de
    tout le monde plutôt que de lever une erreur."""
    migrator.apply_initial_migration(_AVANT)
    nouvel_etat = migrator.apply_tested_migration(_APRES)

    demande_model = nouvel_etat.apps.get_model("core", "ApprovalRequest")
    champ = demande_model._meta.get_field("tenant")
    assert champ.null is False
    assert champ.remote_field.on_delete.__name__ == "PROTECT"


@pytest.mark.django_db
def test_the_rule_keeps_its_company_and_gains_protection(migrator) -> None:
    """`ApprovalRule` portait déjà `tenant`, en CASCADE. Le passage à PROTECT
    est une correction : supprimer une société ne doit pas emporter ses
    règles de validation en silence, sans passer par les chemins de purge."""
    etat = migrator.apply_initial_migration(_AVANT)
    tenant_model = etat.apps.get_model("core", "Tenant")
    content_type_model = etat.apps.get_model("contenttypes", "ContentType")
    regle_model = etat.apps.get_model("core", "ApprovalRule")

    societe = tenant_model.objects.create(code="MIG39-C", name="Société C")
    ct = content_type_model.objects.get_or_create(app_label="core", model="tenant")[0]
    regle = regle_model.objects.create(tenant=societe, content_type=ct, name="C", approver_role="r")

    nouvel_etat = migrator.apply_tested_migration(_APRES)
    regle_apres = nouvel_etat.apps.get_model("core", "ApprovalRule")

    relue = regle_apres.objects.get(pk=regle.pk)
    assert str(relue.tenant_id) == str(societe.id)
    assert regle_apres._meta.get_field("tenant").remote_field.on_delete.__name__ == "PROTECT"
    # Les champs d'audit apparaissent renseignes, jamais nuls, sur une ligne
    # preexistante : `created_at` recoit un defaut a la volee.
    assert relue.created_at is not None
