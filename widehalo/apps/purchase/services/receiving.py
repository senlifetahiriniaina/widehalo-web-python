"""Reception (RG-PUR-5, §5.6.5, PU5 du sous-sequencement `purchase` — cf.
plan) : reception partielle tracee (`PurReceiptLine`, un evenement par
livraison), controle qualite conforme/non-conforme/sous-reserve, recalcul
automatique de l'etat FSM de `PurOrder` (`attempt_transition()`/`.save()`
du socle, meme discipline que `apps.purchase.services.orders` — garde-fou
architecture T7), et calcul de l'ecart reception vs commande.

Cahier des charges Phase 3 (§12.1, decision P2) : `receive_order_line`
cree desormais un VRAI mouvement de stock via `apps.stocks.services.
public.receive_purchase_line` — avant cela, cette fonction n'incrementait
que `PurOrderLine.qty_received`, sans jamais toucher `stocks`, deux
comptabilites de quantite coexistaient et divergeaient silencieusement
(constat de l'audit `docs/audit/2026-09-cahier-des-charges-v3-phase3-audit.md`,
§3.1/§3.3). `PurOrder.warehouse_id` (jusque-la une "reference opaque a un
futur entrepot", cf. `apps.purchase.models`) devient donc une precondition
REELLE de la reception : `receive_order_line` refuse desormais si aucun
entrepot valide (avec au moins un emplacement interne) n'est renseigne sur
la commande, plutot que de laisser la reception "reussir" sans effet sur
le stock physique.

Discipline `attempt_transition` (garde-fou T7, cf. `tests/architecture/
test_attempt_transition_saves_state.py`) : `_recompute_order_reception_
state` rappelle explicitement `order.save(update_fields=["state"])` juste
apres chaque `attempt_transition(...)`, jamais dans la methode `@transition`
elle-meme."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.models.user import User
from apps.core.services.workflow import attempt_transition
from apps.purchase.models import PurOrder, PurOrderLine, PurReceiptLine
from apps.stocks.services.public import receive_purchase_line as receive_stock_move

if TYPE_CHECKING:
    from apps.core.models.quality import QltChecklistTemplate, QltInspection

_VALID_QUALITY_STATUSES = {choice[0] for choice in PurReceiptLine.QUALITY_CHOICES}

# Etats depuis lesquels une reception est acceptee : `PurOrder` doit deja
# etre engagee aupres du fournisseur ET en cours d'acheminement (au moins
# `in_transit`) — rien a recevoir tant que la commande n'a pas quitte le
# fournisseur. Recevoir depuis `partially_received` couvre les livraisons
# partielles suivantes.
_RECEIVABLE_STATES = (PurOrder.STATE_IN_TRANSIT, PurOrder.STATE_PARTIALLY_RECEIVED)

# B4 (Phase 3, ACH-2 : "réception partielle... la somme des réceptions
# successives ne peut pas dépasser la quantité commandée au-delà de la
# tolérance paramétrée") : avant ce sprint, `receive_order_line` refusait
# SYSTÉMATIQUEMENT tout dépassement de `line.qty`, aussi minime soit-il
# (tolérance implicite de 0%). Le CDC ne fixe aucune valeur precise pour
# cette tolerance ("parametree") — meme discipline que
# `DEFAULT_VARIANCE_THRESHOLD_PCT` de `services/invoicing.py` (RG-PUR-6,
# egalement 2% par defaut) : un defaut assume et disclose, modifiable par
# l'appelant via `over_receipt_tolerance_pct`, jamais code en dur ailleurs
# dans ce module.
DEFAULT_OVER_RECEIPT_TOLERANCE_PCT = Decimal("2")


@transaction.atomic
def receive_order_line(
    line: PurOrderLine,
    *,
    qty_received_now: Decimal,
    quality_status: str,
    user: User,
    notes: str = "",
    photo_document_ids: list[UUID] | None = None,
    over_receipt_tolerance_pct: Decimal = DEFAULT_OVER_RECEIPT_TOLERANCE_PCT,
    lot_name: str = "",
    date_production: date | None = None,
    date_expiry: date | None = None,
    certificate_document_id: UUID | None = None,
) -> PurOrderLine:
    """Enregistre UNE reception (partielle ou totale) d'une ligne de
    commande. Refuse (`ValidationError` i18n) :
    - `qty_received_now <= 0` (rien a enregistrer) ;
    - une commande pas encore `in_transit`/`partially_received` (rien n'a
      pu etre livre avant) ;
    - un `quality_status` hors des 3 valeurs autorisees ;
    - un depassement de `line.qty` AU-DELA de la tolerance de surlivraison
      parametree (`line.qty_received + qty_received_now >
      line.qty * (1 + over_receipt_tolerance_pct / 100)`) — B4/ACH-2 :
      "tolerance de surlivraison parametrable... au lieu d'un refus
      systematique". L'ecart (meme dans la tolerance) reste toujours
      visible ligne par ligne via `order_reception_variance` ci-dessous,
      jamais masque — seul le refus stricte devient conditionnel ;
    - l'absence d'un entrepot valide (avec au moins un emplacement
      interne) sur la commande — cf. docstring de module, decision P2 :
      une reception qui ne peut pas produire de mouvement de stock reel
      est refusee plutot que silencieusement acceptee ;
    - Bloc D, D2 (QUA-8) : un article qui exige un certificat d'analyse
      (`catalog.services.public.requires_certificate_of_analysis`) sans
      `lot_name` renseigne, ou dont le lot resolu n'a aucun certificat
      rattache — leve directement par `receive_stock_move`
      (`stocks.services.public.receive_purchase_line`), propage tel quel
      a travers le `@transaction.atomic` de cette fonction (rollback
      complet, meme garantie que les refus ci-dessus).

    `@transaction.atomic` (ajoute par la decision P2) : le mouvement de
    stock, la ligne de reception et l'avancement de l'etat de la commande
    reussissent ou echouent TOUS ENSEMBLE — jamais une reception partielle
    enregistree cote `purchase` sans que le stock physique n'ait bouge.

    Recalcule ensuite automatiquement l'etat de la commande
    (`_recompute_order_reception_state`) : jamais a l'appelant de decider
    manuellement du prochain etat FSM."""
    order = line.order

    if order.state not in _RECEIVABLE_STATES:
        raise ValidationError(
            _(
                "Seule une commande en transit ou partiellement reçue peut "
                "faire l'objet d'une reception."
            )
        )
    if quality_status not in _VALID_QUALITY_STATUSES:
        raise ValidationError(_("Statut de contrôle qualité invalide."))
    if qty_received_now <= 0:
        raise ValidationError(_("La quantité reçue doit être strictement positive."))
    max_allowed_qty = line.qty * (Decimal(100) + over_receipt_tolerance_pct) / Decimal(100)
    if line.qty_received + qty_received_now > max_allowed_qty:
        raise ValidationError(
            _(
                "La quantité reçue (%(qty)s) dépasserait la quantité commandée "
                "de la ligne au-delà de la tolérance de surlivraison paramétrée "
                "(%(tolerance)s%%, RG-PUR-5/ACH-2, écart tracé jamais silencieux)."
            )
            % {"qty": line.qty, "tolerance": over_receipt_tolerance_pct}
        )

    move_id = receive_stock_move(
        tenant=order.tenant,
        variant_id=line.variant_id,
        qty=qty_received_now,
        uom=line.uom,
        warehouse_id=order.warehouse_id,
        date=date.today(),
        source_document=order.reference,
        unit_cost_mga=line.unit_price_mga,
        operator=user,
        lot_name=lot_name,
        date_production=date_production,
        date_expiry=date_expiry,
        certificate_document_id=certificate_document_id,
    )
    if move_id is None:
        raise ValidationError(
            _(
                "Impossible de réceptionner : aucun entrepôt valide (avec au "
                "moins un emplacement interne) n'est renseigné sur cette "
                "commande."
            )
        )

    PurReceiptLine.objects.create(
        tenant=order.tenant,
        order_line=line,
        qty_received=qty_received_now,
        quality_status=quality_status,
        notes=notes,
        photo_document_ids=[str(doc_id) for doc_id in (photo_document_ids or [])],
        received_by=user,
    )

    line.qty_received = line.qty_received + qty_received_now
    line.save(update_fields=["qty_received"])

    _recompute_order_reception_state(order, user)
    return line


def _recompute_order_reception_state(order: PurOrder, user: User) -> None:
    """Fait avancer `PurOrder.state` en fonction du cumul des receptions de
    TOUTES ses lignes — jamais seulement de la ligne qui vient d'etre
    receptionnee, une commande n'est `received` que quand plus AUCUNE ligne
    n'a de reliquat. Ne fait rien (pas d'exception) si l'etat courant
    couvre deja la situation (ex. deuxieme reception partielle sur une
    commande deja `partially_received`) — seule une VRAIE transition est
    tentee."""
    lines = list(order.lines.all())
    all_received = bool(lines) and all(line.qty_received >= line.qty for line in lines)
    any_received = any(line.qty_received > 0 for line in lines)

    if all_received:
        if order.state != PurOrder.STATE_RECEIVED:
            attempt_transition(order, "mark_received", user)
            order.save(update_fields=["state"])
    elif any_received and order.state == PurOrder.STATE_IN_TRANSIT:
        attempt_transition(order, "mark_partially_received", user)
        order.save(update_fields=["state"])


def _ratio_or_none(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    """Meme garde que `accounting.services.budgets._ratio_or_none`/
    `reports.py`/`landed_costs.py` (A13/A14/A17) : une ligne de commande
    jamais receptionnee (`qty_ordered == 0`, cas degenere mais possible si
    une ligne a ete ajoutee avec `qty=0`) ne doit jamais faire lever
    `ZeroDivisionError` — `variance_pct` renvoie `None` dans ce cas.
    Reimplementee ici plutot qu'importee d'`accounting` : `purchase` n'a
    aucune raison d'importer un module d'une autre app pour un garde-fou de
    3 lignes (meme discipline "reuse si importable, sinon mirror inline"
    deja actee pour les autres `_ratio_or_none` du depot)."""
    if denominator == 0:
        return None
    return numerator / denominator


def inspect_receipt(
    receipt_line: PurReceiptLine,
    *,
    template: QltChecklistTemplate,
    inspector: User,
    results: list[dict[str, Any]],
    inspected_at: datetime,
) -> QltInspection:
    """INT3 (chantier interactivite native inter-modules) : cree une
    inspection qualite generique (`core.services.quality.create_inspection`,
    QLT1-2) rattachee a UN `PurReceiptLine` precis (une reception donnee,
    jamais a la ligne de commande ni a la commande entiere — l'inspection
    porte toujours sur ce qui a ete physiquement livre CE jour-la, meme
    granularite que `PurReceiptLine` lui-meme, cf. docstring de
    `apps.purchase.models`).

    **Jamais automatique (choix assume et disclosed)** : `receive_order_line`
    ci-dessus n'appelle JAMAIS cette fonction — une inspection qualite
    formelle (gabarit + criteres notes un par un) est un acte distinct de
    la simple saisie `quality_status` (conforme/non_conforme/sous_reserve)
    deja portee par `PurReceiptLine.quality_status`, qui reste le controle
    rapide systematique. `inspect_receipt` est le point d'entree explicite
    a appeler (vue/action manuelle) quand une inspection APPROFONDIE est
    decidee pour cette reception — jamais une creation systematique sur
    CHAQUE reception, ce qui noierait le registre de `core` (meme
    discipline documentee que `apps.core.services.risk` : cibler les cas
    reels, pas chaque transition).

    `template` est fourni par l'appelant (JAMAIS cree ici a la volee, cf.
    consigne de tache) : cette fonction fonctionne avec n'importe quel
    `QltChecklistTemplate` deja existant, y compris si aucun gabarit dedie
    "reception" n'existe encore pour le tenant courant."""
    from apps.core.services.quality import create_inspection

    return create_inspection(
        tenant=receipt_line.tenant,
        template=template,
        inspector=inspector,
        results=results,
        inspected_at=inspected_at,
        content_object=receipt_line,
    )


def order_reception_variance(order: PurOrder) -> list[dict[str, Any]]:
    """RG-PUR-5 : ecart reception vs commande, PAR LIGNE — `variance` =
    `qty_received - qty_ordered` (positif = sur-receptionne, impossible en
    pratique depuis `receive_order_line` qui plafonne a `qty`, mais reste
    calcule generiquement au cas ou une ligne aurait ete modifiee apres
    coup ; negatif = reliquat non recu)."""
    rows: list[dict[str, Any]] = []
    for line in order.lines.all():
        variance = line.qty_received - line.qty
        rows.append(
            {
                "line_id": line.id,
                "variant_id": line.variant_id,
                "description": line.description,
                "qty_ordered": line.qty,
                "qty_received": line.qty_received,
                "variance": variance,
                "variance_pct": _ratio_or_none(variance, line.qty),
            }
        )
    return rows
