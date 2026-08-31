"""Stock negatif (RG-STK-10, §5.8, ST7 du sous-sequencement `stocks` — cf.
plan) : "Interdit par defaut. Autorisable par exception, par produit, avec
journalisation et alerte." (CDC).

**Octroi/revocation de l'exception** : `grant_negative_stock_exception`/
`revoke_negative_stock_exception` ci-dessous administrent
`StkNegativeStockException` (cf. sa docstring dans `models.py`).

**Reactivation plutot que doublon** : `grant_negative_stock_exception`
cherche d'abord une ligne EXISTANTE pour ce `(tenant, variant_id)` via
`StkNegativeStockException.all_objects` (convention etablie de ce depot
pour interroger au-dela du filtre `TenantManager`/soft-delete par
defaut — cf. `apps.core.services.sandbox`/`apps.core.services.
tenant_export`, qui font deja ce meme `all_objects.filter(tenant=...)`).
Si une ligne active existe deja, `ValidationError` (pas de doublon
silencieux). Si une ligne REVOQUEE (soft-suprimee, `is_active=False`)
existe, elle est reactivee EN PLACE (`is_active=True`, `authorized_by`/
`reason`/`authorized_at` reecrits avec les nouvelles valeurs) plutot
qu'une seconde ligne creee — necessaire ici (contrairement a un
`get_or_create` naif) car `UniqueConstraint(tenant, variant_id)` ne porte
PAS de condition `is_active=True` (aucun precedent d'index partiel dans ce
depot, cf. docstring `models.py`) : une seconde ligne pour le meme produit
violerait cette contrainte DB, meme soft-suprimee.

**Enforcement (l'essentiel de RG-STK-10)** : `services.moves.validate_move`
(cf. son propre commentaire inline) appelle `has_negative_stock_exception`
avant d'appliquer un mouvement sortant depuis un emplacement interne
reellement possede (`_is_valuation_internal`) — jamais pour les
emplacements virtuels (`fournisseur`/`client`/etc., qui vont
LEGITIMEMENT negatif par construction du patron double-entree, cf.
docstring `StkQuant`/ST2). Si le quant source deviendrait negatif et
qu'aucune exception active n'existe, `ValidationError`. Si une exception
existe, le mouvement est autorise mais JOURNALISE
(`apps.core.services.audit.log_action`, meme convention exacte que
`apps.patronage.services.consumption.push_to_bom`) ET une ALERTE est
emise (`apps.core.services.notifications.dispatch_notification`, meme
convention exacte que `apps.sales.services.orders._notify_salesperson`) —
au `move.operator` s'il est renseigne, silencieux sinon (meme discipline
"pas de destinataire de repli invente" que `_notify_salesperson`, cf. sa
docstring — le CDC ne precise pas QUI doit recevoir l'alerte)."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.audit import log_action
from apps.core.services.notifications import dispatch_notification
from apps.stocks.models import StkMove, StkNegativeStockException

AUDIT_ACTION_GRANTED = "stocks.negative_stock.used"  # <=32 chars (AuditLog.action)
NOTIFICATION_TYPE = "stocks.negative_stock_used"


def grant_negative_stock_exception(
    *, tenant: Tenant, variant_id: Any, authorized_by: User, reason: str
) -> StkNegativeStockException:
    """Cree (ou reactive, cf. docstring de module) l'exception au stock
    negatif pour `variant_id`. Refuse si une exception ACTIVE existe deja
    pour ce produit (pas de doublon silencieux, pas de "re-octroi"
    implicite — un appelant qui veut simplement changer le motif d'une
    exception deja active doit d'abord la revoquer, ou cet appel echoue
    volontairement plutot que de reecrire silencieusement une ligne deja
    en vigueur)."""
    existing = StkNegativeStockException.all_objects.filter(
        tenant=tenant, variant_id=variant_id
    ).first()
    if existing is not None and existing.is_active:
        raise ValidationError(_("Une exception de stock négatif est déjà active pour ce produit."))
    if existing is not None:
        existing.is_active = True
        existing.archived_at = None
        existing.authorized_by = authorized_by
        existing.reason = reason
        existing.authorized_at = timezone.now()
        existing.save(
            update_fields=[
                "is_active",
                "archived_at",
                "authorized_by",
                "reason",
                "authorized_at",
            ]
        )
        return existing
    return StkNegativeStockException.objects.create(
        tenant=tenant,
        variant_id=variant_id,
        authorized_by=authorized_by,
        reason=reason,
    )


def revoke_negative_stock_exception(
    exception: StkNegativeStockException, *, reason: str = ""
) -> None:
    """Revoque (soft-delete, `BaseModel.soft_delete`) une exception —
    `reason` est purement documentaire ici (le motif d'OCTROI reste sur
    `exception.reason`, jamais ecrase par le motif de revocation) : cf.
    discipline `PurSubstitute`/ST7, aucun champ dedie n'est prevu pour un
    motif de revocation distinct dans le perimetre CDC de cette entite."""
    exception.soft_delete()


def has_negative_stock_exception(variant_id: Any) -> bool:
    """Lecture simple : une exception ACTIVE existe-t-elle pour ce produit,
    dans le tenant courant (`StkNegativeStockException.objects`, filtre
    tenant implicite du `TenantManager` — jamais `all_objects` ici, seule
    une exception EN VIGUEUR compte pour l'enforcement)."""
    return StkNegativeStockException.objects.filter(variant_id=variant_id, is_active=True).exists()


def _journalize_and_alert(move: StkMove) -> None:
    """Journalisation + alerte RG-STK-10 ("avec journalisation et
    alerte", CDC) — appelee par `services.moves.validate_move` UNIQUEMENT
    quand un mouvement sortant interne qui ferait passer un quant negatif
    est effectivement AUTORISE par une exception active (jamais quand le
    mouvement est refuse, ni quand il n'y a pas de risque de negatif)."""
    log_action(
        AUDIT_ACTION_GRANTED,
        actor=move.operator,
        obj=move,
        metadata={
            "variant_id": str(move.variant_id),
            "location_from_id": str(move.location_from_id),
            "qty": str(move.qty),
        },
    )
    if move.operator is None:
        return
    dispatch_notification(
        user=move.operator,
        notification_type=NOTIFICATION_TYPE,
        payload={
            "move_id": str(move.id),
            "reference": move.reference,
            "variant_id": str(move.variant_id),
            "location_from_id": str(move.location_from_id),
            "qty": str(move.qty),
        },
        tenant_id=str(move.tenant_id),
    )
