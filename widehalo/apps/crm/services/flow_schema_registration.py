"""T0 (§9.2, ligne « Identité et coordonnées de client ») — la minimisation,
rendue mécanique.

La règle citée, mot pour mot : « **Minimisation obligatoire : seuls les
champs exigés par l'opération partent.** La correspondance de champs ne
peut pas ajouter un champ non déclaré nécessaire. »

C'est la seule des trois règles de champ du §9.2 qui ne se satisfait pas
d'une liste blanche : elle exige que chaque champ dise *par quelle
opération* il est exigé. Un numéro de téléphone est nécessaire pour
initier un mouvement d'argent vers un portefeuille de monnaie
électronique (OP5) et pour en recevoir la notification (OP7) ; il n'a
aucun objet dans une soumission fiscale (OP4) ou une publication de jeu de
données (OP2). Sans cette distinction, « minimisation » resterait un mot :
la liaison e-facture emporterait le téléphone du client parce qu'il se
trouvait dans la fiche.

**Ce que ce module ne déclare PAS, et c'est le point.** L'espérance de
revenu, la probabilité, le motif de perte et la description sont des
appréciations internes sur un tiers — le §9.2 les range dans les
« commentaires de gestion » de la ligne précédente, et ils ne sortent
d'aucune fiche. Ils sont déclarés INTERDITS plutôt qu'omis, pour que la
garde puisse les nommer.

**Trois champs décoratifs cessent de l'être.** `source`, `campaign` et
`priority` étaient écrits par les écrans et lus par personne en
production. Les déclarer ici leur donne leur premier lecteur : ce sont
exactement les champs qu'une liaison vers un outil de prospection
demande.
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

DOCUMENT_LEAD = "crm.CrmLead"

#: Remettre la pièce ou le message au tiers lui-même : pousser un document
#: (OP1) ou déposer un fichier à son intention (OP3).
OPERATIONS_DE_REMISE = frozenset({"OP1", "OP3"})
#: Mouvement d'argent (OP5) et notification reçue en retour (OP7) : les
#: deux seules opérations où un numéro de téléphone est le SUJET de
#: l'échange et non un ornement de la fiche.
OPERATIONS_DE_PAIEMENT = frozenset({"OP5", "OP7"})
#: Interroger un référentiel (OP8) : l'opération qui existe précisément
#: pour vérifier une identité déclarée (§4.1, et T3 pour l'identifiant
#: fiscal).
OPERATIONS_DE_REFERENTIEL = frozenset({"OP8"})

_MOTIF_ESPERANCE = (
    "espérance de revenu — appréciation interne portée SUR le tiers, jamais "
    "un fait le concernant : la transmettre lui apprendrait ce que "
    "l'entreprise pense pouvoir lui vendre"
)
_MOTIF_PROBABILITE = (
    "probabilité de conclusion — appréciation interne portée sur le tiers au "
    "même titre que l'espérance de revenu, et tout aussi indéfendable à lui "
    "transmettre"
)
_MOTIF_PERTE = (
    "motif de perte — commentaire de gestion au sens du §9.2, rédigé par un "
    "commercial pour sa hiérarchie, souvent nominatif et souvent peu "
    "flatteur pour le tiers concerné"
)
_MOTIF_DESCRIPTION = (
    "description libre de l'affaire — commentaire de gestion au sens du "
    "§9.2 : champ de texte libre alimenté par les commerciaux, dont le "
    "contenu n'est ni contrôlé ni destiné au tiers"
)


def build_lead(object_id: UUID) -> dict[str, Any] | None:
    from apps.crm.models import CrmLead

    piste = CrmLead.objects.filter(id=object_id).select_related("stage").first()
    if piste is None:
        return None
    return {
        "reference": piste.reference,
        "name": piste.name,
        "partner_id": str(piste.partner_id) if piste.partner_id else "",
        "contact_name": piste.contact_name,
        "email": piste.email,
        "phone": piste.phone,
        "source": piste.source,
        "campaign": piste.campaign,
        "priority": piste.priority,
        "stage_code": piste.stage.code if piste.stage_id else "",
        "expected_close_date": piste.expected_close_date,
    }


def register_outbound_schemas() -> None:
    """Déclare la fiche de piste, champ par champ et opération par
    opération.

    Appelée depuis `apps.py::ready()`, même patron que les rapports, les
    règles d'automatisation et les gardes de chatter de ce module."""
    register_outbound_document(
        OutboundDocument(
            code=DOCUMENT_LEAD,
            label="Piste / opportunité",
            category=CATEGORY_PARTY_IDENTITY,
            fields=(
                OutboundField(
                    "reference",
                    "Référence de la piste",
                    CATEGORY_PARTY_IDENTITY,
                    required_by=ALL_OPERATIONS,
                ),
                OutboundField(
                    "name",
                    "Intitulé de la piste",
                    CATEGORY_PARTY_IDENTITY,
                    required_by=ALL_OPERATIONS,
                ),
                OutboundField(
                    "partner_id",
                    "Identifiant du tiers",
                    CATEGORY_PARTY_IDENTITY,
                    required_by=ALL_OPERATIONS,
                    filterable=True,
                ),
                OutboundField(
                    "contact_name",
                    "Nom du contact",
                    CATEGORY_PARTY_IDENTITY,
                    required_by=OPERATIONS_DE_REMISE | OPERATIONS_DE_REFERENTIEL,
                ),
                OutboundField(
                    "email",
                    "Courriel du contact",
                    CATEGORY_PARTY_IDENTITY,
                    required_by=OPERATIONS_DE_REMISE,
                ),
                OutboundField(
                    "phone",
                    "Téléphone du contact",
                    CATEGORY_PARTY_IDENTITY,
                    required_by=OPERATIONS_DE_PAIEMENT | OPERATIONS_DE_REMISE,
                ),
                OutboundField(
                    "source",
                    "Origine de la piste",
                    CATEGORY_COMMERCIAL_DOCUMENT,
                    filterable=True,
                ),
                OutboundField(
                    "campaign",
                    "Campagne d'origine",
                    CATEGORY_COMMERCIAL_DOCUMENT,
                    filterable=True,
                ),
                OutboundField(
                    "priority", "Priorité", CATEGORY_COMMERCIAL_DOCUMENT, filterable=True
                ),
                OutboundField(
                    "stage_code", "Étape du tunnel", CATEGORY_COMMERCIAL_DOCUMENT, filterable=True
                ),
                OutboundField(
                    "expected_close_date",
                    "Date de conclusion attendue",
                    CATEGORY_COMMERCIAL_DOCUMENT,
                ),
                OutboundField(
                    "expected_revenue_mga",
                    "Espérance de revenu",
                    CATEGORY_COMMERCIAL_DOCUMENT,
                    forbidden_because=_MOTIF_ESPERANCE,
                ),
                OutboundField(
                    "probability",
                    "Probabilité de conclusion",
                    CATEGORY_COMMERCIAL_DOCUMENT,
                    forbidden_because=_MOTIF_PROBABILITE,
                ),
                OutboundField(
                    "lost_comment",
                    "Commentaire de perte",
                    CATEGORY_COMMERCIAL_DOCUMENT,
                    forbidden_because=_MOTIF_PERTE,
                ),
                OutboundField(
                    "description",
                    "Description de l'affaire",
                    CATEGORY_COMMERCIAL_DOCUMENT,
                    forbidden_because=_MOTIF_DESCRIPTION,
                ),
            ),
            builder=build_lead,
        )
    )
