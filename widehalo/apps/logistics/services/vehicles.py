"""LOG1 : creation vehicule/document/cout, alertes d'expiration de document
(RG-LOG-1). `upcoming_document_alerts()` est un simple callable synchrone
(pas d'enregistrement cron automatique) invoque par une future commande de
management (LOG7) — meme discipline que `run_sales_recurrences`/
`run_purchase_reordering` : jamais de planification automatique implicite
dans ce lot, un humain/ops declenche."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.services.notifications import dispatch_notification
from apps.logistics.models import LogDriver, LogVehicle, LogVehicleCost, LogVehicleDocument

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User


def create_vehicle(
    tenant: Tenant,
    *,
    plate_number: str,
    type: str = LogVehicle.TYPE_TRUCK,
    capacity_kg: Decimal | None = None,
    capacity_m3: Decimal | None = None,
) -> LogVehicle:
    vehicle = LogVehicle(
        tenant=tenant,
        plate_number=plate_number,
        type=type,
        capacity_kg=capacity_kg,
        capacity_m3=capacity_m3,
    )
    vehicle.full_clean()
    vehicle.save()
    return vehicle


def add_vehicle_document(
    vehicle: LogVehicle,
    *,
    doc_type: str,
    reference: str = "",
    issue_date: dt.date | None = None,
    expiry_date: dt.date | None = None,
    alert_days_before: int = 30,
) -> LogVehicleDocument:
    document = LogVehicleDocument(
        tenant=vehicle.tenant,
        vehicle=vehicle,
        doc_type=doc_type,
        reference=reference,
        issue_date=issue_date,
        expiry_date=expiry_date,
        alert_days_before=alert_days_before,
    )
    document.full_clean()
    document.save()
    return document


def record_vehicle_cost(
    vehicle: LogVehicle,
    *,
    date: dt.date,
    cost_type: str,
    amount_mga: Decimal,
    odometer_km: Decimal | None = None,
    note: str = "",
) -> LogVehicleCost:
    if amount_mga <= 0:
        raise ValidationError(_("Le montant d'un coût véhicule doit être strictement positif."))
    cost = LogVehicleCost(
        tenant=vehicle.tenant,
        vehicle=vehicle,
        date=date,
        cost_type=cost_type,
        amount_mga=amount_mga,
        odometer_km=odometer_km,
        note=note,
    )
    cost.full_clean()
    cost.save()
    if odometer_km is not None and odometer_km > vehicle.odometer_km:
        vehicle.odometer_km = odometer_km
        vehicle.save(update_fields=["odometer_km"])
    return cost


def create_driver(
    tenant: Tenant,
    *,
    name: str,
    phone: str = "",
    license_number: str = "",
    license_expiry: dt.date | None = None,
    user: User | None = None,
    consent_geolocation: bool = False,
) -> LogDriver:
    driver = LogDriver(
        tenant=tenant,
        name=name,
        phone=phone,
        license_number=license_number,
        license_expiry=license_expiry,
        user=user,
        consent_geolocation=consent_geolocation,
    )
    driver.full_clean()
    driver.save()
    return driver


def upcoming_document_alerts(tenant: Tenant, *, within_days: int = 30) -> list[LogVehicleDocument]:
    """RG-LOG-1 : documents dont l'echeance tombe dans `within_days` jours
    (ou est deja depassee), non deja notifies. Ne notifie PAS elle-meme —
    renvoie la liste, laissant l'appelant (commande de management LOG7)
    decider du canal/destinataire et appeler `mark_alert_notified`."""
    today = timezone.localdate()
    horizon = today + dt.timedelta(days=within_days)
    return list(
        LogVehicleDocument.objects.filter(
            tenant=tenant,
            expiry_date__isnull=False,
            expiry_date__lte=horizon,
            notified_at__isnull=True,
        ).order_by("expiry_date")
    )


def notify_document_alert(document: LogVehicleDocument, *, recipient: User) -> None:
    """Envoie l'alerte (canal notification generique du socle, Lot 1 etape
    11) et marque le document comme notifie — jamais renvoyee deux fois
    pour la meme echeance."""
    dispatch_notification(
        recipient,
        "logistics.vehicle_document_expiring",
        {
            "vehicle_plate_number": document.vehicle.plate_number,
            "doc_type": document.doc_type,
            "expiry_date": document.expiry_date.isoformat() if document.expiry_date else None,
        },
        tenant_id=str(document.tenant_id),
    )
    document.notified_at = timezone.now()
    document.save(update_fields=["notified_at"])
