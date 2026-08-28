"""Reservations de stock (§5.8, ST5 du sous-sequencement `stocks` — cf.
plan) : RG-STK-8 — "la quantite disponible a la vente est `qty -
qty_reserved`", jamais de sur-reservation ; liberation a l'annulation OU a
l'expiration d'un delai parametrable.

**Origine generique** : `reserve_stock` accepte un `source_object`
optionnel (une instance de modele d'une AUTRE app — typiquement
`apps.sales.models.SalesOrderLine`/`apps.mrp.models.MrpOrderComponent`,
jamais importee ici, cf. regle de couplage n°1) et resout elle-meme le
`content_type`/`object_id` via `ContentType.objects.get_for_model(...)` —
meme patron exact que `apps.purchase.services.substitution._ensure_rule`/
`request_substitute_approval`. `stocks` lui-meme n'a AUCUN moyen de savoir
quelle app a genere une reservation donnee au-dela de ce stockage generique
— aucune resolution d'affichage n'est construite ici (hors perimetre ST5,
un futur gap `stocks.services.public` pourrait exposer cette resolution
plus tard si un besoin ecran se presente)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.stocks.models import StkLocation, StkQuant, StkReservation
from apps.stocks.services.quants import available_qty

# RG-STK-8 : "la reservation est liberee ... a l'expiration du delai
# parametrable" — le CDC ne fixe aucune valeur par defaut pour ce delai.
# 30 jours retenu ici comme defaut assume (une reservation active plus
# d'un mois sans etre consommee ni annulee est raisonnablement consideree
# perimee dans un contexte ERP de gestion de commandes/production), meme
# discipline "documenter les defauts assumes" que
# `services.measurements.DEFAULT_VARIANCE_THRESHOLD_PCT`/
# `services.inventory.DEFAULT_VARIANCE_THRESHOLD_PCT` — parametrable par
# appel, jamais code en dur ailleurs.
DEFAULT_MAX_AGE_DAYS = 30


@transaction.atomic
def reserve_stock(
    *,
    tenant: Tenant,
    quant: StkQuant,
    qty: Decimal,
    date: dt.date,
    source_object: models.Model | None = None,
) -> StkReservation:
    """Cree une reservation `active` et incremente `quant.qty_reserved`.
    Refuse (`ValidationError` i18n) si `qty` depasse la quantite
    disponible (`quant.qty - quant.qty_reserved`) — RG-STK-8, jamais de
    sur-reservation. `select_for_update()` (verrou de transaction) sur le
    quant avant de lire sa disponibilite : meme discipline de
    concurrence que `services.moves._apply_quant_delta`, indispensable
    pour que deux reservations concurrentes sur le meme quant ne
    contournent pas la garde en lisant toutes deux une disponibilite
    perimee avant que l'une des deux n'ecrive."""
    quant_locked = StkQuant.objects.select_for_update().get(pk=quant.pk)
    available = quant_locked.qty - quant_locked.qty_reserved
    if qty > available:
        raise ValidationError(
            _("Quantite a reserver (%(qty)s) superieure a la quantite disponible (%(available)s).")
            % {"qty": qty, "available": available}
        )

    content_type = None
    object_id = ""
    if source_object is not None:
        content_type = ContentType.objects.get_for_model(source_object)
        object_id = str(source_object.pk)

    reservation = StkReservation.objects.create(
        tenant=tenant,
        content_type=content_type,
        object_id=object_id,
        quant=quant_locked,
        qty=qty,
        date=date,
        state=StkReservation.STATE_ACTIVE,
    )
    quant_locked.qty_reserved += qty
    quant_locked.save(update_fields=["qty_reserved"])
    return reservation


def _end_reservation(reservation: StkReservation, *, target_state: str) -> StkReservation:
    """Fonction privee partagee par `release_reservation`
    (`target_state="released"`) et `expire_stale_reservations`
    (`target_state="expired"`) — meme effet sur le quant (decrement de
    `qty_reserved`), seul l'etat final differe (RG-STK-8 distingue
    explicitement une liberation manuelle/a l'annulation d'une expiration
    automatique de delai)."""
    if reservation.state != StkReservation.STATE_ACTIVE:
        raise ValidationError(_("Seule une reservation active peut etre liberee ou expiree."))
    quant = StkQuant.objects.select_for_update().get(pk=reservation.quant_id)
    quant.qty_reserved -= reservation.qty
    quant.save(update_fields=["qty_reserved"])
    reservation.state = target_state
    reservation.save(update_fields=["state"])
    return reservation


@transaction.atomic
def release_reservation(reservation: StkReservation, *, reason: str = "") -> StkReservation:
    """`active -> released`. `reason` accepte pour symetrie d'API avec les
    autres gardes "motif" de ce depot (ex. `cancel_move`/`cancel_picking`)
    mais N'EST PAS persiste : `StkReservation` ne porte aucun champ dedie
    pour cela (le CDC §5.8 n'en liste pas) — meme precedent que
    `StkPicking.cancel_picking`, qui exige egalement un `reason` sans le
    stocker sur le document. Refuse (`ValidationError` i18n, via
    `_end_reservation`) si la reservation n'est pas `active`."""
    return _end_reservation(reservation, target_state=StkReservation.STATE_RELEASED)


@transaction.atomic
def expire_stale_reservations(
    tenant: Tenant,
    *,
    as_of: dt.date | None = None,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> int:
    """RG-STK-8 : libere (etat `expired`, distinct de `released`) toute
    reservation `active` dont `date` remonte a plus de `max_age_days`
    avant `as_of` (aujourd'hui par defaut). Renvoie le nombre de
    reservations expirees. Aucun enregistrement de cron automatique ici —
    meme discipline "pas de `Schedule` auto-cable" que
    `run_purchase_reordering`/`run_sales_recurrences` : cette fonction est
    destinee a etre invoquee par la commande de management
    `expire_stock_reservations` (ops/humain/futur planificateur), jamais
    par elle-meme."""
    as_of = as_of or timezone.now().date()
    cutoff = as_of - dt.timedelta(days=max_age_days)
    stale = StkReservation.objects.filter(
        tenant=tenant, state=StkReservation.STATE_ACTIVE, date__lte=cutoff
    )
    count = 0
    for reservation in stale:
        _end_reservation(reservation, target_state=StkReservation.STATE_EXPIRED)
        count += 1
    return count


def available_to_sell(variant_id: UUID, *, location: StkLocation | None = None) -> Decimal:
    """Delegation PURE a `services.quants.available_qty` (deja `qty -
    qty_reserved` agrege par quant, cf. sa docstring — "primitive
    consommee par RG-STK-8, aucune logique de reservation construite ici
    en ST2") : aucun recalcul duplique ici, ce ST5 ne fait
    qu'exploiter la primitive deja prevue a cet effet en ST2."""
    return available_qty(variant_id, location=location)
