"""Entrepots/emplacements (§5.8, ST1 du sous-sequencement `stocks` — cf.
plan) : creation de `StkWarehouse`/`StkLocation`.

`create_location` applique une contrainte metier assumee mais non
explicitement formulee par le CDC : le `parent` d'un emplacement, quand il
est fourni, doit appartenir au MEME entrepot que l'emplacement cree
(deplacer physiquement un emplacement d'un entrepot a un autre via un
changement de parent n'a pas de sens metier). Documentee ici comme
contrainte assumee plutot que silencieusement omise."""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.stocks.models import StkLocation, StkWarehouse


def create_warehouse(
    *,
    tenant: Tenant,
    code: str,
    name: str,
    type: str = StkWarehouse.TYPE_PRINCIPAL,  # noqa: A002 (nom aligne sur le champ modele/CDC)
    address: str = "",
    manager: User | None = None,
) -> StkWarehouse:
    return StkWarehouse.objects.create(
        tenant=tenant,
        code=code,
        name=name,
        type=type,
        address=address,
        manager=manager,
    )


def create_location(
    *,
    tenant: Tenant,
    warehouse: StkWarehouse,
    code: str,
    name: str,
    type: str = StkLocation.TYPE_INTERNE,  # noqa: A002 (nom aligne sur le champ modele/CDC)
    parent: StkLocation | None = None,
    is_scrap: bool = False,
    capacity: Decimal | None = None,
    barcode: str = "",
) -> StkLocation:
    if parent is not None and parent.warehouse_id != warehouse.id:
        raise ValidationError(
            _("L'emplacement parent doit appartenir au meme entrepot que l'emplacement cree.")
        )
    return StkLocation.objects.create(
        tenant=tenant,
        warehouse=warehouse,
        code=code,
        name=name,
        type=type,
        parent=parent,
        is_scrap=is_scrap,
        capacity=capacity,
        barcode=barcode,
    )
