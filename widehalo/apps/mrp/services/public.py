"""Contrat public de l'app `mrp` — seule surface que les autres apps
metier (`patronage`, futur `sales`) ont le droit d'importer (cf.
tests/architecture/test_module_boundaries.py)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.mrp.models import MrpBom, MrpBomLine, MrpOrder, MrpWorkcenter, MrpWorkshop
from apps.mrp.services.interventions import create_cri
from apps.mrp.services.orders import create_order


def set_bom_line_qty_by_size(
    *, bom_id: Any, component_variant_id: Any, qty_by_size: dict[str, Decimal]
) -> bool:
    """RG-PAT-5 : point d'integration central pour
    `patronage.services.push_to_bom()` — alimente `qty_by_size` (RG-MRP-2)
    de la ligne de nomenclature dont le composant correspond a la matiere
    du patron. Retourne False si aucune ligne ne correspond (jamais une
    exception silencieuse deguisee en succes)."""
    bom = MrpBom.objects.get(id=bom_id)
    if bom.state == MrpBom.STATE_ACTIVE:
        raise ValidationError(
            _("Une nomenclature active est immuable — creer une nouvelle version.")
        )

    line = MrpBomLine.objects.filter(
        bom_id=bom_id, component_variant_id=component_variant_id
    ).first()
    if line is None:
        return False

    line.qty_by_size = {size: str(qty) for size, qty in qty_by_size.items()}
    line.save(update_fields=["qty_by_size"])
    return True


def open_conformity_incident(
    *,
    workcenter_id: Any,
    pattern_id: Any,
    date: dt.date,
    description: str,
    cause: str = "",
) -> UUID:
    """RG-PAT-8 : un incident de conformite constate en production ouvre un
    CRI rattache au patron d'origine, pour identifier les patrons generant
    le plus de reprises."""
    workcenter = MrpWorkcenter.objects.get(id=workcenter_id)
    cri = create_cri(
        tenant=workcenter.tenant,
        type="incident_qualite",
        workcenter=workcenter,
        date=date,
        description=description,
        cause=cause,
        pattern_id=pattern_id,
    )
    cri_id: UUID = cri.id
    return cri_id


def list_active_boms_for_product(product_template_id: Any) -> list[dict[str, Any]]:
    """PAT-ECO1 : nomenclatures actives derivees d'un produit — utilise par
    `patronage.services.eco` pour l'analyse d'impact lors d'un changement
    de version de patron."""
    boms = MrpBom.objects.filter(product_template_id=product_template_id, state=MrpBom.STATE_ACTIVE)
    return [{"id": bom.id, "code": bom.code, "version": bom.version} for bom in boms]


def create_manufacturing_order(
    *,
    tenant: Tenant,
    product_template_id: Any,
    variant_id: Any = None,
    qty: Decimal,
    requested_by: User | None = None,
) -> UUID | None:
    """RG-SAL-3 (branche "a produire", cf. plan sous-sequencement `sales`
    S3) : point d'integration appele par
    `sales.services.procurement.qualify_and_process_order` pour toute
    ligne de commande qualifiee "a produire". Ne leve jamais d'exception —
    l'appelant doit pouvoir traiter un retour `None` comme "ne peut pas
    etre produit automatiquement, necessite une intervention manuelle",
    jamais comme une erreur bloquante (meme discipline que le stub de
    faisabilite RG-CRM-7).

    Retourne `None` si aucune nomenclature active n'existe pour le produit,
    ou si le tenant ne dispose d'aucun atelier (`MrpWorkshop`) auquel
    rattacher l'ordre — dans les deux cas, aucun `MrpOrder` n'est cree.
    `requested_by` n'est pas encore trace sur `MrpOrder` (pas de champ
    dedie en modele) : reserve pour un futur enrichissement, accepte sans
    effet pour ne pas casser l'appelant si ce champ est ajoute plus tard."""
    active_boms = list_active_boms_for_product(product_template_id)
    if not active_boms:
        return None
    bom = MrpBom.objects.get(id=active_boms[0]["id"])

    # Choix du workshop par defaut (aucune notion de rattachement produit
    # <-> atelier au CDC pour ce lot) : le premier atelier non
    # sous-traitant du tenant, par ordre de creation — un tenant de
    # production reelle en a generalement peu, et un choix stable/
    # deterministe importe plus ici qu'une regle d'affectation fine
    # (differee a un futur lot si le besoin se confirme).
    workshop = (
        MrpWorkshop.objects.filter(tenant=tenant, is_subcontractor=False)
        .order_by("created_at")
        .first()
    )
    if workshop is None:
        return None

    order = create_order(tenant=tenant, bom=bom, workshop=workshop, qty=qty, variant_id=variant_id)
    order_id: UUID = order.id
    return order_id


def get_total_workshop_capacity(tenant: Tenant) -> Decimal:
    """RG-SAL-7 (composante "capacite disponible des ateliers", cf. plan
    sous-sequencement `sales` S6) : somme de `MrpWorkshop.capacity_hours_day`
    pour les ateliers non sous-traitants actifs du tenant — meme filtre
    "non sous-traitant" que `create_manufacturing_order` (un atelier
    sous-traitant n'est pas une capacite de production propre au tenant).

    C'est une capacite BRUTE en heures/jour, pas une quantite de produits
    servables : convertir des heures atelier en une quantite precise pour
    un produit donne demanderait une estimation de temps de gamme/BOM
    reelle, hors-perimetre de ce lot (cf.
    `sales.services.forecast.build_forecast`, qui expose ce nombre tel
    quel dans `parameters` pour interpretation humaine plutot que de
    fabriquer une quantite-produit precise et trompeuse).

    Retourne `Decimal(0)`, jamais une exception, quand le tenant ne
    dispose d'aucun atelier non sous-traitant (meme discipline "jamais de
    faux positif" que le reste de ce module)."""
    total = MrpWorkshop.objects.filter(tenant=tenant, is_subcontractor=False).aggregate(
        total=models.Sum("capacity_hours_day")
    )["total"]
    return total if total is not None else Decimal(0)


def get_order_produced_qty(mrp_order_id: Any) -> Decimal | None:
    """Gap identifie par le sous-sequencement S4 de `sales` (SAL-AVCT1,
    facturation a l'avancement de production) : remonte la quantite deja
    produite d'un `MrpOrder`, necessaire a
    `sales.services.invoicing.invoiceable_amount_for_line` pour calculer
    la part facturable d'une ligne en `billing_policy="on_production_progress"`.

    Source retenue : `MrpOrder.qty_produced`, le seul champ agrege deja
    tenu a jour par `mrp` (incremente a chaque cloture de composant/OF,
    cf. `apps.mrp.models.MrpOrder`) — plus fiable qu'une resommation des
    `qty_done` de `MrpWorkOrder`/`MrpOrderComponent`, qui ne couvre que le
    detail operation/composant, pas l'avancement global de l'ordre.

    Retourne `None`, jamais une exception, si l'ordre n'existe pas — meme
    discipline que le reste de ce module (`create_manufacturing_order`)."""
    order = MrpOrder.objects.filter(id=mrp_order_id).first()
    if order is None:
        return None
    qty_produced: Decimal = order.qty_produced
    return qty_produced
