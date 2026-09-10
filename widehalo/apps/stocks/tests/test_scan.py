"""STK-9 (Phase 3 §7.3, sprint A6, mode dégradé terrain) : `client_uuid`
comme clef d'idempotence sur `sync_scan_reception_line` — même discipline
que `apps.pos.services.orders.sync_order` (`apps/pos/tests/
test_offline_sync.py`, patron directement repris ici) : un rejeu du même
`client_uuid` (perte de réseau + nouvel essai) ne doit jamais créer un
second `StkMove`, et un rejet ne doit laisser aucun mouvement partiel.
Chaque tentative est journalisée via `AuditLog` (pas un modèle `stocks`
dédié, cf. docstring `services.scan`)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.catalog.tests.factories import (
    ProductTemplateFactory,
    ProductVariantFactory,
    UnitOfMeasureFactory,
)
from apps.core.db.uuid7 import uuid7
from apps.core.models.audit import AuditLog
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkMove
from apps.stocks.services import scan
from apps.stocks.services.barcodes import set_location_barcode
from apps.stocks.services.scan import (
    ACTION_PUTAWAY_REJECTED,
    OUTCOME_ACCEPTED,
    OUTCOME_DUPLICATE,
    UOM_PAR_DEFAUT,
    resolve_scan_uom,
    sync_scan_putaway_line,
    sync_scan_reception_line,
)
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db


@pytest.fixture
def scan_setup():
    tenant = Tenant.objects.create(code="STK-SCAN", name="Stocks Scan Tenant")
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-SCAN", name="Entrepot scan")
        supplier = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="FRS",
            name="Fournisseur",
            type=StkLocation.TYPE_FOURNISSEUR,
        )
        internal = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="A1",
            name="Rayon A1",
            type=StkLocation.TYPE_INTERNE,
        )
        variant = ProductVariantFactory(tenant=tenant, ean13="1234567890128")
        return tenant, supplier, internal, variant


def _line_kwargs(client_uuid, *, ean13, location_from, location_to):
    return {
        "client_uuid": client_uuid,
        "location_from": location_from,
        "location_to": location_to,
        "ean13": ean13,
        "qty": Decimal(1),
        "date": dt.date(2026, 3, 1),
    }


def _audit_actions(client_uuid: uuid.UUID) -> list[str]:
    return [
        log.action
        for log in AuditLog.objects.filter(
            action__in=[scan.ACTION_ACCEPTED, scan.ACTION_DUPLICATE, scan.ACTION_REJECTED]
        )
        if log.metadata.get("client_uuid") == str(client_uuid)
    ]


def test_replaying_the_same_client_uuid_never_creates_a_second_move(scan_setup) -> None:
    tenant, supplier, internal, variant = scan_setup
    client_uuid = uuid.uuid4()
    with use_tenant(tenant.id):
        kwargs = _line_kwargs(
            client_uuid, ean13=variant.ean13, location_from=supplier, location_to=internal
        )

        move1, outcome1 = sync_scan_reception_line(tenant, **kwargs)
        assert outcome1 == scan.OUTCOME_ACCEPTED
        assert move1 is not None
        assert move1.state == StkMove.STATE_DONE
        assert move1.move_type == StkMove.TYPE_RECEPTION
        assert move1.client_uuid == client_uuid

        move2, outcome2 = sync_scan_reception_line(tenant, **kwargs)
        assert outcome2 == scan.OUTCOME_DUPLICATE
        assert move2 is not None
        assert move2.id == move1.id

        assert StkMove.objects.filter(client_uuid=client_uuid).count() == 1
        actions = _audit_actions(client_uuid)
        assert len(actions) == 2
        assert set(actions) == {scan.ACTION_ACCEPTED, scan.ACTION_DUPLICATE}


def test_unknown_ean13_is_rejected_and_leaves_no_partial_move(scan_setup) -> None:
    tenant, supplier, internal, _variant = scan_setup
    client_uuid = uuid.uuid4()
    with use_tenant(tenant.id):
        kwargs = _line_kwargs(
            client_uuid,
            ean13="0000000000000",
            location_from=supplier,
            location_to=internal,
        )

        with pytest.raises(ValidationError):
            sync_scan_reception_line(tenant, **kwargs)

        assert not StkMove.objects.filter(client_uuid=client_uuid).exists()
        log = AuditLog.objects.get(action=scan.ACTION_REJECTED)
        assert log.metadata["client_uuid"] == str(client_uuid)
        assert "0000000000000" in log.metadata["detail"]
        assert log.content_type is None


def test_the_unit_comes_from_the_article_never_from_the_caller(scan_setup) -> None:
    """L'ecran envoyait `uom` dans un champ cache fige a « pc ».

    Consequence mesurable, et elle n'a rien de theorique : **toute
    reception d'un article au metre ou au kilo etait enregistree en
    pieces**. La valeur se lit desormais sur l'article, une fois le
    code-barres resolu — le seul endroit qui la connaisse. Ce test
    l'etablit sur un article dont l'unite de base n'est PAS « pc », sans
    quoi il passerait pour la mauvaise raison."""
    tenant, supplier, internal, _variant = scan_setup

    with use_tenant(tenant.id):
        metre = UnitOfMeasureFactory(tenant=tenant, code="m", name="Metre")
        gabarit = ProductTemplateFactory(tenant=tenant, base_uom=metre)
        au_metre = ProductVariantFactory(tenant=tenant, template=gabarit, ean13="4006381333931")
        assert au_metre.template.base_uom.code == "m", "l'article temoin n'est pas au metre"

        move, outcome = sync_scan_reception_line(
            tenant,
            **_line_kwargs(
                uuid.uuid4(),
                ean13="4006381333931",
                location_from=supplier,
                location_to=internal,
            ),
        )

    assert outcome == OUTCOME_ACCEPTED
    assert move is not None
    assert move.uom == "m", f"unite enregistree : {move.uom!r} — l'article est au metre"


def test_an_article_without_a_declared_unit_falls_back_rather_than_refusing(
    scan_setup,
) -> None:
    """Un article mal configure ne doit pas faire perdre une saisie deja
    prise sur le terrain — STK-9 dit « sans perte », et un referentiel
    incomplet n'est pas la faute du magasinier. Le repli est celui que le
    gabarit imposait a TOUT article jusqu'ici : il ne degrade rien."""
    assert resolve_scan_uom(uuid7()) == UOM_PAR_DEFAUT


# --------------------------------------------------------------------------
# Ranger (B-2) — cahier §13.1 « transfert », STK-5, STK-1, STK-9
# --------------------------------------------------------------------------


@pytest.fixture
def putaway_setup(scan_setup):
    """Deux etageres INTERNES et du stock sur la premiere.

    Un rangement part de stock existant : sans quoi la garde anti-negatif
    refuserait, et le test passerait pour la mauvaise raison."""
    tenant, supplier, quai, variant = scan_setup
    with use_tenant(tenant.id):
        rayon = create_location(
            tenant=tenant,
            warehouse=quai.warehouse,
            code="B2",
            name="Rayon B2",
            type=StkLocation.TYPE_INTERNE,
        )
        # Du stock reel sur le quai, pose par une reception normale.
        sync_scan_reception_line(
            tenant,
            **_line_kwargs(
                uuid.uuid4(), ean13="1234567890128", location_from=supplier, location_to=quai
            ),
        )
    return tenant, quai, rayon, variant


def _putaway_kwargs(client_uuid, *, depart, destination, ean13="1234567890128", qty="1"):
    return {
        "client_uuid": client_uuid,
        "location_from_code": depart.code,
        "location_to_code": destination.code,
        "ean13": ean13,
        "qty": Decimal(qty),
        "date": dt.date(2026, 3, 2),
    }


def test_a_putaway_is_a_single_move_carrying_both_locations(putaway_setup) -> None:
    """STK-5, et c'est le coeur du critere : « un transfert interrompu
    laisse la quantite en transit, ni dans le depot d'origine ni dans celui
    de destination, et JAMAIS PERDUE NI COMPTEE DEUX FOIS ».

    Le cahier §12.1 dit comment on l'obtient : « un transfert est un
    mouvement UNIQUE a deux emplacements, et non deux mouvements
    apparies. C'est ce qui garantit qu'il ne peut pas etre a moitie
    realise, y compris apres une coupure reseau en mode degrade. »

    On mesure donc le NOMBRE de mouvements produits, pas seulement leur
    effet : deux mouvements apparies auraient le meme effet sur le stock,
    et ouvriraient exactement le trou que le critere ferme."""
    tenant, quai, rayon, variant = putaway_setup

    with use_tenant(tenant.id):
        avant = StkMove.objects.filter(move_type=StkMove.TYPE_TRANSFERT_INTERNE).count()
        move, outcome = sync_scan_putaway_line(
            tenant, **_putaway_kwargs(uuid.uuid4(), depart=quai, destination=rayon)
        )
        apres = StkMove.objects.filter(move_type=StkMove.TYPE_TRANSFERT_INTERNE).count()

    assert outcome == OUTCOME_ACCEPTED
    assert apres - avant == 1, "un transfert doit produire UN mouvement, jamais deux"
    assert move is not None
    assert move.location_from_id == quai.id
    assert move.location_to_id == rayon.id
    assert move.state == StkMove.STATE_DONE


def test_replaying_a_putaway_never_creates_a_second_move(putaway_setup) -> None:
    """STK-9 : « sans doublon ni perte ». Le rejeu d'une file hors ligne
    n'est pas un cas rare — c'est le cas NOMINAL du mode degrade."""
    tenant, quai, rayon, _variant = putaway_setup
    ticket = uuid.uuid4()
    kwargs = _putaway_kwargs(ticket, depart=quai, destination=rayon)

    with use_tenant(tenant.id):
        premier, issue1 = sync_scan_putaway_line(tenant, **kwargs)
        second, issue2 = sync_scan_putaway_line(tenant, **kwargs)
        total = StkMove.objects.filter(client_uuid=ticket).count()

    assert issue1 == OUTCOME_ACCEPTED
    assert issue2 == OUTCOME_DUPLICATE
    assert premier is not None and second is not None
    assert premier.id == second.id
    assert total == 1


def test_an_unknown_location_is_refused_and_journalized_never_lost(putaway_setup) -> None:
    """Un code d'emplacement illisible ne doit pas faire disparaitre une
    saisie deja prise sur le terrain.

    C'est la reconciliation explicite du §7.3 : « la ligne concernee est
    presentee pour arbitrage plutot qu'appliquee en force ou rejetee en
    silence ». Le journal porte les deux codes, parce qu'un magasinier
    doit savoir LEQUEL des deux scans etait mauvais."""
    tenant, quai, _rayon, _variant = putaway_setup
    ticket = uuid.uuid4()

    with use_tenant(tenant.id), pytest.raises(ValidationError):
        sync_scan_putaway_line(
            tenant,
            client_uuid=ticket,
            location_from_code=quai.code,
            location_to_code="ETAGERE-QUI-N-EXISTE-PAS",
            ean13="1234567890128",
            qty=Decimal(1),
            date=dt.date(2026, 3, 2),
        )

    with use_tenant(tenant.id):
        assert not StkMove.objects.filter(client_uuid=ticket).exists()
        journal = AuditLog.objects.filter(action=ACTION_PUTAWAY_REJECTED).first()
    assert journal is not None
    assert journal.metadata["to"] == "ETAGERE-QUI-N-EXISTE-PAS"
    assert journal.metadata["from"] == quai.code


def test_a_virtual_location_is_never_a_putaway_destination(putaway_setup) -> None:
    """Un rangement va d'une etagere a une autre.

    Sans ce controle, le code-barres d'un emplacement de rebut ou de
    fournisseur scanne par erreur produirait un mouvement d'une tout autre
    nature que celle demandee — et un stock faux qui se propage dans la
    valorisation.

    **Ce test a d'abord passe pour la mauvaise raison, et la falsification
    l'a demasque.** Il scannait le CODE d'un emplacement de rebut ; or le
    repli de `resolve_scanned_location` ne cherche que parmi les
    emplacements INTERNES, si bien que le refus venait de la resolution —
    « introuvable » — et non du controle de type. Retirer le controle ne
    faisait donc rien tomber.

    Le rebut porte desormais un CODE-BARRES, et c'est lui qu'on scanne :
    `lookup_by_barcode` trouve n'importe quel type d'emplacement, donc la
    resolution reussit et seul le controle de type peut refuser. Le message
    est verifie pour la meme raison — sans quoi le test se remettrait a
    passer sur le mauvais refus."""
    tenant, quai, _rayon, _variant = putaway_setup
    with use_tenant(tenant.id):
        virtuel = create_location(
            tenant=tenant,
            warehouse=quai.warehouse,
            code="REBUT",
            name="Rebut",
            type=StkLocation.TYPE_REBUT,
        )
        set_location_barcode(virtuel, value="REBUT-CB-0001")
        assert virtuel.barcode == "REBUT-CB-0001", "le temoin doit etre trouvable au scan"

        with pytest.raises(ValidationError) as refus:
            sync_scan_putaway_line(
                tenant,
                client_uuid=uuid.uuid4(),
                location_from_code=quai.code,
                location_to_code="REBUT-CB-0001",
                ean13="1234567890128",
                qty=Decimal(1),
                date=dt.date(2026, 3, 2),
            )

    assert "emplacement de stockage" in "; ".join(refus.value.messages)
