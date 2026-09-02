"""Contrat public de `logistics` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py).

Vide au demarrage du module (LOG1), comme `sales.services.public`/
`purchase.services.public` l'etaient a leur premiere etape. Premier gap
reellement expose, ajoute pour FIN3 de `financing` (cf. plan) :
`get_shipment_reference`, necessaire pour afficher une reference lisible
sur `FinCredoc.log_shipment_id` (UUID nu, jamais de FK Django, regle de
couplage n°1) — meme patron que `purchase.services.public.
get_order_reference`.

Gap PT8 du chantier "fiche partenaire a onglets par role" (cf. plan) :
`list_shipments_for_partner`. **Deviation par rapport au plan a
signaler** : le plan supposait un champ deja existant referencant un
partenaire transporteur (style `LogTrip.carrier_partner_id`) — en
lisant reellement `apps/logistics/models.py` avant d'ecrire ce gap,
AUCUN champ de ce module ne referencait `apps.partners.models.Partner`
(ni sur `LogTrip`, trajets de flotte interne sans lien fournisseur, ni
sur `LogServiceProvider`, annuaire autonome de prestataires). Un champ
`LogServiceProvider.partner_id` (UUID nu, nullable, sans migration de
donnees) a donc ete ajoute pour ce chantier, meme discipline que
`catalog.ProductSupplierInfo.priority`/`origin`/`min_qty` (PU2) — les
prestataires existants restent `partner_id=None` jusqu'a rattachement
manuel a un `Partner` (role `carrier`). `list_trips_for_partner` n'a
PAS ete ajoute : `LogTrip` ne concerne que la flotte interne
(vehicule/chauffeur propres), aucune notion de tiers transporteur n'y
a de sens."""

from __future__ import annotations

from typing import Any

from apps.logistics.models import LogShipment


def get_shipment_reference(shipment_id: Any) -> str:
    """Retourne une chaine vide, jamais une exception, si l'expedition
    n'existe pas — meme discipline que `purchase.services.public.
    get_order_reference`."""
    shipment = LogShipment.objects.filter(id=shipment_id).first()
    return shipment.reference if shipment is not None else ""


def list_shipments_for_partner(partner_id: Any, *, limit: int = 20) -> list[dict[str, Any]]:
    """Gap PT8 (cf. docstring du module ci-dessus pour la deviation
    signalee sur `LogServiceProvider.partner_id`) : alimente l'onglet
    "Transporteur" de la fiche partenaire avec les `LogShipment` dont le
    `carrier` est le `LogServiceProvider` rattache a ce `partner_id` —
    `partners` ne doit jamais importer `apps.logistics.models` (regle de
    couplage n°1).

    Retourne des dicts primitifs `{"id", "reference", "origin",
    "destination", "state", "freight_cost_mga"}`, jamais l'objet
    `LogShipment`, tries par `created_at` decroissant (expedition la
    plus recente en premier — `LogShipment` n'a pas de champ `date`
    unique, contrairement a `PurOrder`/`SalesOrder`). Liste vide, jamais
    d'exception, si aucun `LogServiceProvider` n'est rattache a ce
    `partner_id` ou si ce prestataire n'a aucune expedition."""
    shipments = LogShipment.objects.filter(carrier__partner_id=partner_id).order_by("-created_at")[
        :limit
    ]
    return [
        {
            "id": shipment.id,
            "reference": shipment.reference,
            "origin": shipment.origin,
            "destination": shipment.destination,
            "state": shipment.state,
            "freight_cost_mga": shipment.freight_cost_mga,
        }
        for shipment in shipments
    ]
