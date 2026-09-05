"""Bloc F, F4 (FOR-15, §5.6.2 sous-séquencement `forecast` — cf. plan) :
alerte de péremption. "Commande planifiée sur la date limite de lot,
notification/tableau de bord" (texte du plan) : `list_expiring_lots`
(lecture pure, pour le tableau de bord) et `check_expiring_lots`
(variante NOTIFIANTE, réservée à la commande planifiée) détectent les
`StkLot` dont `date_expiry` est atteinte ou approche sous le seuil
`EXPIRY_ALERT_THRESHOLD_DAYS`, et qui portent encore un stock RÉELLEMENT
disponible.

**Conception assumée et disclosée** (aucun texte source FOR-15 plus
précis que sa paraphrase dans le plan/l'audit) :

- Seuil `EXPIRY_ALERT_THRESHOLD_DAYS = 30`, même discipline "constante
  documentée, ajustable" que `apps.purchase.services.price_watch.
  PRICE_DEVIATION_ALERT_THRESHOLD_PCT`.
- Couvre AUSSI les lots DÉJÀ périmés (`date_expiry` dans le passé) —
  "date limite de lot" (texte du plan) ne distingue pas "approche" de
  "déjà dépassée" : `days_until_expiry` est négatif pour un lot déjà
  périmé, jamais exclu pour autant (l'alerte reste pertinente : un lot
  périmé avec du stock restant est le cas le plus urgent, pas le moins).
- Rôle notifié : `magasinier` uniquement (propriétaire opérationnel du
  domaine `stocks`, cf. RBAC.md) — `apps.stocks` n'a aujourd'hui aucun
  appel `notify_role` existant (premier de ce module), et la paire
  `resp_production`/`direction` déjà utilisée par
  `apps.quality.services.alerts` (D3) est spécifique aux alertes HACCP,
  pas un gabarit générique à réappliquer ici sans justification propre.
- `list_expiring_lots`/`check_expiring_lots` sont deux fonctions
  DISTINCTES (même patron que `apps.quality.services.alerts` sépare la
  détection du côté effet de bord, mais ici séparé plus explicitement
  encore) : le tableau de bord (onglet existant "Obsolescence",
  `stocks/index.html`) appelle UNIQUEMENT `list_expiring_lots` — jamais
  la variante notifiante, pour ne pas renvoyer une notification à
  chaque chargement de page. Seule la commande planifiée
  (`run_expiry_alerts`) appelle `check_expiring_lots`.
- Jamais dédoublonnée entre deux exécutions de la commande (même
  discipline assumée que `run_price_watch_checks`/
  `check_overdue_controls`) : un lot qui reste périmant sur plusieurs
  exécutions est renotifié à chaque fois — aucune infrastructure de
  suppression de doublon ajoutée pour un sprint à 2 JT.
- Périmètre "stock réellement disponible" : au moins un `StkQuant`
  associé au lot avec `qty - qty_reserved > 0` sur un emplacement
  INTERNE (même discipline que `services.quants.available_qty`) — un
  lot épuisé ne pèse plus sur rien de physique, jamais une alerte
  fantôme. Un lot déjà tenu en quarantaine/rebut (`StkLot.is_held()`)
  est également exclu — déjà sorti du circuit, déjà sous contrôle.
- Zéro nouvel écran (budget à 240/240, zéro marge) : le résultat est
  lisible via l'onglet EXISTANT "Obsolescence" (même discipline "santé
  du stock" que le rapport de stock dormant déjà affiché là), pas un
  nouvel onglet."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.utils import timezone

from apps.core.services.notifications import notify_role_once
from apps.stocks.models import StkLocation, StkLot

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant

EXPIRY_ALERT_THRESHOLD_DAYS = 30
NOTIFICATION_ROLES = ("magasinier",)


def _remaining_qty(lot: StkLot) -> Decimal:
    total = Decimal(0)
    for quant in lot.quants.filter(location__type=StkLocation.TYPE_INTERNE):
        total += quant.qty - quant.qty_reserved
    return total


def list_expiring_lots(
    tenant: Tenant,
    *,
    today: dt.date | None = None,
    threshold_days: int = EXPIRY_ALERT_THRESHOLD_DAYS,
) -> list[dict[str, Any]]:
    """FOR-15 : lecture pure, ne notifie JAMAIS — cf. `check_expiring_lots`
    pour la variante notifiante, réservée à la commande planifiée.

    Renvoie une entrée par lot dont `date_expiry` est renseignée et
    tombe à `threshold_days` jours ou moins de `today` (passé compris),
    et qui porte encore un stock disponible réel :
    ``{"lot_id", "lot_name", "variant_id", "date_expiry",
    "days_until_expiry", "remaining_qty"}``, triée par `date_expiry`
    ascendant (le plus urgent en premier)."""
    today = today or timezone.now().date()
    threshold_date = today + dt.timedelta(days=threshold_days)

    lots = StkLot.objects.filter(
        tenant=tenant, date_expiry__isnull=False, date_expiry__lte=threshold_date
    ).order_by("date_expiry")

    results: list[dict[str, Any]] = []
    for lot in lots:
        if lot.is_held():
            continue
        remaining = _remaining_qty(lot)
        if remaining <= 0:
            continue
        # Le filtre `date_expiry__isnull=False` ci-dessus garantit deja
        # une date non nulle ici — mypy --strict ne le sait pas (champ
        # nullable au niveau modele), meme idiome que `apps.mrp.services.
        # public.list_planned_orders_workload`.
        assert lot.date_expiry is not None
        results.append(
            {
                "lot_id": lot.id,
                "lot_name": lot.name,
                "variant_id": lot.variant_id,
                "date_expiry": lot.date_expiry,
                "days_until_expiry": (lot.date_expiry - today).days,
                "remaining_qty": remaining,
            }
        )
    return results


def check_expiring_lots(
    tenant: Tenant,
    *,
    today: dt.date | None = None,
    threshold_days: int = EXPIRY_ALERT_THRESHOLD_DAYS,
) -> list[dict[str, Any]]:
    """FOR-15 : variante NOTIFIANTE de `list_expiring_lots` — réservée à
    la commande planifiée (`run_expiry_alerts`), jamais appelée depuis un
    écran. Notifie `NOTIFICATION_ROLES` (une notification par rôle et par
    lot signalé) et renvoie la même liste que `list_expiring_lots`."""
    results = list_expiring_lots(tenant, today=today, threshold_days=threshold_days)
    for row in results:
        payload = {
            "lot_id": str(row["lot_id"]),
            "lot_name": row["lot_name"],
            "variant_id": str(row["variant_id"]),
            "date_expiry": row["date_expiry"].isoformat(),
            "days_until_expiry": row["days_until_expiry"],
            "remaining_qty": str(row["remaining_qty"]),
        }
        for role_code in NOTIFICATION_ROLES:
            # L0-1 : dedoublonnee sur le lot. Un lot qui reste perimant
            # plusieurs jours produisait une notification par execution — ce
            # qui n'avait aucune consequence tant que rien n'ordonnancait
            # cette commande, et en aurait eu des le lendemain.
            notify_role_once(
                str(tenant.id),
                role_code,
                "stocks.lot_expiring",
                payload,
                dedup_keys=("lot_id",),
            )
    return results
