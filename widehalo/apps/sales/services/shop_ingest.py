"""T7 (bloc G, COM-1 à COM-4) — la commande de boutique qui entre.

**Le critère qui décide de tout** : « une commande ingérée crée un document
**au statut initial** et ne produit ni facture, ni mouvement de stock, ni
écriture, conformément à l'interdit de la section 4.4 ».

**La ligne à défendre est nette, et la mesure l'a rendue nette.**
`confirm_order` appelle `procurement.qualify_and_process_order` : confirmer
une commande PRODUIT des mouvements. L'ingestion s'arrête donc à `draft` et
ne confirme jamais — c'est un humain qui confirmera, une fois qu'il aura vu
ce qui est arrivé. C'est le même partage qu'au bloc D : le flux entrant
propose, il ne dispose pas.

**Un article inconnu ne bloque rien** (COM-2). Le lot continue, la commande
concernée porte son anomalie, et les autres entrent. C'est exactement la
leçon payée au bloc E : un chargement qui échoue en entier pour une ligne
oblige l'exploitant à trouver lui-même la ligne fautive — et, si l'échec
laisse des lignes derrière lui, à démêler des doublons au ré-essai.

**La déduplication porte sur (boutique, référence)** (COM-4), jamais sur la
seule référence : deux marchands numérotent tous deux à partir de 1, et
confondre leurs commandes en ferait disparaître une. Une contrainte de base
la rend opposable, et ce module la précède pour que le cas normal — une
boutique qui re-livre son événement faute d'avoir reçu un 2xx — soit un
résultat et non une erreur serveur.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.catalog.services.public import get_variant_id_by_ean13, get_variant_id_by_reference
from apps.core.services.sequences import next_reference
from apps.sales.models import SalesOrder, SalesOrderLine

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant

#: Le code de connecteur dont les événements entrants nous concernent. Une
#: commande arrivée sur un connecteur fiscal ou bancaire traverse le même
#: bus : sans ce filtre, `sales` tenterait de lire une commande dans une
#: charge utile qui n'en porte pas.
CONNECTOR_CODE = "boutique"


@dataclass(frozen=True)
class RejectedOrder:
    """Une commande que l'ingestion n'a pas su lire, et pourquoi.

    Distincte d'une commande EN ANOMALIE : celle-ci n'a pas pu être créée
    du tout — référence manquante, charge utile illisible. Une commande en
    anomalie, elle, existe et attend une correction."""

    external_reference: str
    reason: str


@dataclass(frozen=True)
class ShopIngestReport:
    """Ce que le lot a produit, dans les termes de COM-1 et COM-2.

    Quatre listes plutôt qu'un compte : « créées », « déjà connues »,
    « en anomalie » et « illisibles » appellent quatre gestes différents,
    et un total qui les additionnerait n'en dirait aucun."""

    created: list[SalesOrder] = field(default_factory=list)
    duplicates: list[SalesOrder] = field(default_factory=list)
    with_anomaly: list[SalesOrder] = field(default_factory=list)
    rejected: list[RejectedOrder] = field(default_factory=list)

    @property
    def produced_no_side_effect(self) -> bool:
        """COM-1 — toute commande créée l'est au STATUT INITIAL.

        La propriété que la garde d'architecture et la falsification
        interrogent : aucune commande ingérée ne sort de `draft`, donc
        aucune n'a pu déclencher la qualification d'approvisionnement, ni
        une facture, ni un mouvement de stock."""
        return all(order.state == SalesOrder.STATE_DRAFT for order in self.created)


def ingest_shop_orders(tenant: Tenant, payload: str, *, shop_code: str) -> ShopIngestReport:
    """Ingère un lot de commandes de boutique. Ne confirme rien.

    `payload` : un JSON portant `{"orders": [...]}` ou directement une
    liste. Chaque commande : `{"reference", "partner_id", "lines":
    [{"sku"|"ean13", "qty", "unit_price_mga"}]}`.

    **Réserve.** Aucune boutique réelle n'est raccordée à ce dépôt, et
    aucun contrat d'API n'y est accessible — même réserve que
    `payment_providers` pour les opérateurs mobiles. Ce qui est tenu ici
    est la STRUCTURE (une référence de boutique, des lignes désignant un
    article par sa référence ou son code-barres) ; l'adaptation à un
    contrat réel se fait dans `_parse_order` et nulle part ailleurs."""
    rapport = ShopIngestReport()
    commandes = _parse_payload(payload)
    if commandes is None:
        rapport.rejected.append(
            RejectedOrder(external_reference="", reason=str(_("Charge utile illisible.")))
        )
        return rapport

    for brute in commandes:
        reference = str(brute.get("reference") or "").strip()
        if not reference:
            # Sans référence, COM-4 est inapplicable : rien ne distinguerait
            # une re-livraison d'une commande neuve, et chaque nouvel envoi
            # créerait un doublon. Refuser la ligne est le seul choix qui ne
            # fabrique pas de fausses commandes.
            rapport.rejected.append(
                RejectedOrder(
                    external_reference="",
                    reason=str(_("Commande sans référence de boutique : non dédoublonnable.")),
                )
            )
            continue

        existante = SalesOrder.objects.filter(
            tenant=tenant, shop_code=shop_code, external_reference=reference
        ).first()
        if existante is not None:
            # COM-4 : « ne crée qu'un seul document ». Le doublon est
            # SIGNALÉ, jamais silencieusement absorbé — sans quoi la
            # boutique et nous croirions deux choses différentes.
            rapport.duplicates.append(existante)
            continue

        commande, anomalie = _create_draft_order(
            tenant, brute, shop_code=shop_code, external_reference=reference
        )
        if commande is None:
            rapport.rejected.append(
                RejectedOrder(external_reference=reference, reason=anomalie or "")
            )
            continue

        rapport.created.append(commande)
        if commande.ingestion_anomaly:
            rapport.with_anomaly.append(commande)

    return rapport


def _parse_payload(payload: str) -> list[dict[str, Any]] | None:
    """Rend la liste des commandes, ou `None` si la charge est illisible."""
    try:
        donnees = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if isinstance(donnees, dict):
        donnees = donnees.get("orders")
    if not isinstance(donnees, list):
        return None
    return [element for element in donnees if isinstance(element, dict)]


def _create_draft_order(
    tenant: Tenant, brute: dict[str, Any], *, shop_code: str, external_reference: str
) -> tuple[SalesOrder | None, str | None]:
    """Crée la commande AU STATUT INITIAL, avec ses lignes reconnues.

    **Ne passe jamais par `create_order` ni par aucune transition.**
    `create_order` est le chemin de saisie interne ; le réutiliser
    n'apporterait rien ici — l'ingestion ne calcule pas de prix, ne
    contrôle pas de crédit et ne notifie personne — et le faire ferait
    dépendre l'entrée d'un tiers de règles écrites pour un commercial
    devant son écran.

    **Une ligne dont l'article est inconnu n'est pas écrite** (COM-2) :
    elle est décrite dans l'anomalie. L'écrire avec un article nul
    produirait une commande dont le total est faux, et que quelqu'un
    finirait par confirmer."""
    lignes_brutes = brute.get("lines")
    if not isinstance(lignes_brutes, list) or not lignes_brutes:
        return None, str(_("Commande sans ligne : rien à préparer ni à facturer."))

    reconnues: list[dict[str, Any]] = []
    inconnues: list[str] = []
    for ligne in lignes_brutes:
        if not isinstance(ligne, dict):
            continue
        designation = str(ligne.get("sku") or ligne.get("ean13") or "").strip()
        variant_id = _match_variant(ligne)
        if variant_id is None:
            inconnues.append(designation or "?")
            continue
        try:
            quantite = Decimal(str(ligne.get("qty") or "0"))
            prix = Decimal(str(ligne.get("unit_price_mga") or "0"))
        except InvalidOperation:
            inconnues.append(designation or "?")
            continue
        if quantite <= 0:
            inconnues.append(designation or "?")
            continue
        reconnues.append(
            {
                "variant_id": variant_id,
                "qty": quantite,
                "unit_price": prix,
                "description": designation or str(_("Article de boutique")),
            }
        )

    partner_id = _parse_partner(brute)
    if partner_id is None:
        return None, str(
            _("Commande sans tiers identifiable : elle ne pourrait être ni livrée ni facturée.")
        )

    if not reconnues:
        return None, str(
            _("Aucun article reconnu (%(liste)s) : la commande n'a rien à porter.")
            % {"liste": ", ".join(inconnues) or "?"}
        )

    anomalie = ""
    if inconnues:
        anomalie = str(
            _(
                "Article(s) sans correspondance dans le référentiel : %(liste)s. "
                "La commande est créée sans ces lignes et doit être corrigée avant "
                "confirmation."
            )
            % {"liste": ", ".join(inconnues)}
        )

    with transaction.atomic():
        commande = SalesOrder.objects.create(
            tenant=tenant,
            # La commande porte une RÉFÉRENCE INTERNE comme toute autre :
            # la référence de boutique dit d'où elle vient, pas comment on
            # la nomme chez nous. Les confondre ferait apparaître des
            # numéros étrangers dans nos propres documents.
            reference=next_reference(tenant, "CMD", timezone.now().year),
            # `date` est la date de la commande CHEZ NOUS, à défaut de
            # celle que la boutique n'envoie pas toujours : la laisser
            # nulle est refusé par la base, et inventer une date passée
            # fausserait tout classement chronologique.
            date=_parse_date(brute),
            currency="MGA",
            # Le tiers est DÉSIGNÉ par la boutique, jamais deviné : un
            # rapprochement par nom ou par courriel confondrait deux
            # homonymes, et facturerait le mauvais client. Une commande dont
            # le tiers n'est pas résolu est refusée plus haut.
            partner_id=partner_id,
            shop_code=shop_code,
            external_reference=external_reference,
            ingestion_anomaly=anomalie,
            # **`draft`, et c'est tout le critère COM-1.** Le défaut par
            # défaut du modèle, écrit ici quand même : il dit que ce n'est
            # pas un hasard mais une décision, et une falsification qui le
            # change doit avoir une ligne à changer.
            state=SalesOrder.STATE_DRAFT,
        )
        SalesOrderLine.objects.bulk_create(
            [
                SalesOrderLine(
                    tenant=tenant,
                    order=commande,
                    sequence=(rang + 1) * 10,
                    variant_id=valeurs["variant_id"],
                    description=valeurs["description"],
                    qty=valeurs["qty"],
                    unit_price=valeurs["unit_price"],
                    # Le sous-total est calculé ICI et non laissé à zéro :
                    # une commande dont les lignes ont un prix mais un
                    # sous-total nul afficherait un total de zéro, et
                    # quelqu'un la confirmerait sans voir le montant réel.
                    subtotal=valeurs["qty"] * valeurs["unit_price"],
                )
                for rang, valeurs in enumerate(reconnues)
            ]
        )
    return commande, None


def _parse_date(brute: dict[str, Any]) -> dt.date:
    """La date de la commande : celle de la boutique si elle en donne une
    de lisible, sinon aujourd'hui.

    **Le repli est le jour courant, jamais une date inventée dans le
    passé.** Une date fausse ne se voit pas et fausse tout classement
    chronologique ; une date d'aujourd'hui sur une commande arrivée
    aujourd'hui est exacte à la journée près, ce qui est la précision que
    porte de toute façon un champ `date`."""
    brute_date = str(brute.get("date") or "").strip()
    if brute_date:
        try:
            return dt.date.fromisoformat(brute_date)
        except ValueError:
            pass
    return timezone.now().date()


def _parse_partner(brute: dict[str, Any]) -> Any:
    """Le tiers de la commande, ou `None` si la boutique n'en désigne pas.

    Passe par `parse_optional_uuid` plutôt que par une conversion nue : un
    identifiant malformé venu d'un tiers ne doit jamais remonter en 500 —
    c'est la discipline que T4bis a posée pour tout le dépôt, et une
    surface alimentée par une boutique externe est exactement là où elle
    compte."""
    from django.core.exceptions import ValidationError

    from apps.core.identifiers import parse_optional_uuid

    try:
        return parse_optional_uuid(str(brute.get("partner_id") or ""), champ="client")
    except ValidationError:
        return None


def _match_variant(ligne: dict[str, Any]) -> Any:
    """L'article interne correspondant, ou `None`.

    **Deux clefs, dans cet ordre, et aucune approximation.** La référence
    interne d'abord — c'est celle qu'un marchand recopie de notre
    catalogue —, le code-barres ensuite. Aucun rapprochement par libellé :
    « Chemise bleue L » et « chemise bleu L » désigneraient le même article
    pour un humain et deux pour une machine, et se tromper ici expédie le
    mauvais produit."""
    sku = str(ligne.get("sku") or "").strip()
    if sku:
        variant_id = get_variant_id_by_reference(sku)
        if variant_id is not None:
            return variant_id
    ean13 = str(ligne.get("ean13") or "").strip()
    if ean13:
        return get_variant_id_by_ean13(ean13)
    return None


__all__ = [
    "CONNECTOR_CODE",
    "RejectedOrder",
    "ShopIngestReport",
    "ingest_shop_orders",
]
