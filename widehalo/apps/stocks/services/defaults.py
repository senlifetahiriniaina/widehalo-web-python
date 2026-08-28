"""Emplacement placeholder — chantier RG-QUALIF (qualification et
identification universelle des donnees importees). Un import de mouvement
de stock qui reference un emplacement non reconnu ne doit jamais bloquer
la ligne : la materialisation immediate se rabat sur un emplacement
virtuel "Zone à qualifier" DEDIE par entrepot (distinct de l'emplacement
`STOCK-INITIAL`/`INV-ECART` deja utilises par les imports/inventaires
existants — meme discipline que `stock_import._resolve_variance_location`
: un code distinct par usage garde l'historique explicite a la lecture)."""

from __future__ import annotations

from django.utils.translation import gettext as _

from apps.stocks.models import StkLocation, StkWarehouse
from apps.stocks.services.warehouses import create_location

_UNQUALIFIED_LOCATION_CODE = "ZONE-A-QUALIFIER"


def ensure_unqualified_location(warehouse: StkWarehouse) -> StkLocation:
    """Cree, s'il n'existe pas encore, l'emplacement virtuel "Zone à
    qualifier" de cet entrepot — idempotent (un seul par entrepot),
    reutilise a chaque appel suivant sur le meme entrepot."""
    location = StkLocation.objects.filter(
        warehouse=warehouse, type=StkLocation.TYPE_INVENTAIRE, code=_UNQUALIFIED_LOCATION_CODE
    ).first()
    if location is not None:
        return location
    return create_location(
        tenant=warehouse.tenant,
        warehouse=warehouse,
        code=_UNQUALIFIED_LOCATION_CODE,
        name=str(_("Zone à qualifier")),
        type=StkLocation.TYPE_INVENTAIRE,
    )
