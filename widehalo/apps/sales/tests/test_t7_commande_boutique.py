"""T7 (bloc G, COM-1 à COM-4) — la commande de boutique qui entre.

**Ce que la mesure disait avant d'écrire une ligne** : rien n'existait.
Aucune ingestion de commande dans `sales`, aucune référence externe sur
`SalesOrder`, donc aucune déduplication possible. Les quatre critères sont
une construction, pas une réparation — comme BNK-4 l'était.

**La ligne que COM-1 fait défendre, et elle est nette.** `confirm_order`
appelle `procurement.qualify_and_process_order` : confirmer une commande
PRODUIT des mouvements. L'ingestion doit donc s'arrêter au statut initial
et ne jamais confirmer — c'est un humain qui confirmera, une fois qu'il
aura vu ce qui est arrivé.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest

from apps.catalog.tests.factories import ProductTemplateFactory, ProductVariantFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.sales.models import SalesOrder
from apps.sales.services.shop_ingest import ingest_shop_orders

pytestmark = pytest.mark.django_db

BOUTIQUE = "boutique-mg"


@pytest.fixture
def catalogue():
    tenant = Tenant.objects.create(code="SAL-T7", name="Commerce")
    with use_tenant(tenant.id):
        gamme = ProductTemplateFactory(tenant=tenant, name="Chemise")
        variante = ProductVariantFactory(tenant=tenant, template=gamme, reference="SKU-CHEMISE-L")
    return tenant, variante


def _commande(reference: str, *, sku: str = "SKU-CHEMISE-L", partner_id=None, qty="2") -> dict:
    return {
        "reference": reference,
        "partner_id": str(partner_id or uuid.uuid4()),
        "lines": [{"sku": sku, "qty": qty, "unit_price_mga": "15000"}],
    }


def _charge(*commandes: dict) -> str:
    return json.dumps({"orders": list(commandes)})


def test_an_ingested_order_stays_at_the_initial_state(catalogue) -> None:
    """**COM-1, et c'est le critère qui décide de tout** : « une commande
    ingérée crée un document au statut initial et ne produit ni facture, ni
    mouvement de stock, ni écriture ».

    `confirm_order` déclenche la qualification d'approvisionnement — donc
    des mouvements. Rester en `draft` n'est pas une timidité : c'est la
    seule façon de tenir l'interdit du §4.4 sur un flux entrant."""
    tenant, _variante = catalogue
    with use_tenant(tenant.id):
        rapport = ingest_shop_orders(tenant, _charge(_commande("SHOP-1")), shop_code=BOUTIQUE)

        assert len(rapport.created) == 1
        commande = rapport.created[0]
        assert commande.state == SalesOrder.STATE_DRAFT
        assert rapport.produced_no_side_effect
        assert commande.lines.count() == 1
        assert commande.lines.first().qty == Decimal("2")


def test_an_unknown_article_does_not_block_the_other_orders(catalogue) -> None:
    """**COM-2** : « un article de boutique sans correspondance dans le
    référentiel interne place la commande en anomalie **sans bloquer
    l'ingestion des autres** ».

    C'est la leçon payée au bloc E, transposée : un lot qui tombe en entier
    pour une ligne oblige l'exploitant à trouver lui-même la fautive."""
    tenant, _variante = catalogue
    with use_tenant(tenant.id):
        rapport = ingest_shop_orders(
            tenant,
            _charge(
                _commande("SHOP-1"),
                _commande("SHOP-2", sku="SKU-INCONNU"),
                _commande("SHOP-3"),
            ),
            shop_code=BOUTIQUE,
        )

        assert len(rapport.created) == 2, (
            "Les commandes dont les articles sont reconnus doivent entrer : refuser "
            "le lot pour l'une d'elles est ce que COM-2 interdit."
        )
        assert {c.external_reference for c in rapport.created} == {"SHOP-1", "SHOP-3"}
        assert len(rapport.rejected) == 1
        assert "SKU-INCONNU" in rapport.rejected[0].reason


def test_an_order_mixing_known_and_unknown_articles_carries_its_anomaly(catalogue) -> None:
    """La commande existe, **et porte son anomalie** : c'est ce que « place
    la commande en anomalie » veut dire.

    La ligne inconnue n'est PAS écrite : l'écrire avec un article nul
    produirait un total faux, que quelqu'un finirait par confirmer."""
    tenant, _variante = catalogue
    with use_tenant(tenant.id):
        melangee = _commande("SHOP-9")
        melangee["lines"].append({"sku": "SKU-FANTOME", "qty": "1", "unit_price_mga": "9000"})
        rapport = ingest_shop_orders(tenant, _charge(melangee), shop_code=BOUTIQUE)

        assert len(rapport.created) == 1
        commande = rapport.created[0]
        assert commande in rapport.with_anomaly
        assert "SKU-FANTOME" in commande.ingestion_anomaly
        assert commande.lines.count() == 1, (
            "La ligne dont l'article est inconnu ne doit pas être écrite : elle "
            "fausserait le total de la commande."
        )
        assert commande.state == SalesOrder.STATE_DRAFT


def test_the_same_shop_reference_creates_one_document(catalogue) -> None:
    """**COM-4** : « une commande reçue en double, identifiée par sa
    référence de boutique, ne crée qu'un seul document ».

    Le cas est le plus banal qui soit : une boutique qui n'obtient pas de
    2xx re-livre son événement."""
    tenant, _variante = catalogue
    with use_tenant(tenant.id):
        premier = ingest_shop_orders(tenant, _charge(_commande("SHOP-42")), shop_code=BOUTIQUE)
        second = ingest_shop_orders(tenant, _charge(_commande("SHOP-42")), shop_code=BOUTIQUE)

        assert len(premier.created) == 1
        assert second.created == []
        assert len(second.duplicates) == 1, (
            "Le doublon doit être SIGNALÉ : absorbé en silence, la boutique et nous "
            "croirions deux choses différentes."
        )
        assert SalesOrder.objects.filter(external_reference="SHOP-42").count() == 1


def test_two_shops_may_share_a_reference(catalogue) -> None:
    """La déduplication porte sur le COUPLE (boutique, référence).

    Deux marchands numérotent tous deux à partir de 1 : confondre leurs
    commandes en ferait disparaître une, ce qui est pire que le doublon
    qu'on évite."""
    tenant, _variante = catalogue
    with use_tenant(tenant.id):
        ingest_shop_orders(tenant, _charge(_commande("1042")), shop_code="boutique-a")
        second = ingest_shop_orders(tenant, _charge(_commande("1042")), shop_code="boutique-b")

        assert len(second.created) == 1
        assert SalesOrder.objects.filter(external_reference="1042").count() == 2


def test_an_order_without_a_shop_reference_is_refused(catalogue) -> None:
    """Sans référence, COM-4 est inapplicable : rien ne distinguerait une
    re-livraison d'une commande neuve, et chaque envoi créerait un doublon.

    La refuser est le seul choix qui ne fabrique pas de fausses
    commandes."""
    tenant, _variante = catalogue
    with use_tenant(tenant.id):
        sans_reference = _commande("")
        rapport = ingest_shop_orders(tenant, _charge(sans_reference), shop_code=BOUTIQUE)

        assert rapport.created == []
        assert len(rapport.rejected) == 1
        assert SalesOrder.objects.count() == 0


def test_an_unreadable_payload_creates_nothing(catalogue) -> None:
    """Une charge utile illisible est un résultat, pas une exception : le
    hub réessaierait trois fois un contenu qui ne changera pas."""
    tenant, _variante = catalogue
    with use_tenant(tenant.id):
        rapport = ingest_shop_orders(tenant, "ceci n'est pas du JSON", shop_code=BOUTIQUE)

        assert rapport.created == []
        assert len(rapport.rejected) == 1
        assert SalesOrder.objects.count() == 0


def test_a_malformed_partner_identifier_never_raises(catalogue) -> None:
    """Un identifiant malformé venu d'un tiers ne remonte jamais en 500.

    C'est la discipline posée par T4bis pour tout le dépôt, et une surface
    alimentée par une boutique externe est exactement là où elle compte."""
    tenant, _variante = catalogue
    with use_tenant(tenant.id):
        brute = _commande("SHOP-77")
        brute["partner_id"] = "pas-un-uuid"
        rapport = ingest_shop_orders(tenant, _charge(brute), shop_code=BOUTIQUE)

        assert rapport.created == []
        assert len(rapport.rejected) == 1
