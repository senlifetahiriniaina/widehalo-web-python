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
from apps.mrp.models import (
    MrpBom,
    MrpBomLine,
    MrpCra,
    MrpOrder,
    MrpSupplierEvaluation,
    MrpWorkcenter,
    MrpWorkshop,
)
from apps.mrp.services.interventions import create_cri
from apps.mrp.services.orders import create_order
from apps.mrp.services.suppliers import evaluate_supplier


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


def list_closed_orders(tenant: Tenant, *, since: dt.date | None = None) -> list[dict[str, Any]]:
    """Gap identifie par le sous-sequencement ST6 de `stocks` (RG-STK-6,
    cohérence production/stock) : liste des `MrpOrder` `closed` du tenant,
    pour que `stocks` puisse iterer "quels ordres ont ete clotures
    recemment" sans jamais importer `apps.mrp.models` (regle de couplage
    n°1).

    **Fenetre temporelle** : `MrpOrder` ne porte aucun champ
    `closed_at`/`date_closed` dedie (cf. `apps.mrp.models.MrpOrder` — seuls
    `date_start`/`date_end` existent, remplis a la production, pas a la
    cloture) — `updated_at` (`BaseModel`, `auto_now=True`) est donc utilise
    comme proxy de la date de cloture : pour un ordre dont le dernier champ
    modifie est bien la transition `close()` (`STATE_DONE -> STATE_CLOSED`),
    c'est la meilleure approximation disponible sans ajouter un champ dedie
    hors perimetre de ce lot. `since` filtre donc sur `updated_at__date >=
    since` quand fourni, sinon aucune restriction (l'appelant applique sa
    propre fenetre par defaut — cf. `stocks.services.consistency`, qui
    documente son defaut de 30 jours de son cote).

    Primitives uniquement (dicts), jamais un objet `MrpOrder` — meme
    discipline que `list_supplier_evaluations`. `closed_at` du dict expose
    `updated_at.date()` sous ce nom explicite plutot que de reexposer
    `updated_at` tel quel, pour ne pas laisser croire a l'appelant qu'il
    s'agit d'un champ modele reellement nomme ainsi cote `mrp`."""
    orders = MrpOrder.objects.filter(tenant=tenant, state=MrpOrder.STATE_CLOSED)
    if since is not None:
        orders = orders.filter(updated_at__date__gte=since)
    return [
        {
            "id": order.id,
            "reference": order.reference,
            "workshop_id": order.workshop_id,
            "product_template_id": order.bom.product_template_id,
            "variant_id": order.variant_id,
            "qty_produced": order.qty_produced,
            "closed_at": order.updated_at.date(),
        }
        for order in orders.select_related("bom").order_by("updated_at")
    ]


def record_supplier_evaluation(
    *,
    tenant: Tenant,
    partner_id: Any,
    date: dt.date,
    score_quantity: Decimal,
    score_quality: Decimal,
    score_cost: Decimal,
    score_delay: Decimal,
    score_conformity: Decimal,
    weights: dict[str, int] | None = None,
    conformity_blocking: bool = False,
    notes: str = "",
) -> UUID:
    """RG-PUR-8 (mutualisation MRP-QQCD1, PU7 du sous-sequencement
    `purchase` — cf. plan) : "une seule implementation, deux points
    d'entree" — delegue entierement le calcul de `weighted_score` a
    `apps.mrp.services.suppliers.evaluate_supplier` (deja livre M6),
    jamais reimplemente ici. `component_template_id` reste `None` : une
    evaluation initiee cote `purchase` porte sur le FOURNISSEUR dans son
    ensemble, pas sur un composant `mrp` particulier (le champ est deja
    nullable sur `MrpSupplierEvaluation`, cf. sa docstring).

    `weights` : dict optionnel `{"quantity": int, "quality": int, "cost":
    int, "delay": int, "conformity": int}` — cle absente => poids par
    defaut de `MrpSupplierEvaluation` (cf. `evaluate_supplier`). Retourne
    l'UUID de l'evaluation creee (jamais l'objet `MrpSupplierEvaluation`
    lui-meme — regle de couplage n°1, `purchase` ne doit jamais manipuler
    un modele `mrp`)."""
    weights = weights or {}
    evaluation = evaluate_supplier(
        tenant=tenant,
        partner_id=partner_id,
        date=date,
        score_quantity=score_quantity,
        score_quality=score_quality,
        score_cost=score_cost,
        score_delay=score_delay,
        score_conformity=score_conformity,
        component_template_id=None,
        weight_quantity=weights.get("quantity", MrpSupplierEvaluation.DEFAULT_WEIGHT_QUANTITY),
        weight_quality=weights.get("quality", MrpSupplierEvaluation.DEFAULT_WEIGHT_QUALITY),
        weight_cost=weights.get("cost", MrpSupplierEvaluation.DEFAULT_WEIGHT_COST),
        weight_delay=weights.get("delay", MrpSupplierEvaluation.DEFAULT_WEIGHT_DELAY),
        weight_conformity=weights.get(
            "conformity", MrpSupplierEvaluation.DEFAULT_WEIGHT_CONFORMITY
        ),
        conformity_blocking=conformity_blocking,
        notes=notes,
    )
    evaluation_id: UUID = evaluation.id
    return evaluation_id


def get_supplier_score(partner_id: Any, *, since: dt.date | None = None) -> Decimal | None:
    """RG-PUR-8 : score fournisseur consolide, TOUTES evaluations confondues
    (rattachees ou non a un `component_template_id` — RG-PUR-8 evalue le
    FOURNISSEUR, contrairement a l'usage interne de `mrp` qui peut etre
    par composant).

    **Choix documente** : "la plus recente evaluation" plutot qu'une
    moyenne sur `since` — plus simple et plus defendable pour une echelle
    "calcul trimestriel" (RG-PUR-8) ou une seule evaluation est
    generalement produite par periode ; une moyenne masquerait une
    amelioration/degradation recente derriere d'anciennes notes. Si
    `since` est fourni, restreint la recherche a cette fenetre (la plus
    recente DANS cette fenetre) plutot que de moyenner — coherent avec le
    choix "plus recente" ci-dessus.

    Retourne `None`, JAMAIS une exception, si le fournisseur n'a aucune
    evaluation (dans la fenetre demandee ou globalement) — meme discipline
    "jamais de faux positif" que le reste de `mrp.services.public`.
    Ne tient JAMAIS compte de `conformity_blocking` : c'est une decision
    d'usage (bloquer un approvisionnement/une priorite) qui appartient a
    l'appelant, pas a ce getter de lecture pure."""
    queryset = MrpSupplierEvaluation.objects.filter(partner_id=partner_id)
    if since is not None:
        queryset = queryset.filter(date__gte=since)
    latest = queryset.order_by("-date", "-created_at").first()
    if latest is None:
        return None
    weighted_score: Decimal = latest.weighted_score
    return weighted_score


def list_supplier_evaluations(partner_id: Any) -> list[dict[str, Any]]:
    """Lecture pure pour `purchase` (endpoint `GET /purchase/supplier-
    evaluations`, §5.6.6) : toutes les evaluations d'un fournisseur,
    primitives uniquement (jamais un objet `MrpSupplierEvaluation` —
    regle de couplage n°1), plus recentes d'abord."""
    evaluations = MrpSupplierEvaluation.objects.filter(partner_id=partner_id).order_by(
        "-date", "-created_at"
    )
    return [
        {
            "id": evaluation.id,
            "partner_id": evaluation.partner_id,
            "component_template_id": evaluation.component_template_id,
            "date": evaluation.date,
            "score_quantity": evaluation.score_quantity,
            "score_quality": evaluation.score_quality,
            "score_cost": evaluation.score_cost,
            "score_delay": evaluation.score_delay,
            "score_conformity": evaluation.score_conformity,
            "conformity_blocking": evaluation.conformity_blocking,
            "weighted_score": evaluation.weighted_score,
            "notes": evaluation.notes,
        }
        for evaluation in evaluations
    ]


def get_employee_cra_hours(
    tenant: Tenant, user: User, *, date_from: dt.date, date_to: dt.date
) -> Decimal:
    """RG-PRS-8 : gap ajoute pour `presence.services.reconciliation`
    (rapprochement heures de presence / heures declarees en CRA). Seuls
    les CRA `validated` comptent (un CRA en brouillon/soumis/rejete n'est
    pas une declaration d'activite fiable), meme discipline que
    `services/costing.py` qui n'alimente le cout facon reel qu'a partir
    d'un CRA valide."""
    total = MrpCra.objects.filter(
        tenant=tenant,
        employee=user,
        date__gte=date_from,
        date__lte=date_to,
        state=MrpCra.STATE_VALIDATED,
    ).aggregate(total=models.Sum("hours"))["total"]
    return total if total is not None else Decimal(0)
