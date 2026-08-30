"""Orchestration de la simulation d'une ligne d'etude de faisabilite
(FEA1-3, cf. plan et `apps/feasibility/models.py`).

Patron reutilise : meme discipline "fonction pure, ne persiste que le
resultat final, pas d'effet de bord cache" que
`apps.payroll.services.projection.project_payroll_mass` — ici la seule
"persistance" est l'ecriture du resultat sur la `FeaStudyLine` elle-meme
(jamais un `MrpOrder`/document tiers cree en cascade)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.utils import timezone

from apps.core.services.sequences import next_reference
from apps.feasibility.models import FeaStudy, FeaStudyLine

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User


def create_study(
    tenant: Tenant,
    *,
    name: str,
    description: str = "",
    sector_code: str = "",
    owner: User | None = None,
    created_by: User | None = None,
) -> FeaStudy:
    """Cree une etude en brouillon — un `owner` (`core.User`) porte
    l'etude, jamais un partenaire/prospect (cf. docstring `models.py` :
    c'est precisement le point de ce chantier)."""
    reference = next_reference(tenant, "FEASTUDY", timezone.now().year)
    return FeaStudy.objects.create(
        tenant=tenant,
        reference=reference,
        name=name,
        description=description,
        sector_code=sector_code,
        owner=owner,
        created_by=created_by,
        updated_by=created_by,
    )


def add_study_line(
    study: FeaStudy,
    *,
    variant_id: UUID | None = None,
    hypothetical_spec: dict[str, Any] | None = None,
    assumed_qty: Decimal = Decimal(1),
    assumed_unit_price_mga: Decimal = Decimal(0),
    cost_breakdown: dict[str, Decimal] | None = None,
) -> FeaStudyLine:
    """Ajoute une ligne (produit reel ou hypothetique) a l'etude.
    `cost_breakdown` saisi ici est la valeur MANUELLE de depart (avant tout
    appel a `simulate_study_line` qui la remplacera si une BOM reelle est
    trouvee) — cf. docstring `resolve_cost_breakdown`."""
    return FeaStudyLine.objects.create(
        tenant=study.tenant,
        study=study,
        variant_id=variant_id,
        hypothetical_spec=hypothetical_spec or {},
        assumed_qty=assumed_qty,
        assumed_unit_price_mga=assumed_unit_price_mga,
        cost_breakdown=_serialize_cost_breakdown(cost_breakdown) if cost_breakdown else {},
    )


def _serialize_cost_breakdown(costs: dict[str, Decimal]) -> dict[str, str]:
    """Un `JSONField` ne serialise pas nativement `Decimal` sans risque de
    passer par un `float` intermediaire selon l'encodeur — memes precaution
    et convention que `mrp.services.bom::add_bom_line`/`set_bom_line_qty_
    by_size` (`qty_by_size` stocke en `str`), jamais un `float`."""
    return {key: str(value) for key, value in costs.items()}


def _deserialize_cost_breakdown(raw: dict[str, Any]) -> dict[str, Decimal]:
    return {key: Decimal(str(value)) for key, value in raw.items()}


def resolve_cost_breakdown(
    line: FeaStudyLine,
    *,
    component_unit_costs: dict[UUID, Decimal] | None = None,
    overhead_rate_pct: Decimal = Decimal(0),
) -> dict[str, Decimal]:
    """Resout le cout d'une ligne : si `line.variant_id` est renseigne ET
    qu'une nomenclature ACTIVE existe pour son produit, delegue
    ENTIEREMENT le calcul a `mrp.services.public.simulate_bom_cost` (jamais
    une reimplementation de l'arithmetique matiere/facon/frais generaux,
    cf. docstring de ce gap cote `mrp`). Sinon (etude 100% exploratoire, ou
    variante reelle sans BOM saisie) retombe sur `line.cost_breakdown` deja
    stocke, saisi manuellement par l'utilisateur — jamais une exception,
    meme discipline "jamais de faux positif" que `mrp.services.public`."""
    if line.variant_id is not None:
        from apps.catalog.services.public import get_variant_template_id
        from apps.mrp.services.public import list_active_boms_for_product, simulate_bom_cost

        template_id = get_variant_template_id(line.variant_id)
        if template_id is not None:
            active_boms = list_active_boms_for_product(template_id)
            if active_boms:
                costs = simulate_bom_cost(
                    active_boms[0]["id"],
                    line.assumed_qty,
                    component_unit_costs=component_unit_costs or {},
                    overhead_rate_pct=overhead_rate_pct,
                )
                if costs is not None:
                    return costs

    return (
        _deserialize_cost_breakdown(line.cost_breakdown)
        if line.cost_breakdown
        else {
            "material": Decimal(0),
            "labor": Decimal(0),
            "overhead": Decimal(0),
            "total": Decimal(0),
        }
    )


def resolve_unit_price(line: FeaStudyLine) -> Decimal:
    """Reutilise `catalog.services.public.get_variant_price` TEL QUEL (deja
    supporte sans partenaire, `partner_id=None`, cf. plan) quand une
    variante reelle est rattachee ET qu'aucun prix hypothetique n'a ete
    saisi manuellement (`assumed_unit_price_mga` a 0, sa valeur par
    defaut) — un prix explicitement saisi par l'utilisateur (meme sur une
    variante reelle, ex. hypothese de repositionnement tarifaire) prime
    toujours sur le prix catalogue courant. Retombe sur le prix
    hypothetique deja porte par la ligne dans tous les autres cas, jamais
    une exception (une variante reelle peut avoir ete supprimee/rattachee a
    un autre tenant depuis la creation de la ligne)."""
    if line.variant_id is not None and line.assumed_unit_price_mga == Decimal(0):
        from apps.catalog.services.public import get_variant_price

        try:
            price = get_variant_price(line.variant_id, partner_id=None)
        except Exception:  # noqa: BLE001 — variante introuvable/tenant differe
            return line.assumed_unit_price_mga
        if price is not None:
            return price
    return line.assumed_unit_price_mga


def compute_margin_pct(*, total_revenue_mga: Decimal, total_cost_mga: Decimal) -> Decimal:
    """`(prix - cout) / prix * 100` (cf. cadrage du chantier) — `prix` nul
    (aucun prix hypothetique/catalogue disponible) est traite comme "marge
    non calculable" (`Decimal(0)`), jamais une division par zero silencieuse
    ni une exception (meme discipline que `StgKeyResult.progress_pct`)."""
    if total_revenue_mga == 0:
        return Decimal(0)
    return ((total_revenue_mga - total_cost_mga) / total_revenue_mga * Decimal(100)).quantize(
        Decimal("0.01")
    )


def complete_study(study: FeaStudy) -> FeaStudy:
    """INT1 (chantier interactivite native inter-modules) : passe l'etude en
    `STATUS_COMPLETED` et publie `feasibility.study_completed`. Aucune
    fonction de transition de statut n'existait encore pour `FeaStudy`
    (contrairement a `PatPattern.state`/`SalesOrder.state`, `status` reste
    un simple `CharField` sans machine a etats `django-fsm-2` — cf.
    `models.py`) : cette fonction est le point d'entree MINIMAL manquant
    pour cabler la publication, jamais une machine a etats complete
    (hors-perimetre de ce chantier de cablage pur)."""
    study.status = FeaStudy.STATUS_COMPLETED
    study.save(update_fields=["status"])

    from apps.core.events import publish_event

    publish_event(
        "feasibility.study_completed",
        {
            "study_id": str(study.id),
            "reference": study.reference,
            "name": study.name,
            "owner_id": str(study.owner_id) if study.owner_id else None,
        },
        tenant_id=str(study.tenant_id),
    )
    return study


def simulate_study_line(
    line: FeaStudyLine,
    *,
    component_unit_costs: dict[UUID, Decimal] | None = None,
    overhead_rate_pct: Decimal = Decimal(0),
) -> FeaStudyLine:
    """Point d'entree unique de la simulation d'une ligne d'etude (FEA1-3) :
    resout le cout (BOM reelle si possible, `cost_breakdown` manuel sinon),
    resout le prix (catalogue si possible, hypothese manuelle sinon), et
    recalcule `computed_margin_pct` — le SEUL champ que cette fonction est
    autorisee a deriver (`assumed_qty`/`hypothetical_spec` restent des
    saisies humaines, jamais mutees ici)."""
    costs = resolve_cost_breakdown(
        line, component_unit_costs=component_unit_costs, overhead_rate_pct=overhead_rate_pct
    )
    unit_price = resolve_unit_price(line)
    total_cost = costs.get("total", Decimal(0))
    total_revenue = line.assumed_qty * unit_price

    line.cost_breakdown = _serialize_cost_breakdown(costs)
    line.assumed_unit_price_mga = unit_price
    line.computed_margin_pct = compute_margin_pct(
        total_revenue_mga=total_revenue, total_cost_mga=total_cost
    )
    line.save(update_fields=["cost_breakdown", "assumed_unit_price_mga", "computed_margin_pct"])
    return line
