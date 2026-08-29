"""Contrat public de `logistics` — seule surface que les autres apps
metier ont le droit d'importer (cf. tests/architecture/test_module_boundaries.py).

Vide au demarrage du module (LOG1), comme `sales.services.public`/
`purchase.services.public` l'etaient a leur premiere etape. Premier gap
reellement expose, ajoute pour FIN3 de `financing` (cf. plan) :
`get_shipment_reference`, necessaire pour afficher une reference lisible
sur `FinCredoc.log_shipment_id` (UUID nu, jamais de FK Django, regle de
couplage n°1) — meme patron que `purchase.services.public.
get_order_reference`."""

from __future__ import annotations

from typing import Any

from apps.logistics.models import LogShipment


def get_shipment_reference(shipment_id: Any) -> str:
    """Retourne une chaine vide, jamais une exception, si l'expedition
    n'existe pas — meme discipline que `purchase.services.public.
    get_order_reference`."""
    shipment = LogShipment.objects.filter(id=shipment_id).first()
    return shipment.reference if shipment is not None else ""
