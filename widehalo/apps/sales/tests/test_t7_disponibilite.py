"""T7 (bloc G, COM-3) — ce qu'on publie comme disponible.

**Le critère tient dans un mot** : « la publication de disponibilité
reflète le stock **disponible à la vente** au sens de la Phase 3,
réservations déduites, **et non le stock physique** ».

**Ce que la mesure disait avant d'écrire.** La primitive existait déjà —
`available_to_sell` / `get_available_stock_qty` valent `qty − qty_reserved`
sur les emplacements internes (RG-STK-8). Ce qui manquait était la
PUBLICATION : `OP_PUBLISH_DATASET` appartient au jeu fermé des huit
opérations depuis S1, l'adaptateur sait la servir, et aucune fonction de la
surface publique ne permettait de la demander. Le même vide
qu'`initiate_payment` avant le bloc D.

**Pourquoi ce test regarde le CORPS publié et pas le retour de la
fonction.** Ce qui compte n'est pas qu'un échange soit créé, c'est le
chiffre qu'il transporte. Un test qui vérifierait seulement « une
publication a eu lieu » passerait encore le jour où quelqu'un publierait le
stock physique — c'est-à-dire le jour où le critère serait violé.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from apps.catalog.tests.factories import ProductTemplateFactory, ProductVariantFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.flows.models import FlwExchange, FlwLink
from apps.flows.operations import OP_PUBLISH_DATASET
from apps.flows.tests.factories import FlwConnectorFactory, FlwLinkFactory
from apps.sales.services.shop_publication import CONNECTOR_CODE, publish_availability
from apps.stocks.models import StkLocation
from apps.stocks.tests.factories import StkLocationFactory, StkQuantFactory

pytestmark = pytest.mark.django_db

PHYSIQUE = Decimal("10")
RESERVE = Decimal("4")
DISPONIBLE = PHYSIQUE - RESERVE


@pytest.fixture
def boutique_raccordee():
    tenant = Tenant.objects.create(code="SAL-T7D", name="Disponibilité")
    with use_tenant(tenant.id):
        gamme = ProductTemplateFactory(tenant=tenant, name="Chemise")
        variante = ProductVariantFactory(tenant=tenant, template=gamme, reference="SKU-DISPO")
        emplacement = StkLocationFactory(tenant=tenant, type=StkLocation.TYPE_INTERNE)
        StkQuantFactory(
            tenant=tenant,
            variant_id=variante.id,
            location=emplacement,
            qty=PHYSIQUE,
            qty_reserved=RESERVE,
        )
        connecteur = FlwConnectorFactory(tenant=tenant, code=CONNECTOR_CODE)
        FlwLinkFactory(tenant=tenant, connector=connecteur, state=FlwLink.STATE_ACTIVE)
    return tenant, variante


def _corps_publie(tenant) -> dict:
    from apps.flows.models import FlwPayload

    echange = (
        FlwExchange.objects.filter(operation=OP_PUBLISH_DATASET).order_by("-created_at").first()
    )
    assert echange is not None, "Aucune publication n'a été mise en file."
    payload = FlwPayload.objects.filter(exchange=echange).first()
    assert payload is not None, "La publication est partie sans charge utile."
    return json.loads(payload.body)


def test_the_published_quantity_deducts_reservations(boutique_raccordee) -> None:
    """**LE critère.** Publier le physique reviendrait à vendre ce qui est
    déjà promis : la boutique accepterait la commande, et c'est à la
    préparation qu'on découvrirait qu'il n'y a rien à expédier."""
    tenant, _variante = boutique_raccordee
    with use_tenant(tenant.id):
        accuse = publish_availability(tenant, variant_ids=[_variante.id])
        assert accuse is not None
        corps = _corps_publie(tenant)

    lignes = corps["availability"]
    assert len(lignes) == 1
    assert Decimal(lignes[0]["available_qty"]) == DISPONIBLE, (
        f"La disponibilité publiée vaut {lignes[0]['available_qty']} ; attendu "
        f"{DISPONIBLE} = {PHYSIQUE} physique − {RESERVE} réservé (RG-STK-8)."
    )
    assert Decimal(lignes[0]["available_qty"]) != PHYSIQUE, (
        "Le stock PHYSIQUE est publié : c'est exactement ce que COM-3 interdit."
    )


def test_the_publication_goes_through_the_hub_as_op2(boutique_raccordee) -> None:
    """La publication passe par le hub, jamais par un appel réseau du
    module métier — règle de couplage n°1, et `OP_PUBLISH_DATASET` est
    l'opération que le cahier prévoit pour cela."""
    tenant, variante = boutique_raccordee
    with use_tenant(tenant.id):
        accuse = publish_availability(tenant, variant_ids=[variante.id])

        assert accuse is not None
        assert accuse["operation"] == OP_PUBLISH_DATASET
        assert accuse["state"] == FlwExchange.STATE_QUEUED


def test_publishing_twice_does_not_collide_on_idempotency(boutique_raccordee) -> None:
    """**Le défaut payé trois fois dans cette vague.** Une publication de
    disponibilité se refait — à chaque heure, à chaque mouvement de stock.
    Sans occurrence distincte, la seconde heurterait
    `uniq_flw_exchange_idempotency_key` et la planification mourrait au
    deuxième passage, en silence.

    Vu sur OP8 au lot T3, retrouvé sur OP5 au lot T5, et il aurait
    recommencé ici."""
    import datetime as dt

    from django.utils import timezone

    tenant, variante = boutique_raccordee
    with use_tenant(tenant.id):
        maintenant = timezone.now()
        premier = publish_availability(tenant, variant_ids=[variante.id], now=maintenant)
        second = publish_availability(
            tenant, variant_ids=[variante.id], now=maintenant + dt.timedelta(hours=1)
        )

        assert premier is not None
        assert second is not None
        assert premier["id"] != second["id"]
        assert FlwExchange.objects.filter(operation=OP_PUBLISH_DATASET).count() == 2


def test_without_a_shop_link_nothing_is_published(boutique_raccordee) -> None:
    """Une société qui ne vend pas en ligne n'est pas en panne.

    Rendre `None` plutôt que lever, c'est ce qui permet à la commande
    périodique de traiter toutes les sociétés sans que celles sans boutique
    fassent échouer la passe pour les autres."""
    tenant, variante = boutique_raccordee
    with use_tenant(tenant.id):
        FlwLink.objects.update(state=FlwLink.STATE_SUSPENDED)
        assert publish_availability(tenant, variant_ids=[variante.id]) is None
        assert not FlwExchange.objects.filter(operation=OP_PUBLISH_DATASET).exists()


def test_the_periodic_command_publishes_for_connected_tenants_only(boutique_raccordee) -> None:
    """**La commande est ce qui rend la publication non décorative** : sans
    elle, `publish_availability` n'aurait aucun appelant de production.

    Elle est donc exercée comme le reste. Deux propriétés en une : elle
    publie pour la société raccordée, et elle ne tombe pas sur celle qui ne
    l'est pas — sans quoi une seule société sans boutique empêcherait de
    publier pour toutes les autres."""
    from django.core.management import call_command

    tenant, _variante = boutique_raccordee
    sans_boutique = Tenant.objects.create(code="SAL-T7X", name="Sans boutique")
    with use_tenant(sans_boutique.id):
        gamme = ProductTemplateFactory(tenant=sans_boutique, name="Autre")
        ProductVariantFactory(tenant=sans_boutique, template=gamme, reference="SKU-AUTRE")

    call_command("publish_shop_availability")

    with use_tenant(tenant.id):
        assert FlwExchange.objects.filter(operation=OP_PUBLISH_DATASET).count() == 1
    with use_tenant(sans_boutique.id):
        assert not FlwExchange.objects.filter(operation=OP_PUBLISH_DATASET).exists()


def test_only_sellable_variants_are_published(boutique_raccordee) -> None:
    """Publier une matière première ou un composant interne offrirait à la
    vente ce qui n'est pas vendable.

    `catalog` sait déjà répondre à cette question (`list_sellable_variants`,
    qui filtre sur `template.is_sellable`) — et c'est par sa surface
    publique que la commande la pose, jamais en lisant ses modèles."""
    from django.core.management import call_command

    tenant, variante = boutique_raccordee
    with use_tenant(tenant.id):
        interne = ProductTemplateFactory(tenant=tenant, name="Matière", is_sellable=False)
        ProductVariantFactory(tenant=tenant, template=interne, reference="SKU-INTERNE")

    call_command("publish_shop_availability")

    with use_tenant(tenant.id):
        corps = _corps_publie(tenant)
    references = {ligne["sku"] for ligne in corps["availability"]}
    assert "SKU-DISPO" in references
    assert "SKU-INTERNE" not in references, (
        "Un article non vendable est publié comme disponible : la boutique l'offrirait à la vente."
    )
