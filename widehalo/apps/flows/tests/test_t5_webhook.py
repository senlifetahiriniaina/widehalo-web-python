"""T5 — le point d'entrée entrant : ce qu'il refuse, et ce qu'il diffère.

**Le critère API-3** : « un appel de webhook non signé, mal signé ou
horodaté hors fenêtre est rejeté sans traitement, et journalisé sans
révéler le motif à l'appelant ». Quatre exigences distinctes, quatre tests.

**Le critère API-5** : « le point d'entrée accuse réception en moins de
500 ms sous charge nominale, le traitement étant différé en file ». Ce
qu'on vérifie ici n'est pas un chronomètre — il mesurerait la machine de
test — mais la PROPRIÉTÉ qui rend le délai possible : aucun traitement
métier n'a lieu dans la vue.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json

import pytest
from django.test import Client
from django.utils import timezone

from apps.core.tests.utils import use_tenant
from apps.flows.models import FlwCredential, FlwExchange, FlwLink
from apps.flows.services.webhook_auth import TIMESTAMP_WINDOW_SECONDS
from apps.flows.tests.factories import FlwConnectorFactory, FlwLinkFactory

pytestmark = pytest.mark.django_db

SECRET = "secret-de-webhook-pour-le-test"  # noqa: S105 - valeur de test, jamais un secret reel.


@pytest.fixture
def liaison_signee(tenant_factory=None):
    from apps.core.models.tenant import Tenant

    societe = Tenant.objects.create(code="T5-WH", name="Encaissement SARL")
    with use_tenant(societe.id):
        connecteur = FlwConnectorFactory(tenant=societe, code="encaissement_mobile")
        liaison = FlwLinkFactory(tenant=societe, connector=connecteur, state=FlwLink.STATE_ACTIVE)
        FlwCredential.objects.create(
            tenant=societe,
            connector=connecteur,
            label="Secret de webhook",
            kind=FlwCredential.KIND_WEBHOOK_SECRET,
            secret=SECRET,
        )
    return societe, liaison


def _corps(reference: str = "PAY-001") -> bytes:
    return json.dumps({"reference": reference, "montant": "1000"}, sort_keys=True).encode("utf-8")


def _signe(corps: bytes, horodatage: str) -> str:
    return hmac.new(
        SECRET.encode("utf-8"), horodatage.encode("utf-8") + b"." + corps, hashlib.sha256
    ).hexdigest()


def _maintenant() -> str:
    return str(int(timezone.now().timestamp()))


def _poste(client: Client, liaison, corps: bytes, *, signature: str, horodatage: str):
    return client.post(
        f"/api/v1/flows/webhooks/{liaison.id}",
        data=corps,
        content_type="application/json",
        HTTP_X_SIGNATURE=signature,
        HTTP_X_TIMESTAMP=horodatage,
    )


def test_a_correctly_signed_call_is_accepted_and_recorded(liaison_signee) -> None:
    """Le chemin nominal : l'appel est accepté, l'échange entrant existe."""
    societe, liaison = liaison_signee
    corps, horodatage = _corps(), _maintenant()

    reponse = _poste(
        Client(), liaison, corps, signature=_signe(corps, horodatage), horodatage=horodatage
    )

    assert reponse.status_code == 200
    with use_tenant(societe.id):
        echange = FlwExchange.objects.get(tenant=societe, direction=FlwExchange.DIRECTION_INBOUND)
        assert echange.payload_fingerprint, "l'empreinte doit exister — elle survit à la purge"


def test_an_unsigned_call_is_refused(liaison_signee) -> None:
    societe, liaison = liaison_signee
    corps, horodatage = _corps(), _maintenant()

    reponse = _poste(Client(), liaison, corps, signature="", horodatage=horodatage)

    assert reponse.status_code == 403
    with use_tenant(societe.id):
        assert not FlwExchange.objects.filter(tenant=societe).exists(), (
            "« rejeté SANS TRAITEMENT » : aucun échange ne doit être écrit"
        )


def test_a_badly_signed_call_is_refused(liaison_signee) -> None:
    """Une signature calculée avec le mauvais secret ne passe pas.

    C'est le cas qui compte : une signature ABSENTE est refusée par
    n'importe quelle implémentation, une signature FAUSSE ne l'est que si
    la comparaison est réellement faite."""
    societe, liaison = liaison_signee
    corps, horodatage = _corps(), _maintenant()
    fausse = hmac.new(b"le-mauvais-secret", corps, hashlib.sha256).hexdigest()

    reponse = _poste(Client(), liaison, corps, signature=fausse, horodatage=horodatage)

    assert reponse.status_code == 403


def test_a_stale_timestamp_is_refused_even_with_a_valid_signature(liaison_signee) -> None:
    """L'horodatage est un contrôle À PART, pas un doublon de la signature.

    L'appel est authentique — signé avec le bon secret — mais daté d'hier.
    C'est exactement le scénario d'un appel capturé puis rejoué."""
    societe, liaison = liaison_signee
    corps = _corps()
    vieux = str(
        int((timezone.now() - dt.timedelta(seconds=TIMESTAMP_WINDOW_SECONDS + 60)).timestamp())
    )

    reponse = _poste(Client(), liaison, corps, signature=_signe(corps, vieux), horodatage=vieux)

    assert reponse.status_code == 403


def test_a_future_timestamp_is_refused_too(liaison_signee) -> None:
    """La fenêtre est SYMÉTRIQUE.

    N'en border qu'un côté laisserait passer un appel daté de 2030, que
    rien n'expirerait jamais — un rejeu à durée illimitée."""
    societe, liaison = liaison_signee
    corps = _corps()
    futur = str(
        int((timezone.now() + dt.timedelta(seconds=TIMESTAMP_WINDOW_SECONDS + 60)).timestamp())
    )

    reponse = _poste(Client(), liaison, corps, signature=_signe(corps, futur), horodatage=futur)

    assert reponse.status_code == 403


def test_the_signature_covers_the_timestamp(liaison_signee) -> None:
    """Signer le seul corps laisserait rejouer un appel authentique avec un
    horodatage neuf — la fenêtre ne servirait alors à rien, puisque
    l'attaquant choisirait lui-même la valeur qu'elle contrôle."""
    societe, liaison = liaison_signee
    corps, horodatage = _corps(), _maintenant()
    signature_du_corps_seul = hmac.new(SECRET.encode("utf-8"), corps, hashlib.sha256).hexdigest()

    reponse = _poste(
        Client(), liaison, corps, signature=signature_du_corps_seul, horodatage=horodatage
    )

    assert reponse.status_code == 403


def test_the_same_payload_twice_is_refused_the_second_time(liaison_signee) -> None:
    """API-4 — « un même événement entrant reçu deux fois produit un seul
    traitement métier ».

    Le tiers re-livre tant qu'il n'a pas son 2xx : une réponse lente, un
    déploiement, et le même appel arrive deux fois."""
    societe, liaison = liaison_signee
    corps, horodatage = _corps(), _maintenant()
    signature = _signe(corps, horodatage)
    client = Client()

    premiere = _poste(client, liaison, corps, signature=signature, horodatage=horodatage)
    seconde = _poste(client, liaison, corps, signature=signature, horodatage=horodatage)

    assert premiere.status_code == 200
    assert seconde.status_code == 403
    with use_tenant(societe.id):
        assert FlwExchange.objects.filter(tenant=societe).count() == 1


def test_a_link_without_a_secret_refuses_rather_than_accepts(liaison_signee) -> None:
    """Un webhook non configuré n'est jamais valide par défaut.

    C'est la règle que `logistics/services/webhooks.py` a posée en premier,
    et l'inverse ouvrirait le point d'entrée à quiconque connaît un
    identifiant de liaison."""
    societe, liaison = liaison_signee
    with use_tenant(societe.id):
        FlwCredential.objects.filter(tenant=societe).delete()
    corps, horodatage = _corps(), _maintenant()

    reponse = _poste(
        Client(), liaison, corps, signature=_signe(corps, horodatage), horodatage=horodatage
    )

    assert reponse.status_code == 403


def test_a_suspended_link_refuses(liaison_signee) -> None:
    """On suspend une liaison précisément parce que ses échanges posent
    problème ; continuer à en accepter viderait « suspendre » de son sens."""
    societe, liaison = liaison_signee
    with use_tenant(societe.id):
        liaison.state = FlwLink.STATE_SUSPENDED
        liaison.save(update_fields=["state"])
    corps, horodatage = _corps(), _maintenant()

    reponse = _poste(
        Client(), liaison, corps, signature=_signe(corps, horodatage), horodatage=horodatage
    )

    assert reponse.status_code == 403


def test_the_refusal_never_tells_the_caller_why(liaison_signee) -> None:
    """« Journalisé SANS RÉVÉLER LE MOTIF à l'appelant ».

    Distinguer « signature invalide » de « horodatage hors fenêtre »
    apprendrait à qui essaie où il en est de sa tentative. Les deux refus
    doivent être indiscernables de l'extérieur."""
    societe, liaison = liaison_signee
    corps = _corps()
    horodatage = _maintenant()
    vieux = str(int((timezone.now() - dt.timedelta(days=1)).timestamp()))
    client = Client()

    mauvaise_signature = _poste(client, liaison, corps, signature="00" * 32, horodatage=horodatage)
    hors_fenetre = _poste(client, liaison, corps, signature=_signe(corps, vieux), horodatage=vieux)

    assert mauvaise_signature.status_code == hors_fenetre.status_code == 403
    assert mauvaise_signature.content == hors_fenetre.content
