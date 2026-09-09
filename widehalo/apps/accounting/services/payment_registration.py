"""T5 — le dernier maillon : ce qui écoute le hub et règle la pièce.

**Ce que ce fichier ferme.** Avant lui, le chemin entrant s'arrêtait au
registre : `receive_event` écrivait un `FlwExchange` entrant, et personne
ne le lisait. Une notification de paiement authentique arrivait, était
tracée avec sa clef de corrélation et son empreinte — et rien ne se
passait. PAY-2 (« produit l'écriture d'encaissement sans intervention
comptable ») était inatteignable, non par manque de moteur mais par
absence d'auditeur.

**Pourquoi un abonné et pas un appel depuis le hub.** La docstring de
`flows.services.public` pose la règle depuis S1 : « le hub ne rappelle
jamais un module métier — il rend un résultat, et l'appelant en fait ce
qu'il veut ». Le hub PUBLIE donc `flows.inbound_received`, et c'est
`accounting` qui décide que cela le concerne. `flows` n'a pas à savoir
qu'un module de comptabilité existe. C'est le miroir exact de ce que T4 a
fait dans l'autre sens avec `accounting.invoice_validated`.

**L'abonné ne lève jamais pour un cas normal.** Le bus réessaie trois fois
avant de marquer un événement en échec. Un échange qui ne concerne pas un
encaissement, une charge utile illisible, une notification orpheline : les
trois sont l'état habituel d'une installation, et lever produirait trois
tentatives inutiles puis une trace d'échec pour un fonctionnement nominal.
C'est la leçon écrite dans `einvoice_registration`, et elle vaut ici mot
pour mot.

**Ce qu'il ne fait pas, et qui est le cœur de l'arbitrage.** Il ne décide
jamais qu'une notification « correspond probablement » à une pièce. Il
passe la référence à `receive_payment_notification`, qui écrit UNIQUEMENT
sur corrélation réussie d'une référence que nous avons nous-mêmes émise.
L'interdit l.385 vise le rapprochement heuristique ; cet abonné n'en fait
aucun.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.core.events import subscribe

logger = logging.getLogger(__name__)

#: Le code de connecteur dont les événements entrants nous concernent. Un
#: échange arrivé sur un connecteur de transporteur ou de référentiel
#: fiscal traverse le même bus : sans ce filtre, `accounting` tenterait de
#: lire un montant dans une charge utile qui n'en porte pas.
CONNECTOR_CODE = "encaissement_mobile"


def register_payment_subscribers() -> None:
    """Appelée depuis `apps.py::ready()`, même patron que les autres
    registres du module."""

    @subscribe("flows.inbound_received")
    def _on_inbound_received(event: dict[str, Any]) -> None:
        from apps.accounting.services.payment_settlement import (
            receive_payment_notification,
        )
        from apps.core.models.tenant import Tenant
        from apps.core.tenant_context import activate_tenant
        from apps.flows.services.public import (
            correlate_inbound_exchange,
            read_inbound_payload,
        )

        payload = event.get("payload") or {}
        if payload.get("connector_code") != CONNECTOR_CODE:
            return

        tenant_id = event.get("tenant_id")
        exchange_id = payload.get("exchange_id")
        if not tenant_id or not exchange_id:
            return

        tenant = Tenant.objects.filter(id=tenant_id).first()
        if tenant is None:
            # La société a pu être supprimée entre la publication et la
            # distribution. Rare, mais pas anormal — et re-lever ferait
            # réessayer trois fois quelque chose qui n'existe plus.
            return

        with activate_tenant(tenant.id):
            corps = read_inbound_payload(tenant, exchange_id=exchange_id)
            if corps is None:
                # La charge utile a pu être purgée (FLX-5) avant que le bus
                # ne distribue. L'échange reste, sa trace aussi ; il n'y a
                # simplement plus rien à lire.
                logger.info("échange entrant %s sans charge utile lisible", exchange_id)
                return

            notification = _parse(corps)
            if notification is None:
                # Une charge utile qu'on ne sait pas lire n'est pas un
                # incident du bus : c'est un tiers qui n'envoie pas ce qu'on
                # attend. Elle est journalisée et laissée là — la lever
                # ferait trois tentatives puis un échec, pour un contenu qui
                # ne changera pas au troisième essai.
                logger.warning("charge utile d'encaissement illisible (échange %s)", exchange_id)
                return

            resultat = receive_payment_notification(
                tenant,
                provider_code=notification["provider_code"],
                external_reference=notification["external_reference"],
                amount=notification["amount"],
                currency=notification["currency"],
                fee_amount=notification["fee_amount"],
                raw=corps,
            )

            if resultat.document_id:
                # **C'est ici que la lignee se referme, et nulle part
                # ailleurs.** Le hub ne lit jamais le corps d'un echange :
                # il ne peut donc pas savoir a quelle facture une
                # notification se rapporte. Nous venons de l'apprendre — par
                # une reference que nous avons nous-memes emise — et nous
                # sommes les seuls a pouvoir le lui dire. Sans cet appel,
                # `lineage()` rend la soumission et ses reessais, et jamais
                # la notification qui les a tranches : la seule des trois qui
                # dise ce que la facture est DEVENUE.
                correlate_inbound_exchange(
                    tenant,
                    exchange_id=exchange_id,
                    document_type=resultat.document_type,
                    document_id=resultat.document_id,
                )


def _parse(corps: str) -> dict[str, Any] | None:
    """Lit la charge utile d'un opérateur, ou rend `None`.

    **Aucun défaut n'est inventé.** Un montant absent rend `None` plutôt
    que zéro : un encaissement de zéro n'existe pas, et en écrire un
    laisserait une pièce comptable qui ne correspond à aucun mouvement
    d'argent. Une devise absente, en revanche, retombe sur l'ariary — c'est
    la devise de tous les opérateurs visés, et le cahier ne connaît pas de
    règlement mobile en devise.

    **Réserve.** Les noms de champs ci-dessous ne sont tirés d'aucune
    spécification réelle : ni Mvola, ni Orange Money, ni Airtel Money ne
    publient de contrat accessible à ce dépôt — `services/mobile_money.py`
    porte déjà cette réserve pour son format de relevé. Ce qui est tenu
    ici est la STRUCTURE (une référence, un montant, une commission
    éventuelle), et l'adaptation à un contrat réel se fait dans cette
    seule fonction."""
    try:
        donnees = json.loads(corps)
    except (ValueError, TypeError):
        return None
    if not isinstance(donnees, dict):
        return None

    reference = str(donnees.get("reference") or "").strip()
    montant_brut = donnees.get("amount")
    if montant_brut is None:
        return None
    try:
        montant = Decimal(str(montant_brut))
    except (InvalidOperation, ValueError):
        return None
    if montant <= 0:
        return None

    try:
        commission = Decimal(str(donnees.get("fee") or 0))
    except (InvalidOperation, ValueError):
        commission = Decimal(0)

    return {
        "provider_code": str(donnees.get("provider") or "").strip(),
        "external_reference": reference,
        "amount": montant,
        "currency": str(donnees.get("currency") or "MGA").strip().upper(),
        "fee_amount": commission,
    }


__all__ = ["CONNECTOR_CODE", "register_payment_subscribers"]
