"""La classe d'erreur qui rendait 500 — mesurée, puis corrigée.

**Le défaut, chiffré.** La campagne de contrat OpenAPI
(`tests/contract/test_openapi_schemathesis.py`, marquée `slow`) mesure
**264 des 590 opérations** rendant un 500 sur entrée malformée. Sa
docstring annonçait « 165 sur 309 » : le chiffre datait d'avant l'ajout de
plusieurs modules, et la surface a grossi en emportant le défaut avec elle.

**La cause tient en une phrase.** Un identifiant UUID malformé reçu dans un
paramètre déclaré `str` traverse la validation de schéma de django-ninja
sans erreur, puis fait lever `Model.objects.get(id=...)` d'une
`django.core.exceptions.ValidationError` que **personne ne rattrapait**.
Elle tombait donc dans le gestionnaire générique, qui rend 500.

Le remède annoncé — retyper 460 paramètres `_id: str` en `UUID`, module par
module — traite les symptômes un par un. Le gestionnaire d'exception traite
la classe entière, en quinze lignes. Le retypage garde son intérêt (rejeter
en amont, et documenter le type dans l'OpenAPI publié), mais il cesse d'être
le préalable bloquant du bloc B.

**Et le défaut débordait largement des entrées malformées.** Toute la couche
service de ce dépôt lève `ValidationError` pour refuser une opération
métier. Chacun de ces refus — volontaire, documenté, testé — rendait un 500
dès lors qu'il traversait un endpoint : un refus légitime présenté à
l'utilisateur comme une panne du produit.
"""

from __future__ import annotations

import uuid

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.auth import issue_tokens

pytestmark = pytest.mark.django_db


@pytest.fixture
def client_authentifie():
    tenant = Tenant.objects.create(code="ERR-CONTRAT", name="Contrat SARL")
    utilisateur = User.objects.create_user(
        email="contrat@example.com", password="Str0ngPassw0rd!23"
    )
    acces, _rafraichissement = issue_tokens(utilisateur)
    entetes = {
        "HTTP_AUTHORIZATION": f"Bearer {acces}",
        "HTTP_X_TENANT_ID": str(tenant.id),
    }
    return Client(), entetes, tenant


def test_a_malformed_identifier_is_an_invalid_entry_not_a_crash(client_authentifie) -> None:
    """Le cas exact que la campagne de contrat génère : `"0"` là où un UUID
    est attendu. C'est une entrée invalide — 422 — jamais une panne du
    serveur."""
    client, entetes, _tenant = client_authentifie
    reponse = client.post(
        "/api/v1/approvals/0/decide",
        {"approved": False, "comment": ""},
        content_type="application/json",
        **entetes,
    )
    assert reponse.status_code != 500, reponse.content
    assert reponse.status_code == 422
    assert reponse["Content-Type"] == "application/problem+json"


def test_a_valid_but_absent_identifier_is_a_404(client_authentifie) -> None:
    """Un identifiant bien formé mais introuvable — le cas le plus fréquent
    sur une instance multi-sociétés, où `TenantManager` rend invisibles les
    lignes d'une autre société. Rendre 500 transformerait une isolation qui
    fonctionne en incident de production."""
    client, entetes, _tenant = client_authentifie
    reponse = client.post(
        f"/api/v1/approvals/{uuid.uuid4()}/decide",
        {"approved": False, "comment": ""},
        content_type="application/json",
        **entetes,
    )
    assert reponse.status_code == 404, reponse.content


def test_the_404_never_says_whether_the_object_exists(client_authentifie) -> None:
    """Distinguer « cet objet n'existe pas » de « cet objet ne vous est pas
    accessible » revient à confirmer son existence à qui n'y a pas droit.
    Même posture que le rejet de webhook de §8.2, « sans révéler
    pourquoi »."""
    client, entetes, _tenant = client_authentifie
    identifiant = uuid.uuid4()
    reponse = client.post(
        f"/api/v1/approvals/{identifiant}/decide",
        {"approved": False, "comment": ""},
        content_type="application/json",
        **entetes,
    )
    assert str(identifiant) not in reponse.content.decode()

    # Et le gestionnaire d'`ObjectDoesNotExist` lui-même, qui couvre les
    # endpoints faisant un `.objects.get()` direct plutôt qu'un
    # `get_object_or_404`. Celui-ci passe par le second (django-ninja rend
    # alors son propre « Not Found ») : vérifier l'endpoint seul laisserait
    # le gestionnaire neuf sans aucun test.
    from config.api import api
    from django.core.exceptions import ObjectDoesNotExist

    gestionnaire = api._exception_handlers[ObjectDoesNotExist]
    fausse_requete = type("R", (), {"path": "/api/v1/x"})()
    corps = gestionnaire(
        fausse_requete, ObjectDoesNotExist(f"Approval {identifiant} matching query does not exist")
    ).content.decode()
    assert str(identifiant) not in corps, (
        "Le détail recopie le message de l'exception : il révèle ce qui a été "
        "cherché, donc l'existence de l'objet à qui n'y a pas droit."
    )
    assert "existe pas ou n'est pas accessible" in corps


def test_a_service_refusal_reaches_the_user_with_its_reason(client_authentifie) -> None:
    """**La moitié qui compte le plus.** Le gestionnaire ne sert pas qu'aux
    entrées malformées : toute la couche service lève `ValidationError` pour
    refuser une opération métier, et chacun de ces refus rendait un 500.

    Le message est répercuté, contrairement au 500 générique : c'est toute
    la différence entre « une erreur inattendue est survenue » et une phrase
    sur laquelle l'utilisateur peut agir."""
    # Vérifié sur le gestionnaire lui-même plutôt qu'à travers un endpoint :
    # le message doit traverser, quel que soit l'endpoint qui le produit.
    from config.api import api
    from django.core.exceptions import ValidationError

    from apps.core.errors import ProblemDetailResponse

    gestionnaire = api._exception_handlers[ValidationError]
    fausse_requete = type("R", (), {"path": "/api/v1/x"})()
    reponse = gestionnaire(
        fausse_requete, ValidationError("le connecteur ne déclare pas l'opération OP3")
    )
    assert isinstance(reponse, ProblemDetailResponse)
    assert reponse.status_code == 422
    assert b"OP3" in reponse.content


def test_a_well_formed_call_still_works(client_authentifie) -> None:
    """Le témoin. Un gestionnaire qui rendrait 422 à tout le monde
    satisferait les tests ci-dessus et casserait le produit."""
    client, entetes, _tenant = client_authentifie
    reponse = client.get("/api/v1/approvals/pending", **entetes)
    assert reponse.status_code == 200
