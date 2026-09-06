"""S1 (Phase 4, bloc A) — le socle de flux : ce que le modele PROMET, et
ce qui le verifie.

Un sprint de cadrage produit surtout des tables, et la tentation est de
n'ecrire que des tests qui creent une ligne et la relisent. Ils seraient
verts par construction. Les tests ci-dessous n'exercent que des points ou
le modele prend un ENGAGEMENT qu'une implementation ulterieure pourrait
trahir sans qu'on s'en apercoive :

- la charge utile se purge SANS toucher a la preuve (FLX-5) ;
- deux echanges ne peuvent pas porter la meme clef d'idempotence (FLX-4) ;
- le secret est chiffre EN BASE, pas seulement masque a l'ecran (FLX-8,
  ecart aggravant releve par l'audit §3.6) ;
- la piece metier est designee sans cle etrangere, ce qui est la condition
  du decouplage du hub ;
- les deux plafonds neufs de la Phase 4 existent et sont verifies.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from django.db import IntegrityError, connection

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.flows.models import FlwExchange, FlwPayload
from apps.flows.tests.factories import (
    FlwConnectorFactory,
    FlwCredentialFactory,
    FlwExchangeFactory,
    FlwLinkFactory,
    FlwPayloadFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return Tenant.objects.create(code="S1-FLOWS", name="Flux S1 SARL")


# --- FLX-5 : la purge laisse la preuve intacte ---------------------------------


def test_purging_the_payload_leaves_the_exchange_provable(tenant) -> None:
    """Le critere demande que la purge laisse « echange, empreinte,
    horodatage et verdict intacts ». C'est la raison d'etre de la table
    separee : si le corps transmis vivait dans une colonne de l'echange,
    le purger reviendrait a ECRIRE dans la ligne de preuve.

    Ce test ne verifie pas seulement que l'echange survit — il verifie que
    ce qui survit permet encore de PROUVER ce qui a ete envoye."""
    body = '{"facture": "FA-2026-0001", "montant": 1500000}'
    with use_tenant(tenant.id):
        exchange = FlwExchangeFactory(
            tenant=tenant,
            payload_fingerprint=FlwExchange.fingerprint_of(body),
            result_code="ACCEPTE",
            state=FlwExchange.STATE_ACCEPTED,
            settled_at=dt.datetime(2026, 3, 4, 8, 0, tzinfo=dt.UTC),
        )
        FlwPayloadFactory(tenant=tenant, exchange=exchange, body=body)

        FlwPayload.objects.filter(exchange=exchange).delete()

        exchange.refresh_from_db()
        assert not FlwPayload.objects.filter(exchange=exchange).exists()

    # La preuve tient toujours : on peut affirmer QUE ce corps precis est
    # celui qui est parti, sans le conserver.
    assert exchange.payload_fingerprint == FlwExchange.fingerprint_of(body)
    assert exchange.result_code == "ACCEPTE"
    assert exchange.state == FlwExchange.STATE_ACCEPTED
    assert exchange.settled_at is not None
    # Et on ne peut PAS reconstruire le corps depuis l'empreinte — c'est
    # bien une purge, pas un encodage.
    assert body not in exchange.payload_fingerprint


def test_the_fingerprint_distinguishes_two_different_bodies(tenant) -> None:
    """Falsification du test precedent : une empreinte constante le
    satisferait aussi. Elle doit varier avec le corps, sans quoi elle ne
    prouve rien."""
    assert FlwExchange.fingerprint_of('{"a": 1}') != FlwExchange.fingerprint_of('{"a": 2}')
    assert FlwExchange.fingerprint_of('{"a": 1}') == FlwExchange.fingerprint_of('{"a": 1}')


# --- FLX-4 : l'idempotence est une promesse faite au tiers ---------------------


def test_two_exchanges_cannot_share_an_idempotency_key(tenant) -> None:
    """« Rejeu transmettant la meme clef d'idempotence, sans doublon chez
    le tiers » ne serait qu'une intention si rien n'empechait deux
    echanges de porter la meme clef. La contrainte vit en BASE : un service
    peut etre contourne, une contrainte non."""
    with use_tenant(tenant.id):
        link = FlwLinkFactory(tenant=tenant)
        FlwExchangeFactory(tenant=tenant, link=link, idempotency_key="cle-unique")
        with pytest.raises(IntegrityError):
            FlwExchangeFactory(tenant=tenant, link=link, idempotency_key="cle-unique")


def test_many_exchanges_may_have_no_idempotency_key_yet(tenant) -> None:
    """La contrepartie, et elle compte : la clef est calculee au moment de
    la mise en file (S4). Une contrainte d'unicite sans condition sur la
    chaine vide rendrait impossible la creation de deux echanges avant ce
    calcul — c'est-a-dire le cas nominal."""
    with use_tenant(tenant.id):
        link = FlwLinkFactory(tenant=tenant)
        FlwExchangeFactory(tenant=tenant, link=link)
        FlwExchangeFactory(tenant=tenant, link=link)
        assert FlwExchange.objects.filter(link=link, idempotency_key="").count() == 2


# --- FLX-8 / audit §3.6 : le secret est chiffre EN BASE ------------------------


def test_the_credential_secret_is_encrypted_at_rest(tenant) -> None:
    """L'audit relevait `LogServiceProvider.webhook_secret` stocke en clair
    « alors que `EncryptedCharField` existe » (§3.6, ecart aggravant de
    FLX-8). Ce test lit la colonne en SQL BRUT : verifier via l'ORM ne
    prouverait rien, puisque le champ dechiffre a la lecture — on
    verifierait alors que le chiffrement est transparent, pas qu'il a lieu.
    """
    secret = "cle-api-tres-secrete-4f2a"
    with use_tenant(tenant.id):
        credential = FlwCredentialFactory(tenant=tenant, secret=secret)

        with connection.cursor() as cursor:
            cursor.execute("SELECT secret FROM flw_credential WHERE id = %s", [credential.id])
            stored = cursor.fetchone()[0]

    assert stored != secret, "Le secret est stocke EN CLAIR dans la base."
    assert secret not in stored
    # Et il reste lisible par l'application : un chiffrement qui perd la
    # donnee protegerait parfaitement et ne servirait a rien.
    with use_tenant(tenant.id):
        assert FlwCredentialFactory._meta.model.objects.get(id=credential.id).secret == secret


# --- Le decouplage du hub ------------------------------------------------------


def test_the_business_document_is_referenced_without_a_foreign_key() -> None:
    """La condition du decouplage, verifiee par introspection plutot que
    par lecture : une FK vers un modele metier obligerait `flows` a
    dependre de `accounting`, puis de tous les modules qui emettent un
    echange — le socle deviendrait le neuvieme module couple aux huit
    autres.

    On verifie donc que `document_id` est un UUID NU, et que les seules
    relations sortantes de l'echange restent internes au hub."""
    field = FlwExchange._meta.get_field("document_id")
    assert field.get_internal_type() == "UUIDField", (
        "`document_id` est devenu une relation : le hub connait desormais un "
        "modele metier, ce que la decision structurante n°2 du cahier interdit."
    )
    related_apps = {
        f.related_model._meta.app_label
        for f in FlwExchange._meta.get_fields()
        if f.is_relation and f.related_model is not None
    }
    assert related_apps <= {"flows", "core"}, (
        f"Le hub reference des modules metier : {sorted(related_apps - {'flows', 'core'})}"
    )


def test_the_partition_key_is_the_first_day_of_the_month() -> None:
    """`partition_month` prepare la bascule en table partitionnee. Une cle
    qui ne serait pas normalisee au premier du mois produirait autant de
    partitions que de jours — et la bascule deviendrait une reprise de
    donnees, ce que ce champ existe precisement pour eviter."""
    assert FlwExchange.month_of(dt.date(2026, 3, 27)) == dt.date(2026, 3, 1)
    assert FlwExchange.month_of(dt.date(2026, 3, 1)) == dt.date(2026, 3, 1)


# --- Le contrat public ---------------------------------------------------------


def test_the_public_contract_answers_for_a_document(tenant) -> None:
    """Ce que le contrat public sert a faire : repondre « qu'est devenue
    cette piece chez le tiers ? » depuis la fiche de la piece, sans que le
    module appelant connaisse `FlwExchange`."""
    from apps.flows.services.public import (
        count_exchanges_awaiting_verdict,
        has_active_link,
        list_exchanges_for_document,
    )

    document_id = uuid.uuid4()
    with use_tenant(tenant.id):
        connector = FlwConnectorFactory(tenant=tenant, code="dgi")
        link = FlwLinkFactory(tenant=tenant, connector=connector)
        FlwExchangeFactory(
            tenant=tenant,
            link=link,
            document_type="facture_vente",
            document_id=document_id,
            state=FlwExchange.STATE_AWAITING_VERDICT,
        )

        rows = list_exchanges_for_document(
            tenant, document_type="facture_vente", document_id=document_id
        )
        assert len(rows) == 1
        assert rows[0]["state"] == FlwExchange.STATE_AWAITING_VERDICT
        # Des primitives, jamais l'objet ORM (regle de couplage n°1).
        assert not hasattr(rows[0], "_meta")

        assert count_exchanges_awaiting_verdict(tenant) == 1

        # La liaison est en brouillon : le bouton d'envoi ne doit pas etre
        # propose. C'est la LIAISON qui est interrogee, jamais le
        # connecteur — deux tenants sur le meme adaptateur ont deux
        # enrolements independants.
        assert has_active_link(tenant, connector_code="dgi") is False
        link.state = link.STATE_ACTIVE
        link.save(update_fields=["state"])
        assert has_active_link(tenant, connector_code="dgi") is True


def test_a_document_without_any_exchange_gets_an_empty_list(tenant) -> None:
    """Le cas NORMAL pour l'immense majorite des pieces — jamais une
    exception, jamais une anomalie a signaler."""
    from apps.flows.services.public import list_exchanges_for_document

    with use_tenant(tenant.id):
        assert (
            list_exchanges_for_document(
                tenant, document_type="facture_vente", document_id=uuid.uuid4()
            )
            == []
        )


# --- Les deux budgets neufs de la Phase 4 --------------------------------------


def test_the_two_new_phase4_budgets_exist() -> None:
    """S1 a pour definition de fin de POSER ces deux budgets. Un plafond
    absent des reglages serait un plafond dont la garde d'architecture
    leverait `AttributeError` au lieu de mesurer."""
    from django.conf import settings

    assert settings.BUDGET_MAX_ADAPTERS == 12
    assert settings.BUDGET_MAX_PUBLIC_OPERATIONS == 80
