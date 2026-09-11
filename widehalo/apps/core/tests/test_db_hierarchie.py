"""D-B — la chaîne hiérarchique des rôles, et ce qu'elle alimente.

Le commanditaire demande que « le responsable, ou à défaut son supérieur »
soit une règle du produit, dans tous les modules. Le moteur d'approbation
portait déjà la forme (`approver_role` / `fallback_approver_role`) ; aucune
chaîne n'était déclarée, et aucune règle du dépôt ne renseignait son
secours.

La vérification se fait contre une source INDÉPENDANTE — la matrice RBAC —
et jamais contre le dictionnaire qu'elle surveille : un jeu fermé vérifié
contre lui-même ne dit rien (leçon F60)."""

from __future__ import annotations

import pytest

from apps.core.services.rbac_policy import ROLE_APP_PERMISSIONS
from apps.core.services.role_hierarchy import (
    ROLE_SOMMET,
    SUPERIEUR_DE,
    chaine_de,
    superieur_de,
)

pytestmark = pytest.mark.django_db


def test_every_role_of_the_matrix_has_a_place_in_the_chain() -> None:
    """Un rôle sans place remonterait à personne : sa demande resterait en
    attente indéfiniment si son titulaire ne décide pas."""
    roles = set(ROLE_APP_PERMISSIONS)
    assert roles, "La matrice RBAC est vide : le test ne mesure rien."

    sans_place = sorted(roles - set(SUPERIEUR_DE) - {ROLE_SOMMET})
    assert not sans_place, (
        f"Ces rôles de la matrice n'ont aucun supérieur déclaré : {sans_place}. "
        "Une demande qui leur revient ne pourrait jamais être escaladée."
    )


def test_the_chain_names_no_role_the_matrix_does_not_know() -> None:
    """L'inverse du précédent : un supérieur qui n'existe pas dans la
    matrice ne recevrait jamais rien, et l'escalade tomberait dans le
    vide."""
    inconnus = sorted(set(SUPERIEUR_DE.values()) - set(ROLE_APP_PERMISSIONS) - {ROLE_SOMMET})
    assert not inconnus, f"La chaîne nomme des rôles absents de la matrice : {inconnus}."


def test_the_chain_always_reaches_the_top_and_never_loops() -> None:
    for role in SUPERIEUR_DE:
        chaine = chaine_de(role)
        assert chaine, f"Le rôle « {role} » ne remonte à personne."
        assert len(chaine) == len(set(chaine)), f"La chaîne de « {role} » boucle : {chaine}."
        assert chaine[-1] == ROLE_SOMMET, (
            f"La chaîne de « {role} » s'arrête à « {chaine[-1]}» au lieu du sommet."
        )


def test_the_top_role_has_no_superior() -> None:
    assert superieur_de(ROLE_SOMMET) is None, "Le sommet de la chaîne a un supérieur."


def test_the_accounting_rules_carry_their_fallback_from_the_chain() -> None:
    """Ce que la chaîne SERT : sans secours renseigné, une demande non
    décidée par son titulaire n'est jamais reprise par personne."""
    from django.contrib.contenttypes.models import ContentType

    from apps.accounting.models import AccMove
    from apps.accounting.services.invoices import ensure_default_approval_thresholds
    from apps.core.models.tenant import Tenant
    from apps.core.models.workflow import ApprovalRule
    from apps.core.tests.utils import use_tenant

    tenant = Tenant.objects.create(code="DBH", name="Societe hierarchie")
    with use_tenant(tenant.id):
        ensure_default_approval_thresholds(tenant)
        regles = list(
            ApprovalRule.objects.filter(
                tenant=tenant, content_type=ContentType.objects.get_for_model(AccMove)
            )
        )

    assert regles, "Aucune règle de validation semée : le test ne mesure rien."
    for regle in regles:
        assert regle.fallback_approver_role == superieur_de(regle.approver_role), (
            f"La règle « {regle.name} » ne reprend pas la chaîne : secours "
            f"« {regle.fallback_approver_role} » pour un titulaire « {regle.approver_role} »."
        )
        assert regle.escalate_after is not None, (
            f"La règle « {regle.name} » n'a aucun délai d'escalade : son secours "
            "ne sera jamais atteint."
        )
