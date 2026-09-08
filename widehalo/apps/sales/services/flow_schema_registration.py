"""T0 (§9.2, ligne « Pièce commerciale complète ») — ce qu'une commande et
un devis ont le droit de laisser sortir.

La règle citée, mot pour mot : « Sortie autorisée après consentement.
**Champs internes — marge, coût de revient, commentaires de gestion —
exclus par défaut de toute correspondance.** »

Les trois champs que cette phrase nomme existent, et ce sont des colonnes
réelles : `SalesOrderLine.margin_pct`, `SalesOrderLine.cost_estimate_mga`,
`SalesOrder.internal_notes`. Ils sont déclarés ici **interdits** plutôt
qu'omis, et ce n'est pas de la redondance : un champ omis est refusé par la
règle de fermeture, mais rien ne se casse le jour où quelqu'un l'ajoute
aux champs émis. Un champ nommé interdit, si.

**La marge est sur la LIGNE, pas sur l'en-tête** — c'est pour ça que le
registre sait traverser une liste (`lines[].margin_pct`). Une projection
qui n'élaguerait que l'en-tête laisserait partir la marge de chaque ligne
en croyant l'avoir retirée.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.core.services.outbound_schemas import (
    ALL_OPERATIONS,
    CATEGORY_COMMERCIAL_DOCUMENT,
    CATEGORY_PARTY_IDENTITY,
    OutboundDocument,
    OutboundField,
    register_outbound_document,
)

DOCUMENT_ORDER = "sales.SalesOrder"
DOCUMENT_QUOTATION = "sales.SalesQuotation"

#: Le nom du contact et l'adresse de livraison sont des données
#: personnelles logées dans une pièce commerciale : la minimisation du §9.2
#: leur est due, pas celle de la pièce. Elles n'ont d'objet que quand la
#: pièce est REMISE au tiers lui-même — pousser un document (OP1) ou
#: déposer un fichier (OP3). Une soumission fiscale (OP4), une publication
#: de jeu de données (OP2) ou un mouvement d'argent (OP5) n'en ont aucun
#: besoin, et le refus le dira.
OPERATIONS_DE_REMISE = frozenset({"OP1", "OP3"})

_MOTIF_MARGE = (
    "marge commerciale — champ interne au sens du §9.2, exclu par défaut de "
    "toute correspondance : le transmettre révélerait au tiers la structure "
    "de prix de l'entreprise"
)
_MOTIF_COUT = (
    "coût de revient — champ interne au sens du §9.2, exclu par défaut de "
    "toute correspondance : c'est le secret industriel du client, jamais une "
    "donnée de la pièce commerciale"
)
_MOTIF_NOTES_INTERNES = (
    "commentaire de gestion — champ interne au sens du §9.2 : rédigé par un "
    "salarié pour ses collègues, jamais pour le tiers, et souvent nominatif"
)
_MOTIF_BLOCAGE = (
    "motif de blocage — commentaire de gestion au sens du §9.2 : il annonce "
    "au tiers que son client est bloqué en crédit, ce qui est une "
    "appréciation interne et non un fait de la pièce"
)


def _lignes(objet: Any) -> list[dict[str, Any]]:
    return [
        {
            "sequence": ligne.sequence,
            "description": ligne.description,
            "qty": ligne.qty,
            "uom": ligne.uom,
            "unit_price": ligne.unit_price,
            "discount_pct": ligne.discount_pct,
            "tax_rate": ligne.tax_rate,
            "subtotal": ligne.subtotal,
        }
        for ligne in objet.lines.order_by("sequence", "created_at")
    ]


def _entete(objet: Any) -> dict[str, Any]:
    return {
        "reference": objet.reference,
        "date": objet.date,
        "state": objet.state,
        "currency": objet.currency,
        "incoterm": objet.incoterm,
        "amount_untaxed": objet.amount_untaxed,
        "amount_tax": objet.amount_tax,
        "amount_total": objet.amount_total,
        "amount_total_mga": objet.amount_total_mga,
        "notes": objet.notes,
        "partner_id": str(objet.partner_id) if objet.partner_id else "",
        "contact": objet.contact,
        "delivery_address": objet.delivery_address,
        "lines": _lignes(objet),
    }


def build_order(object_id: UUID) -> dict[str, Any] | None:
    from apps.sales.models import SalesOrder

    commande = SalesOrder.objects.filter(id=object_id).prefetch_related("lines").first()
    if commande is None:
        return None
    document = _entete(commande)
    document["date_confirmed"] = commande.date_confirmed
    document["commitment_date"] = commande.commitment_date
    document["is_export"] = commande.is_export
    return document


def build_quotation(object_id: UUID) -> dict[str, Any] | None:
    from apps.sales.models import SalesQuotation

    devis = SalesQuotation.objects.filter(id=object_id).prefetch_related("lines").first()
    if devis is None:
        return None
    document = _entete(devis)
    document["validity_date"] = devis.validity_date
    return document


_CHAMPS_COMMUNS: tuple[OutboundField, ...] = (
    OutboundField("reference", "Référence du document", CATEGORY_COMMERCIAL_DOCUMENT),
    OutboundField("date", "Date du document", CATEGORY_COMMERCIAL_DOCUMENT, filterable=True),
    OutboundField("state", "État", CATEGORY_COMMERCIAL_DOCUMENT, filterable=True),
    OutboundField("currency", "Devise", CATEGORY_COMMERCIAL_DOCUMENT, filterable=True),
    OutboundField("incoterm", "Incoterm", CATEGORY_COMMERCIAL_DOCUMENT),
    OutboundField("amount_untaxed", "Montant hors taxe", CATEGORY_COMMERCIAL_DOCUMENT),
    OutboundField("amount_tax", "Montant de taxe", CATEGORY_COMMERCIAL_DOCUMENT),
    OutboundField("amount_total", "Montant total", CATEGORY_COMMERCIAL_DOCUMENT),
    OutboundField("amount_total_mga", "Montant total en ariary", CATEGORY_COMMERCIAL_DOCUMENT),
    OutboundField("notes", "Notes portées sur le document", CATEGORY_COMMERCIAL_DOCUMENT),
    OutboundField(
        "partner_id",
        "Identifiant du tiers",
        CATEGORY_PARTY_IDENTITY,
        required_by=ALL_OPERATIONS,
        filterable=True,
    ),
    OutboundField(
        "contact",
        "Nom du contact",
        CATEGORY_PARTY_IDENTITY,
        required_by=OPERATIONS_DE_REMISE,
    ),
    OutboundField(
        "delivery_address",
        "Adresse de livraison",
        CATEGORY_PARTY_IDENTITY,
        required_by=OPERATIONS_DE_REMISE,
    ),
    OutboundField("lines[].sequence", "Rang de la ligne", CATEGORY_COMMERCIAL_DOCUMENT),
    OutboundField("lines[].description", "Désignation", CATEGORY_COMMERCIAL_DOCUMENT),
    OutboundField("lines[].qty", "Quantité", CATEGORY_COMMERCIAL_DOCUMENT),
    OutboundField("lines[].uom", "Unité", CATEGORY_COMMERCIAL_DOCUMENT),
    OutboundField("lines[].unit_price", "Prix unitaire", CATEGORY_COMMERCIAL_DOCUMENT),
    OutboundField("lines[].discount_pct", "Remise (%)", CATEGORY_COMMERCIAL_DOCUMENT),
    OutboundField("lines[].tax_rate", "Taux de taxe", CATEGORY_COMMERCIAL_DOCUMENT),
    OutboundField("lines[].subtotal", "Sous-total de ligne", CATEGORY_COMMERCIAL_DOCUMENT),
    # Les trois champs que le §9.2 NOMME, déclarés interdits pour être
    # testables (cf. docstring de module).
    OutboundField(
        "lines[].margin_pct",
        "Marge de ligne",
        CATEGORY_COMMERCIAL_DOCUMENT,
        forbidden_because=_MOTIF_MARGE,
    ),
    OutboundField(
        "lines[].cost_estimate_mga",
        "Coût de revient estimé de ligne",
        CATEGORY_COMMERCIAL_DOCUMENT,
        forbidden_because=_MOTIF_COUT,
    ),
    OutboundField(
        "internal_notes",
        "Notes internes",
        CATEGORY_COMMERCIAL_DOCUMENT,
        forbidden_because=_MOTIF_NOTES_INTERNES,
    ),
)


def register_outbound_schemas() -> None:
    """Déclare les deux pièces liables de ce module.

    Appelée depuis `apps.py::ready()`, même patron que les rapports, les
    anomalies et les outils du copilote."""
    register_outbound_document(
        OutboundDocument(
            code=DOCUMENT_ORDER,
            label="Commande de vente",
            category=CATEGORY_COMMERCIAL_DOCUMENT,
            fields=(
                *_CHAMPS_COMMUNS,
                OutboundField(
                    "date_confirmed", "Date de confirmation", CATEGORY_COMMERCIAL_DOCUMENT
                ),
                OutboundField("commitment_date", "Date d'engagement", CATEGORY_COMMERCIAL_DOCUMENT),
                OutboundField(
                    "is_export",
                    "Commande à l'export",
                    CATEGORY_COMMERCIAL_DOCUMENT,
                    filterable=True,
                ),
                OutboundField(
                    "blocked_reason",
                    "Motif de blocage",
                    CATEGORY_COMMERCIAL_DOCUMENT,
                    forbidden_because=_MOTIF_BLOCAGE,
                ),
            ),
            builder=build_order,
        )
    )
    register_outbound_document(
        OutboundDocument(
            code=DOCUMENT_QUOTATION,
            label="Devis",
            category=CATEGORY_COMMERCIAL_DOCUMENT,
            fields=(
                *_CHAMPS_COMMUNS,
                OutboundField(
                    "validity_date",
                    "Date de validité",
                    CATEGORY_COMMERCIAL_DOCUMENT,
                    filterable=True,
                ),
            ),
            builder=build_quotation,
        )
    )
