"""T9 — le webhook transporteur rendait 404 sur chaque appel authentique.

**Le meme defaut que celui repare sur le hub au lot T5, laisse ouvert deux
lots durant parce qu'il n'entrait dans aucun critere des quatre cahiers.**
`carrier_webhook_endpoint` lit `LogServiceProvider.all_objects` sans
contexte de societe. Or `all_objects` ne contourne que la RLS APPLICATIVE
de `TenantManager` : la policy PostgreSQL, elle, reste en place, et
`log_service_provider` est en `FORCE ROW LEVEL SECURITY` comme toute
sous-classe de `BaseModel`. Sans `app.tenant_id`, aucune ligne ne remonte,
`get_object_or_404` leve, et le transporteur recoit 404 sur un appel
parfaitement signe.

**Pourquoi le test existant ne le voyait pas, et c'est la lecon centrale.**
`apps/logistics/tests/test_api.py::test_carrier_webhook_accepts_valid_
signature_and_rejects_invalid` passe, et il a toujours passe. pytest-django
enveloppe chaque test dans une transaction ; le `SET LOCAL app.tenant_id`
pose par la fixture `use_tenant` ne meurt donc pas a la sortie du bloc
`with` — il survit jusqu'a la fin du test. La requete du webhook lit la
ligne grace a un contexte de societe **qui n'existe que dans le harnais**.

Seul `django_db(transaction=True)` reproduit la production : chaque
requete y a sa propre transaction, et le reglage de session ne traverse
plus rien.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from django.db import ProgrammingError, connection
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.logistics.models import LogServiceProvider

pytestmark = pytest.mark.django_db(transaction=True)

SECRET = "s3cr3t-transporteur"


@pytest.fixture
def transporteur() -> LogServiceProvider:
    tenant = Tenant.objects.create(code="LOG-T9", name="Webhook transporteur")
    with use_tenant(tenant.id):
        return LogServiceProvider.objects.create(
            tenant=tenant, code="DHL-T9", name="DHL", webhook_secret=SECRET
        )


def _appel(provider_id, *, secret: str = SECRET):
    corps = json.dumps({"event": "shipment_status", "status": "in_transit"}).encode()
    signature = hmac.new(secret.encode(), corps, hashlib.sha256).hexdigest()
    return Client().post(
        f"/api/v1/logistics/webhooks/carrier/{provider_id}",
        data=corps,
        content_type="application/json",
        HTTP_X_SIGNATURE=signature,
    )


def test_an_authentic_carrier_call_is_accepted_without_any_tenant_context(
    transporteur: LogServiceProvider,
) -> None:
    """**LE critere de production.** Un transporteur n'a ni session, ni
    jeton, ni en-tete de societe — lui en faire envoyer un reviendrait a
    laisser l'appelant choisir la societe dans laquelle il ecrit.

    Sans la fenetre de lecture, cette assertion rend 404."""
    reponse = _appel(transporteur.id)

    assert reponse.status_code == 200, (
        "Le webhook transporteur refuse un appel authentique : la RLS "
        "PostgreSQL cache la ligne, et `all_objects` n'y change rien."
    )
    assert reponse.json()["status"] == "ok"


def test_a_wrong_signature_is_still_refused(transporteur: LogServiceProvider) -> None:
    """Ouvrir la lecture ne doit rien ouvrir d'autre : la signature reste
    le seul juge de l'authenticite."""
    assert _appel(transporteur.id, secret="mauvais-secret").status_code == 403


def test_an_unknown_provider_is_a_404_and_not_a_500(
    transporteur: LogServiceProvider,
) -> None:
    """Un identifiant inconnu et un identifiant malforme n'apprennent rien
    a qui essaie : les deux rendent le meme refus."""
    assert _appel("01a08600-0000-7000-8000-00000000dead").status_code == 404
    assert _appel("pas-un-uuid").status_code in (404, 422)


def test_the_open_window_never_opens_writing(transporteur: LogServiceProvider) -> None:
    """**L'autre sens, qui ne se deduit pas du premier.**

    Le remede aurait pu etre une derogation `RLS_FORCE_FOR_OWNER = False`,
    et c'est ce qui a ete tente puis retire au lot T5 : elle rend la table
    lisible ET ECRIVABLE hors societe par le proprietaire, et le critere
    d'isolation est tombe. La policy posee ici est `FOR SELECT` seule ;
    ecrire chez une autre societe doit rester refuse PAR POSTGRESQL, pas
    seulement invisible ensuite."""
    autre = Tenant.objects.create(code="LOG-T9B", name="Autre societe")

    with use_tenant(transporteur.tenant_id), pytest.raises(ProgrammingError):
        LogServiceProvider.objects.create(tenant=autre, code="INTRUS", name="Prestataire intrus")


def test_the_read_policy_is_really_installed_on_the_table() -> None:
    """La garde statique regarde de quoi les modeles heritent ; elle ne dit
    rien de ce que PostgreSQL porte reellement. Ce test interroge le
    catalogue — et il tomberait si la migration etait annulee sans que le
    code le soit."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT policyname, cmd FROM pg_policies "
            "WHERE tablename = 'log_service_provider' ORDER BY policyname"
        )
        policies = dict(cursor.fetchall())

    assert "tenant_isolation_policy" in policies
    assert policies.get("webhook_lookup_policy") == "SELECT", (
        "La policy de lecture anonyme doit etre FOR SELECT et rien d'autre : "
        "une policy ALL rendrait la table ecrivable hors societe."
    )
