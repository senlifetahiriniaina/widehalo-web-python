"""STK-9 (Phase 3 §7.3, sprint A6, mode dégradé terrain) : point d'entrée
unique et idempotent de la synchronisation d'une ligne de réception
scannée depuis l'écran magasinier (`templates/stocks/tw-scan.html`) — que
la ligne soit envoyée en ligne ou rejouée après une coupure réseau. Même
patron, très directement calqué, que
`apps.pos.services.orders.sync_order` (le protocole hors ligne du POS est
réutilisé, pas réinventé — cahier, « H19 »).

Chaque tentative de synchronisation (acceptée/doublon/rejetée) est
journalisée via `apps.core.services.audit.log_action` (`AuditLog`, déjà
existant, immuable en base) plutôt que par un nouveau modèle dédié à la
`apps.pos.models.PosSyncLog` : `stocks` était déjà à 290/290 modèles au
moment de ce sprint (`tests/architecture/test_budget.py::
test_model_budget_not_exceeded`), plafond qui ne se relève pas sans
décision explicite du commanditaire — réutiliser le journal d'audit
transversal est le choix qui respecte ce garde-fou plutôt que de le
contourner."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.catalog.services.public import get_variant_id_by_ean13
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.audit import log_action
from apps.stocks.models import StkLocation, StkMove
from apps.stocks.services.moves import create_move, validate_move

OUTCOME_ACCEPTED = "accepted"
OUTCOME_DUPLICATE = "duplicate"
OUTCOME_REJECTED = "rejected"

ACTION_ACCEPTED = "stocks.scan.accepted"
ACTION_DUPLICATE = "stocks.scan.duplicate"
ACTION_REJECTED = "stocks.scan.rejected"


def sync_scan_reception_line(
    tenant: Tenant,
    *,
    client_uuid: UUID,
    location_from: StkLocation,
    location_to: StkLocation,
    ean13: str,
    qty: Decimal,
    uom: str,
    date: dt.date,
    operator: User | None = None,
) -> tuple[StkMove | None, str]:
    """`client_uuid` déjà connu (`StkMove` existant) => AUCUN nouveau
    mouvement, aucun doublon (STK-9 : « produit exactement trente
    mouvements, sans doublon ni perte ») : le mouvement existant est
    retourné tel quel, un `AuditLog` "duplicate" est journalisé. Toute
    autre erreur (code-barres article inconnu, garde RG-STK-10/lot bloqué
    de `create_move`/`validate_move`...) est journalisée "rejected" AVANT
    d'être relevée telle quelle à l'appelant — c'est ce journal qui
    alimente le panneau « à traiter » de l'écran (cahier §7.3 : « la
    ligne concernée est présentée pour arbitrage plutôt qu'appliquée en
    force ou rejetée en silence »).

    **Volontairement PAS `@transaction.atomic` sur cette fonction
    elle-même** — même piège/même solution que `sync_order` (cf. son
    docstring) : seule la construction du mouvement doit être annulée en
    cas d'échec, jamais le `log_action()` de la branche `except`, qui
    doit survivre au `raise` final. Un décorateur englobant annulerait ce
    dernier avec le reste dès que l'exception se propage hors de la
    fonction.

    `unit_cost_mga=0` par défaut (une réception au scan sans clavier n'a
    pas de coût de revient saisissable dans ce sprint — rapprochement
    ultérieur avec le bon de commande, hors périmètre explicite d'A6)."""
    existing = StkMove.objects.filter(tenant=tenant, client_uuid=client_uuid).first()
    if existing is not None:
        log_action(
            ACTION_DUPLICATE,
            actor=operator,
            obj=existing,
            metadata={
                "client_uuid": str(client_uuid),
                "detail": _("Ligne déjà synchronisée, rejeu ignoré."),
            },
        )
        return existing, OUTCOME_DUPLICATE

    try:
        with transaction.atomic():
            variant_id = get_variant_id_by_ean13(ean13)
            if variant_id is None:
                raise ValidationError(
                    _("Code-barres article inconnu : %(ean13)s") % {"ean13": ean13}
                )
            move = create_move(
                tenant=tenant,
                variant_id=variant_id,
                qty=qty,
                uom=uom,
                location_from=location_from,
                location_to=location_to,
                date=date,
                move_type=StkMove.TYPE_RECEPTION,
                unit_cost_mga=Decimal(0),
                operator=operator,
                client_uuid=client_uuid,
            )
            validate_move(move)
    except ValidationError as exc:
        detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        log_action(
            ACTION_REJECTED,
            actor=operator,
            metadata={"client_uuid": str(client_uuid), "detail": detail},
        )
        raise

    log_action(
        ACTION_ACCEPTED,
        actor=operator,
        obj=move,
        metadata={"client_uuid": str(client_uuid), "detail": ""},
    )
    return move, OUTCOME_ACCEPTED
