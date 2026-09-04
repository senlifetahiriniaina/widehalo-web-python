"""Entrepots/emplacements (§5.8, ST1 du sous-sequencement `stocks` — cf.
plan) : creation de `StkWarehouse`/`StkLocation`.

`create_location` applique une contrainte metier assumee mais non
explicitement formulee par le CDC : le `parent` d'un emplacement, quand il
est fourni, doit appartenir au MEME entrepot que l'emplacement cree
(deplacer physiquement un emplacement d'un entrepot a un autre via un
changement de parent n'a pas de sens metier). Documentee ici comme
contrainte assumee plutot que silencieusement omise.

**Limite de 3 niveaux (Phase 3, sprint A2)** : le cahier definit
explicitement (glossaire, entree "Emplacement") : « Hierarchie depot ->
zone -> emplacement, a trois niveaux au plus. » Lecture retenue (3 noms,
3 niveaux) : `StkWarehouse` = niveau 1, `StkLocation` racine
(`parent=None`, "zone") = niveau 2, `StkLocation` enfant d'une zone
("emplacement") = niveau 3 — un `StkLocation` PETIT-ENFANT (dont le
parent a lui-meme deja un parent) constituerait un 4e niveau, interdit.
`create_location` refuse donc la creation si `parent.parent_id` est deja
renseigne (garde AVANT la garde "meme entrepot" ci-dessus). Aucun autre
modele arborescent du depot (`catalog.Category.parent`,
`accounting.AccAccount.parent`, tous deux cites comme precedents par le
docstring `StkLocation` dans `models.py`) n'impose de limite de
profondeur — verifie par lecture, cette garde introduit donc un nouveau
pattern plutot que de reutiliser un existant."""

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
    if parent is not None and parent.parent_id is not None:
        raise ValidationError(
            _(
                "La hiérarchie des emplacements est limitée à trois niveaux "
                "(entrepôt/zone/emplacement) — impossible de créer un emplacement "
                "sous un emplacement déjà imbriqué."
            )
        )
    if parent is not None and parent.warehouse_id != warehouse.id:
        raise ValidationError(
            _("L'emplacement parent doit appartenir au même entrepôt que l'emplacement créé.")
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
