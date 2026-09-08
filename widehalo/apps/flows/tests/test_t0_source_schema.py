"""T0 — le hub confronte enfin une correspondance à NOTRE schéma.

**Ce que ces tests mesurent, et pourquoi ils n'existaient pas avant.**
`save_mapping` (S5) validait `field_map` contre `target_schema`,
c'est-à-dire contre ce que le TIERS déclare attendre. Rien ne regardait ce
que la correspondance allait LIRE chez nous. Une règle
`{"marge": {"source": "lines[].margin_pct"}}` était donc acceptée,
enregistrée, et la marge partait au premier échange — alors que le §9.2
l'exclut nommément « par défaut de toute correspondance ».

Les tests ci-dessous sont écrits par CHEMIN SOURCE et non par module :
c'est la propriété qui compte, et elle doit tenir pour un module à venir
comme pour les trois d'aujourd'hui.
"""

from __future__ import annotations

import json

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.services.outbound_schemas import project_document
from apps.core.tests.utils import use_tenant
from apps.crm.tests.factories import CrmLeadFactory
from apps.flows.models import FlwExchange, FlwLink, FlwTrigger
from apps.flows.operations import OP_INITIATE_PAYMENT, OP_PUSH_DOCUMENT, OP_SUBMIT_FOR_VERDICT
from apps.flows.services import triggers
from apps.flows.services.mapping import save_mapping
from apps.flows.tests.factories import FlwConnectorFactory, FlwLinkFactory
from apps.sales.models import SalesOrder
from apps.sales.tests.factories import SalesOrderFactory, SalesOrderLineFactory

#: `django_db` SANS `transaction=True` : rien ici ne dépend d'`on_commit`
#: (les événements sont distribués à la main, jamais publiés), et la
#: variante transactionnelle vide puis re-sème toutes les données de
#: référence entre chaque test — dix fois le coût, pour aucune propriété
#: supplémentaire. L'isolation entre sociétés reste mesurée : `use_tenant`
#: pose bien `SET LOCAL app.tenant_id` dans la transaction englobante, et
#: la RLS s'applique (même montage que `test_s5_mapping.py`).
pytestmark = pytest.mark.django_db

#: Un schéma tiers minimal : ces tests ne mesurent PAS FLX-6 (déjà couvert
#: par `test_s5_mapping.py`), ils mesurent le schéma source. Le tiers
#: déclare donc exactement ce qu'il faut pour que le seul refus possible
#: vienne de chez nous.
SCHEMA_TIERS = {
    "fields": {
        "numero": {"required": True},
        "libelle": {"required": False},
    }
}


@pytest.fixture
def societe():
    return Tenant.objects.create(code="T0-SRC", name="Schéma source SARL")


def _lien(societe, *, operations=None):
    """Une liaison active, CONSTRUITE SOUS LA SOCIÉTÉ ACTIVE.

    Jamais une fixture : `FlwLink` hérite de `BaseModel`, donc de la RLS.
    Une fixture qui la créerait hors `use_tenant` se verrait refuser
    l'insertion par la politique — et le message (« new row violates
    row-level security policy ») ne désigne pas la cause."""
    connecteur = FlwConnectorFactory(
        tenant=societe, **({"supported_operations": operations} if operations else {})
    )
    return FlwLinkFactory(tenant=societe, connector=connecteur, state=FlwLink.STATE_ACTIVE)


def _enregistre(lien, *, document_type, field_map):
    return save_mapping(
        lien.tenant,
        lien,
        document_type=document_type,
        field_map=field_map,
        target_schema=SCHEMA_TIERS,
    )


# --- §9.2 : les champs que le cahier nomme --------------------------------


def test_a_mapping_that_sources_the_margin_is_refused_by_name(societe) -> None:
    """« Marge, coût de revient, commentaires de gestion — exclus par défaut
    de toute correspondance » (§9.2).

    Le refus doit NOMMER le champ et son motif : un refus qui dirait
    seulement « correspondance invalide » obligerait celui qui configure la
    liaison à comparer deux JSON à l'œil, exactement ce que FLX-6 reproche
    déjà aux refus muets."""
    with use_tenant(societe.id), pytest.raises(ValidationError) as refus:
        _enregistre(
            _lien(societe),
            document_type="sales.SalesOrder",
            field_map={"numero": {"source": "lines[].margin_pct"}},
        )
    message = " ".join(refus.value.messages)
    assert "margin_pct" in message
    assert "marge" in message.lower()


def test_a_mapping_that_sources_the_cost_price_is_refused(societe) -> None:
    with use_tenant(societe.id), pytest.raises(ValidationError) as refus:
        _enregistre(
            _lien(societe),
            document_type="sales.SalesOrder",
            field_map={"numero": {"source": "lines[].cost_estimate_mga"}},
        )
    assert "cost_estimate_mga" in " ".join(refus.value.messages)


def test_a_mapping_that_sources_a_full_account_number_is_refused(societe) -> None:
    """« Aucun numéro de compte complet dans une trace ou une charge utile
    archivée » (§9.2). La classe PCG, elle, est bien émise."""
    with use_tenant(societe.id):
        lien = _lien(societe)
        with pytest.raises(ValidationError) as refus:
            _enregistre(
                lien,
                document_type="accounting.AccMove",
                field_map={"numero": {"source": "lines[].account_code"}},
            )
        assert "account_code" in " ".join(refus.value.messages)

        _enregistre(
            lien,
            document_type="accounting.AccMove",
            field_map={"numero": {"source": "lines[].account_class"}},
        )


def test_a_mapping_that_sources_an_undeclared_field_is_refused(societe) -> None:
    """La fermeture elle-même : ce qui n'est pas déclaré ne sort pas.

    C'est la moitié du §9.2 qui ne dépend d'aucune liste — un champ inventé,
    mal orthographié ou nouvellement ajouté au modèle est refusé sans que
    personne n'ait eu à le prévoir."""
    with use_tenant(societe.id), pytest.raises(ValidationError) as refus:
        _enregistre(
            _lien(societe),
            document_type="sales.SalesOrder",
            field_map={"numero": {"source": "salesperson_id"}},
        )
    assert "salesperson_id" in " ".join(refus.value.messages)


def test_a_mapping_on_an_undeclared_document_is_refused_entirely(societe) -> None:
    """Deny-by-default à l'échelle de la pièce.

    Les quinze autres modules du produit n'ont pas encore déclaré leurs
    schémas de sortie : aucune correspondance ne peut les désigner, et c'est
    le comportement voulu. Une correspondance qu'on ne sait pas confronter à
    notre propre schéma est exactement celle qui laisse fuir."""
    with use_tenant(societe.id), pytest.raises(ValidationError) as refus:
        _enregistre(
            _lien(societe),
            document_type="purchase.PurOrder",
            field_map={"numero": {"source": "reference"}},
        )
    assert "purchase.PurOrder" in " ".join(refus.value.messages)


def test_a_mapping_on_a_declared_field_is_accepted(societe) -> None:
    """Le témoin. Sans lui, un refus généralisé passerait pour de la
    rigueur."""
    with use_tenant(societe.id):
        correspondance = _enregistre(
            _lien(societe),
            document_type="sales.SalesOrder",
            field_map={
                "numero": {"source": "reference"},
                "libelle": {
                    "sources": ["reference", "currency"],
                    "transform": "concatenation",
                },
            },
        )
    assert correspondance.document_type == "sales.SalesOrder"


# --- §9.2 : la minimisation, par opération --------------------------------


def test_a_fiscal_connector_cannot_map_the_customer_phone_number(societe) -> None:
    """« Minimisation obligatoire : seuls les champs exigés par l'opération
    partent » (§9.2).

    Un connecteur qui ne sait que soumettre pour verdict (OP4) n'a aucun
    besoin du téléphone du client. Sans ce contrôle, la liaison e-facture
    emporterait le numéro parce qu'il se trouvait dans la fiche."""
    with use_tenant(societe.id), pytest.raises(ValidationError) as refus:
        _enregistre(
            _lien(societe, operations=[OP_SUBMIT_FOR_VERDICT]),
            document_type="crm.CrmLead",
            field_map={"numero": {"source": "phone"}},
        )
    assert "phone" in " ".join(refus.value.messages)


def test_a_payment_connector_may_map_the_customer_phone_number(societe) -> None:
    """Le même champ, la même fiche, une autre opération — et il passe.

    C'est ce couple de tests qui distingue la minimisation d'une simple
    liste noire : sans le second, interdire le téléphone partout donnerait
    exactement le même vert."""
    with use_tenant(societe.id):
        _enregistre(
            _lien(societe, operations=[OP_INITIATE_PAYMENT]),
            document_type="crm.CrmLead",
            field_map={"numero": {"source": "phone"}},
        )


# --- La projection : ce qui sort réellement -------------------------------


def test_the_projection_of_an_order_carries_the_lines_but_never_the_margin(societe) -> None:
    """La déclaration n'est pas un commentaire : elle produit la charge
    utile.

    La marge est écrite en base sur la ligne, et elle n'est pas dans la
    projection — sans que le mappeur ait eu à la retirer."""
    with use_tenant(societe.id):
        commande = SalesOrderFactory(tenant=societe, currency="MGA")
        SalesOrderLineFactory(
            tenant=societe,
            order=commande,
            description="Ciment 50 kg",
            qty=10,
            unit_price=42000,
            subtotal=420000,
            cost_estimate_mga=300000,
            margin_pct=28,
        )
        projection = project_document("sales.SalesOrder", commande.id)

    assert projection is not None
    assert projection["lines"][0]["description"] == "Ciment 50 kg"
    assert "margin_pct" not in projection["lines"][0]
    assert "cost_estimate_mga" not in projection["lines"][0]
    assert "internal_notes" not in projection


def test_the_projection_is_none_for_a_piece_of_another_company(societe) -> None:
    """Une pièce d'une autre société ne se projette pas, donc ne part pas.

    **Ce qui tient cette propriété, mesuré et non supposé.** La
    falsification a remplacé `SalesOrder.objects` par `SalesOrder.
    all_objects` dans le projecteur : ce test est resté VERT. La protection
    n'est donc pas le choix du gestionnaire — c'est la Row-Level Security,
    posée `FORCE` sur la table, qui rend la ligne invisible quelle que soit
    la porte empruntée par l'ORM.

    Le gestionnaire filtré reste le bon réflexe (il économise un aller-
    retour et il est la règle du dépôt), mais il est ici REDONDANT, et le
    dire évite de croire que ce test le garde. Corollaire désagréable, à
    écrire plutôt qu'à découvrir : celui qui passerait un projecteur à
    `all_objects` ne verrait rien rougir. Ce qui ferait rougir ce test,
    c'est la disparition de la politique RLS elle-même — gardée, elle, par
    `tests/architecture/test_rls_coverage.py`."""
    autre = Tenant.objects.create(code="T0-AUTRE", name="Autre SARL")
    with use_tenant(autre.id):
        commande = SalesOrderFactory(tenant=autre)
    with use_tenant(societe.id):
        assert project_document("sales.SalesOrder", commande.id) is None


# --- Le corps de l'échange : la projection, pas l'enveloppe ---------------


def test_the_exchange_body_carries_the_projected_document(societe) -> None:
    """Avant T0, le corps était la charge de `workflow.transitioned` — cinq
    clefs d'enveloppe. Une correspondance désignant `reference` lisait
    `None` et n'émettait rien : la correspondance était livrée, branchée, et
    silencieusement vide."""
    with use_tenant(societe.id):
        lien = _lien(societe)
        commande = SalesOrderFactory(tenant=societe)
        _enregistre(
            lien,
            document_type="sales.SalesOrder",
            field_map={"numero": {"source": "reference"}},
        )
        declencheur = FlwTrigger.objects.create(
            tenant=societe,
            link=lien,
            event_name="workflow.transitioned",
            operation=OP_PUSH_DOCUMENT,
        )
        charge = {
            "model": "sales.SalesOrder",
            "object_id": str(commande.id),
            "field": "state",
            "source": "draft",
            "target": "confirmed",
        }
        echange = triggers.fire(declencheur, charge)
        corps = json.loads(echange.payload.body)

    assert corps == {"numero": commande.reference}
    assert echange.state == FlwExchange.STATE_QUEUED


# --- Axe A1 : le filtre déclaré ------------------------------------------


def test_a_filter_on_an_undeclared_field_is_refused_at_save_time(societe) -> None:
    """« Un filtre non déclaré est refusé à l'enregistrement » (axe A1).

    Refusé à l'enregistrement, pas au premier événement : un filtre faux
    découvert en production se découvre sur la pièce d'un client, longtemps
    après que quelqu'un l'a saisi."""
    with use_tenant(societe.id), pytest.raises(ValidationError) as refus:
        triggers.save_trigger(
            societe,
            _lien(societe),
            event_name="workflow.transitioned",
            operation=OP_PUSH_DOCUMENT,
            document_type="sales.SalesOrder",
            filters=[{"field": "internal_notes", "op": "eq", "value": "x"}],
        )
    assert "internal_notes" in " ".join(refus.value.messages)


def test_a_filter_operator_outside_the_closed_set_is_refused(societe) -> None:
    with use_tenant(societe.id), pytest.raises(ValidationError) as refus:
        triggers.save_trigger(
            societe,
            _lien(societe),
            event_name="workflow.transitioned",
            operation=OP_PUSH_DOCUMENT,
            document_type="sales.SalesOrder",
            filters=[{"field": "state", "op": "regex", "value": ".*"}],
        )
    assert "regex" in " ".join(refus.value.messages)


def test_a_filter_without_a_declared_document_is_refused(societe) -> None:
    """Sans pièce déclarée il n'y a aucun « champ déclaré » contre quoi
    vérifier le filtre — et l'axe A1 redeviendrait une expression libre."""
    with use_tenant(societe.id), pytest.raises(ValidationError):
        triggers.save_trigger(
            societe,
            _lien(societe),
            event_name="workflow.transitioned",
            operation=OP_PUSH_DOCUMENT,
            filters=[{"field": "state", "op": "eq", "value": "confirmed"}],
        )


def test_a_declared_filter_selects_the_piece_it_names(societe) -> None:
    """Le bout en bout de l'axe A1 : une transition réelle, un filtre
    déclaré, et l'échange qui naît — ou non."""
    with use_tenant(societe.id):
        lien = _lien(societe)
        triggers.save_trigger(
            societe,
            lien,
            event_name="workflow.transitioned",
            operation=OP_PUSH_DOCUMENT,
            document_type="sales.SalesOrder",
            filters=[{"field": "state", "op": "eq", "value": SalesOrder.STATE_CONFIRMED}],
        )
        retenue = SalesOrderFactory(tenant=societe, state=SalesOrder.STATE_CONFIRMED)
        ecartee = SalesOrderFactory(tenant=societe, state=SalesOrder.STATE_DRAFT)

    def _charge(commande):
        return {
            "model": "sales.SalesOrder",
            "object_id": str(commande.id),
            "field": "state",
            "source": "draft",
            "target": commande.state,
        }

    with use_tenant(societe.id):
        triggers.dispatch_event_to_triggers(
            {
                "type": "workflow.transitioned",
                "payload": _charge(retenue),
                "tenant_id": str(societe.id),
            }
        )
        triggers.dispatch_event_to_triggers(
            {
                "type": "workflow.transitioned",
                "payload": _charge(ecartee),
                "tenant_id": str(societe.id),
            }
        )
        emis = list(FlwExchange.objects.filter(link=lien))

    assert [str(echange.document_id) for echange in emis] == [str(retenue.id)]


def test_a_trigger_declaring_another_piece_never_fires(societe) -> None:
    """Une erreur de configuration ne doit pas faire partir TOUTES les
    pièces au lieu d'aucune : un déclencheur qui déclare une commande ne
    tire pas sur une piste.

    **Le déclencheur n'a délibérément AUCUN filtre**, et c'est tout
    l'intérêt. La falsification l'a établi : avec un filtre, retirer le
    contrôle de pièce laisse ce test vert — le filtre `state` lit `None`
    sur une piste et retient déjà l'échange. C'est donc le cas SANS filtre
    qui mesure le contrôle : déclarer une pièce sans rien filtrer dessus
    est parfaitement légitime (« toutes les commandes »), et sans ce
    contrôle un tel déclencheur tirerait sur n'importe quelle pièce."""
    with use_tenant(societe.id):
        lien = _lien(societe)
        triggers.save_trigger(
            societe,
            lien,
            event_name="workflow.transitioned",
            operation=OP_PUSH_DOCUMENT,
            document_type="sales.SalesOrder",
        )
        piste = CrmLeadFactory(tenant=societe)
        triggers.dispatch_event_to_triggers(
            {
                "type": "workflow.transitioned",
                "payload": {
                    "model": "crm.CrmLead",
                    "object_id": str(piste.id),
                    "field": "stage",
                    "source": "a",
                    "target": "b",
                },
                "tenant_id": str(societe.id),
            }
        )
        assert not FlwExchange.objects.filter(link=lien).exists()


def test_a_trigger_on_an_unpublished_event_is_refused(societe) -> None:
    """Un déclencheur branché sur un nom d'événement qui n'existe pas ne
    tire jamais, et rien ne le signalerait — même défaut que
    `FlwTrigger.event_name` non validé, relevé au passage de T0."""
    with use_tenant(societe.id), pytest.raises(ValidationError) as refus:
        triggers.save_trigger(
            societe,
            _lien(societe),
            event_name="sales.facture_publiee",
            operation=OP_PUSH_DOCUMENT,
            document_type="sales.SalesOrder",
        )
    assert "sales.facture_publiee" in " ".join(refus.value.messages)
