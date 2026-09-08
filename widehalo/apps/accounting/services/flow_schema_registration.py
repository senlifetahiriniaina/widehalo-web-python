"""T0 (§9.2, ligne « Montant et référence de règlement ») — ce qu'une
écriture laisse sortir, et le numéro de compte qui n'en sort pas.

La règle citée, mot pour mot : « Sortie autorisée. **Aucun numéro de compte
complet dans une trace ou une charge utile archivée.** »

La phrase vise deux objets à la fois dans ce module, et les deux sont
tenus ici :

1. **Le compte du plan comptable.** `AccAccount.code` est le numéro
   complet — `411100`, `512300`. Il ne sort jamais : la projection émet la
   **classe** PCG (`4`, `5`), qui suffit à un tiers pour savoir s'il
   regarde un compte de tiers ou de trésorerie, et n'apprend rien de
   l'organisation comptable interne du client.
2. **Le compte bancaire.** Le dépôt a déjà tranché dans le même sens et
   avant ce lot : `AccJournal.bank_account_prefix` porte un PRÉFIXE, pas un
   numéro. La déclaration ci-dessous ne fait que refuser explicitement ce
   qui n'existe pas encore en colonne, pour que le jour où un numéro
   complet apparaîtra, il se heurte à un refus nommé plutôt qu'au silence.

**Pourquoi la classe et pas le code tronqué.** Tronquer laisse fuir : sur
un plan comptable normalisé, les trois premiers chiffres d'un compte de
tiers désignent souvent le tiers lui-même. La classe est un seul chiffre,
définie par le PCG 2005, et elle est déjà une colonne du modèle
(`AccAccount.account_class`) — on ne dérive rien, on lit ce qui existe.

**Le domaine Paie n'apparaît nulle part ici, et c'est délibéré.** Le §9.2
lui oppose une « interdiction absolue », avec une seule exception :
l'ordre de virement, « qui expose un montant et un bénéficiaire sans aucun
élément de rubrique ». Cette exception, quand elle sera livrée (bloc E,
BNK-4), sera un document DE CE MODULE — un ordre de virement, pas un
bulletin — de sorte que l'interdiction sur `payroll.*` reste absolue et
vérifiable telle quelle en intégration continue.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.core.services.outbound_schemas import (
    ALL_OPERATIONS,
    CATEGORY_COMMERCIAL_DOCUMENT,
    CATEGORY_PARTY_IDENTITY,
    CATEGORY_SETTLEMENT,
    OutboundDocument,
    OutboundField,
    register_outbound_document,
)

DOCUMENT_MOVE = "accounting.AccMove"

_MOTIF_NUMERO_DE_COMPTE = (
    "numéro de compte complet — le §9.2 l'interdit dans toute trace et toute "
    "charge utile archivée ; seule la classe PCG sort (`lines[].account_class`), "
    "qui dit la nature du compte sans révéler le plan comptable du client"
)
_MOTIF_COMPTE_BANCAIRE = (
    "numéro de compte bancaire complet — même interdit du §9.2 que le compte "
    "du plan comptable, et de conséquence plus lourde : un relevé d'identité "
    "bancaire complet permet un prélèvement"
)
_MOTIF_ANALYTIQUE = (
    "distribution analytique — découpage de gestion interne (centres de coût, "
    "projets) au sens des « commentaires de gestion » du §9.2 : il décrit "
    "l'organisation du client, pas la pièce"
)
_MOTIF_LETTRAGE = (
    "numéro de lettrage — clef de rapprochement interne appartenant au "
    "registre de preuve du §9.2, dont la ligne dit qu'il n'est « jamais "
    "transmis à un tiers dans le cadre d'une liaison »"
)


def build_move(object_id: UUID) -> dict[str, Any] | None:
    from apps.accounting.models import AccMove

    ecriture = (
        AccMove.objects.filter(id=object_id)
        .select_related("journal")
        .prefetch_related("lines__account")
        .first()
    )
    if ecriture is None:
        return None
    return {
        "reference": ecriture.reference,
        "date": ecriture.date,
        "move_type": ecriture.move_type,
        "state": ecriture.state,
        "invoice_state": ecriture.invoice_state,
        "currency": ecriture.currency,
        "exchange_rate": ecriture.exchange_rate,
        "total_debit": ecriture.total_debit,
        "total_credit": ecriture.total_credit,
        "narration": ecriture.narration,
        "partner_id": str(ecriture.partner_id) if ecriture.partner_id else "",
        "lines": [
            {
                # La CLASSE, jamais le code : cf. docstring de module.
                "account_class": str(ligne.account.account_class),
                "label": ligne.label,
                "debit": ligne.debit,
                "credit": ligne.credit,
                "currency": ligne.currency,
                "amount_currency": ligne.amount_currency,
                "tax_base": ligne.tax_base,
                "due_date": ligne.due_date,
            }
            for ligne in ecriture.lines.order_by("created_at")
        ],
    }


def register_outbound_schemas() -> None:
    """Déclare l'écriture comptable comme pièce liable.

    Appelée depuis `apps.py::ready()`, même patron que les rapports, le
    contexte IA et les contrôles d'anomalie de ce module."""
    register_outbound_document(
        OutboundDocument(
            code=DOCUMENT_MOVE,
            label="Écriture comptable (facture incluse)",
            category=CATEGORY_COMMERCIAL_DOCUMENT,
            fields=(
                OutboundField("reference", "Numéro de pièce", CATEGORY_COMMERCIAL_DOCUMENT),
                OutboundField(
                    "date", "Date de l'écriture", CATEGORY_COMMERCIAL_DOCUMENT, filterable=True
                ),
                OutboundField(
                    "move_type", "Nature de la pièce", CATEGORY_COMMERCIAL_DOCUMENT, filterable=True
                ),
                OutboundField(
                    "state", "État comptable", CATEGORY_COMMERCIAL_DOCUMENT, filterable=True
                ),
                OutboundField(
                    "invoice_state",
                    "État de règlement",
                    CATEGORY_COMMERCIAL_DOCUMENT,
                    filterable=True,
                ),
                OutboundField("currency", "Devise", CATEGORY_SETTLEMENT, filterable=True),
                OutboundField("exchange_rate", "Cours de change", CATEGORY_SETTLEMENT),
                OutboundField("total_debit", "Total débit", CATEGORY_SETTLEMENT),
                OutboundField("total_credit", "Total crédit", CATEGORY_SETTLEMENT),
                OutboundField(
                    "narration", "Libellé porté sur la pièce", CATEGORY_COMMERCIAL_DOCUMENT
                ),
                OutboundField(
                    "partner_id",
                    "Identifiant du tiers",
                    CATEGORY_PARTY_IDENTITY,
                    required_by=ALL_OPERATIONS,
                    filterable=True,
                ),
                OutboundField("lines[].account_class", "Classe PCG du compte", CATEGORY_SETTLEMENT),
                OutboundField("lines[].label", "Libellé de ligne", CATEGORY_COMMERCIAL_DOCUMENT),
                OutboundField("lines[].debit", "Débit", CATEGORY_SETTLEMENT),
                OutboundField("lines[].credit", "Crédit", CATEGORY_SETTLEMENT),
                OutboundField("lines[].currency", "Devise de ligne", CATEGORY_SETTLEMENT),
                OutboundField("lines[].amount_currency", "Montant en devise", CATEGORY_SETTLEMENT),
                OutboundField("lines[].tax_base", "Base taxable", CATEGORY_SETTLEMENT),
                OutboundField("lines[].due_date", "Échéance", CATEGORY_SETTLEMENT),
                OutboundField(
                    "lines[].account_code",
                    "Numéro de compte du plan comptable",
                    CATEGORY_SETTLEMENT,
                    forbidden_because=_MOTIF_NUMERO_DE_COMPTE,
                ),
                OutboundField(
                    "bank_account_number",
                    "Numéro de compte bancaire",
                    CATEGORY_SETTLEMENT,
                    forbidden_because=_MOTIF_COMPTE_BANCAIRE,
                ),
                OutboundField(
                    "lines[].analytic_distribution",
                    "Distribution analytique",
                    CATEGORY_COMMERCIAL_DOCUMENT,
                    forbidden_because=_MOTIF_ANALYTIQUE,
                ),
                OutboundField(
                    "lines[].matching_number",
                    "Numéro de lettrage",
                    CATEGORY_COMMERCIAL_DOCUMENT,
                    forbidden_because=_MOTIF_LETTRAGE,
                ),
            ),
            builder=build_move,
        )
    )
