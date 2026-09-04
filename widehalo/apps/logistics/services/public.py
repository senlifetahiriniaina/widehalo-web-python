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
a de sens.

Gap B2 (Phase 3, "chronologie unifiee CREDOC/import/cout debarque", cf.
plan) : `list_shipments_for_purchase_order`/
`get_shipment_transition_history`, consommes par la nouvelle vue
composite de `financing` (seul module dont les dependances declarees
atteignent a la fois `purchase` et `logistics`, cf. `apps/financing/
module.py`)."""

from __future__ import annotations

from typing import Any

from apps.logistics.models import LogShipment


def get_shipment_transition_history(shipment_id: Any) -> list[dict[str, Any]]:
    """Gap B2 (Phase 3, "chronologie unifiée CREDOC/import/coût débarqué",
    cf. plan) : historique DES transitions réellement effectuées pour
    cette expédition, motif inclus — lit directement `core.
    StateTransitionLog` (journal générique déjà alimenté automatiquement
    par le signal `django_fsm.post_transition`, cf. `apps.core.workflows`),
    jamais un nouveau champ dédié sur `LogShipment`. Exclut les tentatives
    refusées (`was_refused=True`) — seules les VRAIES transitions
    intéressent une frise chronologique, un refus de permission n'est pas
    un évènement du dossier.

    Retourne des dicts primitifs `{"at", "from_state", "to_state",
    "reason", "performed_by"}`, triés chronologiquement, jamais l'objet
    `StateTransitionLog` (régle de couplage n°1 — `core` reste consommable
    directement, mais le contrat renvoyé ici reste primitif comme le reste
    de cette surface). Liste vide, jamais une exception, si l'expédition
    n'existe pas ou n'a encore subi aucune transition."""
    from django.contrib.contenttypes.models import ContentType

    from apps.core.models.workflow import StateTransitionLog

    content_type = ContentType.objects.get_for_model(LogShipment)
    logs = StateTransitionLog.objects.filter(
        content_type=content_type, object_id=str(shipment_id), was_refused=False
    ).order_by("created_at")
    return [
        {
            "at": log.created_at,
            "from_state": log.from_state,
            "to_state": log.to_state,
            "reason": log.comment,
            "performed_by": log.performed_by.email if log.performed_by is not None else "",
        }
        for log in logs
    ]


def list_shipments_for_purchase_order(purchase_order_id: Any) -> list[dict[str, Any]]:
    """Gap B2 (Phase 3, "chronologie unifiée CREDOC/import/coût débarqué",
    cf. plan) : `financing` a besoin de retrouver, pour un dossier d'achat
    donné (`purchase_order_id`), TOUTES les expéditions qui le
    transportent — `LogShipment.purchase_order_ids` est une LISTE
    JSONField (un envoi peut consolider plusieurs commandes, cf. sa
    docstring), d'où le lookup `__contains` (containment Postgres jsonb,
    même patron que `apps.bi.views`/`apps.partners.services.defaults`) —
    ainsi que leurs dossiers douaniers (`LogCustomsFile`, atteints
    uniquement via `shipment.customs_files`, aucun lien direct vers
    `purchase_order_id`).

    Retourne des dicts primitifs imbriqués, jamais les objets ORM (règle
    de couplage n°1) : `{"id", "reference", "origin", "destination",
    "state", "block_reason", "history", "customs_files"}` — `history`
    réutilise `get_shipment_transition_history` ci-dessus ; chaque
    `customs_files[i]` est `{"id", "reference", "state", "opened_at",
    "cleared_at", "closed_at", "landed_cost_batch_id"}` (`LogCustomsFile.
    state` est un `CharField` simple, PAS un `FSMField` — aucun
    `StateTransitionLog` n'existe pour lui, cf. sa docstring : son
    "historique" se lit directement sur ses 3 champs date). Liste vide,
    jamais une exception, si aucune expédition ne transporte ce dossier."""
    shipments = LogShipment.objects.filter(
        purchase_order_ids__contains=[str(purchase_order_id)]
    ).order_by("created_at")
    return [
        {
            "id": shipment.id,
            "reference": shipment.reference,
            "origin": shipment.origin,
            "destination": shipment.destination,
            "state": shipment.state,
            "block_reason": shipment.block_reason,
            "history": get_shipment_transition_history(shipment.id),
            "customs_files": [
                {
                    "id": customs_file.id,
                    "reference": customs_file.reference,
                    "state": customs_file.state,
                    "opened_at": customs_file.opened_at,
                    "cleared_at": customs_file.cleared_at,
                    "closed_at": customs_file.closed_at,
                    "landed_cost_batch_id": customs_file.landed_cost_batch_id,
                }
                for customs_file in shipment.customs_files.order_by("opened_at")
            ],
        }
        for shipment in shipments
    ]


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
