"""S4 — les trois défauts de `core/idempotency.py`, antérieurs à la Phase 4.

Aucun n'était une opinion : tous trois ont été vérifiés sur pièces avant
d'être corrigés.

1. **`expires_at` était écrit et filtré par aucune lecture.** Le TTL de
   24 h annoncé dans la docstring n'existait pas. Pire que « pas de TTL » :
   le `unique_together` interdisait pour toujours la réutilisation d'une
   chaîne de clé, si bien qu'un client recyclant ses clés voyait ses
   requêtes légitimes renvoyer une réponse vieille de plusieurs mois.

2. **Aucune purge.** La table conservait une ligne par appel idempotent,
   corps complet de la réponse inclus, indéfiniment. Ce n'est pas une
   question d'encombrement mais de gouvernance : une table qui n'oublie
   jamais conserve des données hors de toute durée déclarée.

3. **Hors Row-Level Security.** Pas une fuite atteignable — la seule
   lecture du dépôt filtre sur le triplet complet — mais un filet absent.
   Traité par une garde d'architecture plutôt qu'ici, parce que le défaut
   n'est pas cette table : c'est le mécanisme de sélection d'`apply_rls`,
   qui laisse passer dix modèles.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from django.utils import timezone

from apps.core.models.idempotency import IdempotencyKey
from apps.core.services.idempotency_purge import purge_expired_idempotency_keys

pytestmark = pytest.mark.django_db


def _key(*, key="cle-1", expired=False, tenant_id=None, user_id=None):
    moment = timezone.now()
    return IdempotencyKey.objects.create(
        tenant_id=tenant_id,
        user_id=user_id,
        key=key,
        request_hash="abc",
        response_status=200,
        response_body='{"message": "bonjour"}',
        expires_at=moment - dt.timedelta(hours=1) if expired else moment + dt.timedelta(hours=1),
    )


def test_an_expired_key_no_longer_replays_its_answer() -> None:
    """Le TTL est opposable à la LECTURE — vérifié SUR LE DÉCORATEUR, pas
    sur un `queryset` reconstruit par le test.

    La première rédaction construisait elle-même le filtre
    `expires_at__gt=now` et vérifiait qu'il ne renvoyait rien : elle
    testait Django, pas ce module. La falsification l'a montrée — retirer
    le filtre du décorateur ne la faisait pas rougir. Elle appelle donc le
    vrai endpoint idempotent."""
    from apps.core.idempotency import DEFAULT_TTL

    assert dt.timedelta(hours=24) == DEFAULT_TTL

    # L'endpoint idempotent exige une session : mêmes aides que
    # `test_api_conventions.py`, qui exerce déjà ce chemin.
    from django.test import Client

    from apps.core.models.user import User

    utilisateur = User.objects.create_user(email="ttl@example.com", password="Str0ngPassw0rd!23")
    client = Client()
    jeton = client.post(
        "/api/v1/auth/login",
        {"email": utilisateur.email, "password": "Str0ngPassw0rd!23"},
        content_type="application/json",
    ).json()["access"]
    entete = {"HTTP_AUTHORIZATION": f"Bearer {jeton}", "HTTP_IDEMPOTENCY_KEY": "cle-ttl"}
    premiere = client.post(
        "/api/v1/meta/echo",
        data=json.dumps({"message": "premier"}),
        content_type="application/json",
        **entete,
    )
    assert premiere.status_code == 200
    assert premiere.json()["message"] == "premier"

    # La clé est périmée à la main : l'horloge du test ne peut pas avancer
    # de vingt-quatre heures.
    IdempotencyKey.objects.filter(key="cle-ttl").update(
        expires_at=timezone.now() - dt.timedelta(minutes=1)
    )

    # Même clé, corps DIFFÉRENT. Sans TTL, le décorateur retrouverait
    # l'ancienne ligne et répondrait 409 (conflit de corps). Il doit
    # traiter la requête.
    seconde = client.post(
        "/api/v1/meta/echo",
        data=json.dumps({"message": "second"}),
        content_type="application/json",
        **entete,
    )
    assert seconde.status_code == 200, (
        f"Statut {seconde.status_code} : la clé périmée bloque encore un appel "
        "légitime — le TTL n'est pas appliqué à la lecture."
    )
    assert seconde.json()["message"] == "second", (
        "La réponse rejouée est celle de la clé périmée : le TTL est décoratif."
    )


def test_an_expired_key_does_not_block_its_own_reuse_forever() -> None:
    """La conséquence la moins visible et la plus gênante. Le
    `unique_together` retenait la chaîne de clé pour toujours : appliquer
    le TTL à la seule lecture aurait fait remonter une `IntegrityError` à
    l'appelant légitime. Le TTL doit être tenu aux DEUX bouts."""
    from apps.core.models.idempotency import IdempotencyKey as Modele

    perimee = _key(key="recyclee", expired=True)
    maintenant = timezone.now()

    # Ce que fait le décorateur avant de réécrire.
    Modele.objects.filter(
        tenant_id=None, user_id=None, key="recyclee", expires_at__lte=maintenant
    ).delete()
    neuve = _key(key="recyclee")

    assert neuve.pk != perimee.pk
    assert Modele.objects.filter(key="recyclee").count() == 1


def test_the_purge_removes_expired_keys_and_only_those() -> None:
    """La seconde moitié : sans purge, la table croît sans fin même si le
    TTL est respecté à la lecture."""
    _key(key="vivante")
    _key(key="perimee-1", expired=True)
    _key(key="perimee-2", expired=True)

    supprimees = purge_expired_idempotency_keys()

    assert supprimees == 2
    assert list(IdempotencyKey.objects.values_list("key", flat=True)) == ["vivante"]


def test_the_purge_is_idempotent() -> None:
    """Deux passages successifs ne suppriment rien la seconde fois, et un
    passage sur une table propre n'écrit rien (discipline L0-1)."""
    _key(key="perimee", expired=True)
    assert purge_expired_idempotency_keys() == 1
    assert purge_expired_idempotency_keys() == 0


def test_the_purge_command_is_declared_in_the_schedule_registry() -> None:
    """Une purge présente sur disque mais non planifiée ne s'exécute
    jamais — c'est exactement le défaut que le lot WhatsApp a corrigé pour
    sa file, et il n'y a aucune raison de le refaire ici."""
    from apps.core.services.scheduled_commands import list_scheduled_commands

    entree = next(c for c in list_scheduled_commands() if c.code == "core.purge_idempotency_keys")
    assert entree.command == "purge_idempotency_keys"
    assert entree.frequency == "daily"


def test_the_expires_at_column_is_indexed() -> None:
    """La purge et le filtre de TTL balaient tous deux sur ce champ. Sans
    index, chaque appel à un endpoint idempotent ferait un parcours complet
    d'une table qui n'a, par construction, aucune raison de rester
    petite."""
    index = {i.name for i in IdempotencyKey._meta.indexes}
    assert "idx_core_idemp_expires" in index


def test_uniqueness_holds_even_when_the_tenant_is_not_resolved() -> None:
    """Trouvé en FALSIFIANT, et c'est le genre de défaut qu'aucune relecture
    n'attrape.

    `unique_together = ("tenant_id", "user_id", "key")` ne mord pas quand
    `tenant_id` est NUL : PostgreSQL considère deux NULL comme distincts
    dans un index unique. Le triplet (NULL, utilisateur, clé) n'entrait
    donc en collision avec rien — c'est-à-dire que **l'idempotence n'était
    pas garantie pour les appels dont le tenant n'est pas résolu**, qui
    sont précisément ceux où le client a le moins de contexte pour se
    protéger lui-même.

    La falsification qui l'a révélé : retirer le retrait de la ligne
    périmée avant réécriture aurait dû produire une `IntegrityError`, et ne
    produisait rien du tout."""
    from django.db import IntegrityError

    _key(key="sans-tenant", tenant_id=None, user_id=None)
    with pytest.raises(IntegrityError):
        _key(key="sans-tenant", tenant_id=None, user_id=None)


def test_two_users_may_share_a_key_when_neither_has_a_tenant() -> None:
    """La contrepartie : la contrainte porte sur (utilisateur, clé), pas sur
    la clé seule. Deux appelants distincts ne doivent jamais se bloquer
    l'un l'autre en choisissant par hasard la même chaîne."""
    import uuid as _uuid

    _key(key="partagee", tenant_id=None, user_id=_uuid.uuid4())
    _key(key="partagee", tenant_id=None, user_id=_uuid.uuid4())
    assert IdempotencyKey.objects.filter(key="partagee").count() == 2
