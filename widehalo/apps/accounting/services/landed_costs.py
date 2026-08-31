"""A17 (Phase 2 `accounting`) — **ACC-IMP**, couts d'importation (landed
costs) : calculateur de repartition de frais additionnels (fret, assurance,
douane, manutention portuaire...) saisis manuellement sur un lot d'achat
importe, entre les lignes/articles de ce lot.

**Ce module ne fait explicitement toujours PAS ceci** (perimetre A17 tel
qu'acte au plan) :

- Aucune `AccMove` n'est postee ici pour materialiser l'allocation en
  comptabilite generale. Une vraie implementation debiterait, pour chaque
  article, son compte de valorisation de stock du montant alloue et
  crediterait les comptes de charge/fournisseur correspondants — hors
  perimetre A17 (le patron existe deja ailleurs, cf.
  `logistics.services.customs.close_customs_file`, qui poste une vraie
  `AccMove` via `accounting.services.public.
  create_landed_cost_batch_from_source` pour le cas particulier douanier ;
  A17 reste un calculateur/rapport autonome, jamais une ecriture postee).

**Ce qui EST reellement fait depuis le chantier de durcissement retroactif**
(`apps.stocks` existe desormais, cf. plan, §5.8) : `finalize_batch`
repercute REELLEMENT le cout alloue de chaque `AccLandedCostLine` portant
un `variant_id` sur la valorisation de stock deja receptionnee, via
`stocks.services.public.apply_landed_cost_to_valuation` — meme gap deja
consomme par `logistics.services.customs.close_customs_file` (RG-LOG-7),
desormais aussi cable depuis le cas general (non douanier) `accounting`.
Une ligne SANS `variant_id` (ex. un frais general non rattache a un
article precis) reste, elle, un pur calcul de rapport — rien a revaloriser
cote stock, ce n'est pas une erreur. `landed_cost_report` reste l'outil de
calcul/rapport (cle d'allocation, cout debarque unitaire) reutilise tel
quel pour deriver le montant a repercuter par ligne — aucune formule
d'allocation reimplementee ici. Aucune reserve OECFM/DGI necessaire ici :
ce n'est pas une reconstruction de canevas fiscal, seulement un calcul de
repartition de cout standard."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils.translation import gettext as _

from apps.accounting.models import (
    AccAccount,
    AccLandedCostBatch,
    AccLandedCostComponent,
    AccLandedCostLine,
)
from apps.core.models.tenant import Tenant
from apps.core.services.sequences import next_reference
from apps.stocks.services.public import apply_landed_cost_to_valuation


def create_landed_cost_batch(
    *,
    tenant: Tenant,
    label: str,
    date: Any,
    allocation_method: str,
    currency: str = "MGA",
) -> AccLandedCostBatch:
    """Cree un lot en `state="draft"`. Reference sequencee par tenant/annee,
    meme patron que `AccAsset`/`AccProvision` (A10)/`AccBudget` (A14)."""
    reference = next_reference(tenant, "IMP", date.year)
    return AccLandedCostBatch.objects.create(
        tenant=tenant,
        label=label,
        date=date,
        currency=currency,
        allocation_method=allocation_method,
        reference=reference,
        state=AccLandedCostBatch.STATE_DRAFT,
    )


def _recompute_total_purchase_value(batch: AccLandedCostBatch) -> None:
    total = batch.lines.aggregate(total=Sum("purchase_value_mga"))["total"] or Decimal(0)
    batch.total_purchase_value_mga = total
    batch.save(update_fields=["total_purchase_value_mga"])


def add_landed_cost_line(
    batch: AccLandedCostBatch,
    *,
    description: str,
    qty: Decimal,
    purchase_value_mga: Decimal,
    variant_id: UUID | None = None,
    weight_kg: Decimal | None = None,
) -> AccLandedCostLine:
    """Ajoute une ligne a un lot en brouillon — refuse (`ValidationError`)
    si `batch.state != "draft"`. Recalcule ensuite
    `batch.total_purchase_value_mga` (somme des `purchase_value_mga` de
    toutes les lignes du lot)."""
    if batch.state != AccLandedCostBatch.STATE_DRAFT:
        raise ValidationError(_("Impossible d'ajouter une ligne a un lot déjà finalisé."))
    line = AccLandedCostLine.objects.create(
        tenant=batch.tenant,
        batch=batch,
        description=description,
        variant_id=variant_id,
        qty=qty,
        weight_kg=weight_kg,
        purchase_value_mga=purchase_value_mga,
    )
    _recompute_total_purchase_value(batch)
    return line


def add_cost_component(
    batch: AccLandedCostBatch,
    *,
    label: str,
    amount_mga: Decimal,
    account: AccAccount | None = None,
) -> AccLandedCostComponent:
    """Ajoute un composant de cout a un lot en brouillon — refuse
    (`ValidationError`) si `batch.state != "draft"`."""
    if batch.state != AccLandedCostBatch.STATE_DRAFT:
        raise ValidationError(
            _("Impossible d'ajouter un composant de coût a un lot déjà finalisé.")
        )
    return AccLandedCostComponent.objects.create(
        tenant=batch.tenant,
        batch=batch,
        label=label,
        amount_mga=amount_mga,
        account=account,
    )


def finalize_batch(batch: AccLandedCostBatch) -> AccLandedCostBatch:
    """Transition `draft -> finalized`. Refuse une double finalisation.
    Verrouille le lot contre tout ajout ulterieur de ligne/composant (garde
    appliquee dans `add_landed_cost_line`/`add_cost_component` ci-dessus, pas
    ici) — `landed_cost_report` reste calculable dans les deux etats.

    Depuis le chantier de durcissement retroactif (cf. docstring de
    module) : repercute REELLEMENT, pour chaque `AccLandedCostLine` portant
    un `variant_id`, son `allocated_cost_mga` (calcule par
    `landed_cost_report`, aucune formule d'allocation dupliquee ici) sur la
    valorisation de stock via `stocks.services.public.
    apply_landed_cost_to_valuation` — meme garde `if additional_cost > 0`
    que `logistics.services.customs.close_customs_file`. Une ligne sans
    `variant_id`, ou dont l'allocation est `None`/nulle (division par zero
    geree en amont par `landed_cost_report`, cf. sa docstring), n'a
    simplement rien a revaloriser cote stock — jamais une erreur."""
    if batch.state != AccLandedCostBatch.STATE_DRAFT:
        raise ValidationError(_("Ce lot est déjà finalisé."))
    batch.state = AccLandedCostBatch.STATE_FINALIZED
    batch.save(update_fields=["state"])

    for row in landed_cost_report(batch):
        variant_id = row["variant_id"]
        allocated_cost = row["allocated_cost_mga"]
        if variant_id is not None and allocated_cost is not None and allocated_cost > 0:
            apply_landed_cost_to_valuation(variant_id, additional_cost_mga=allocated_cost)

    return batch


def _ratio_or_none(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    """Meme garde que `reports.py`/`budgets.py::_ratio_or_none` (A13/A14) :
    un denominateur nul (lot sans valeur d'achat, poids ou quantite totale
    nulle) ne doit jamais lever `ZeroDivisionError` — renvoie `None` plutot
    qu'une erreur applicative. Reimplementee ici plutot qu'importee : meme
    raisonnement que `budgets.py::_ratio_or_none` (fonction privee, fichiers
    `services/` independants)."""
    if denominator == 0:
        return None
    return numerator / denominator


def landed_cost_report(batch: AccLandedCostBatch) -> list[dict[str, Any]]:
    """Calcule, pour chaque `AccLandedCostLine` du lot, sa cle d'allocation
    (selon `batch.allocation_method`) et son cout debarque unitaire.

    Cles d'allocation :

    - `by_value` : part de `line.purchase_value_mga` dans
      `batch.total_purchase_value_mga`.
    - `by_weight` : part de `line.weight_kg` dans la somme des
      `weight_kg` de toutes les lignes du lot. Leve une `ValidationError`
      (i18n) explicite si UNE SEULE ligne du lot n'a pas de `weight_kg`
      renseigne alors que cette methode est selectionnee — jamais un
      defaut silencieux a 0 ni un saut de ligne, une repartition au poids
      avec une donnee manquante est fausse par construction.
    - `by_quantity` : part de `line.qty` dans la somme des `qty` de toutes
      les lignes du lot.

    Pour chaque ligne : `total_allocated_cost_mga = cle * somme des
    AccLandedCostComponent.amount_mga du lot`, puis
    `landed_unit_cost_mga = (purchase_value_mga + total_allocated_cost_mga)
    / qty`.

    Division par zero geree partout comme un cas normal, pas une erreur
    (meme discipline que `_ratio_or_none` d'A13/A14) : un denominateur nul
    (valeur totale d'achat nulle, poids total nul, quantite totale nulle, ou
    `qty` nul sur UNE ligne pour `landed_unit_cost_mga`) renvoie `None` pour
    le(s) champ(s) calcule(s) affecte(s) plutot que de lever."""
    lines = list(batch.lines.all().order_by("id"))
    total_cost = batch.cost_components.aggregate(total=Sum("amount_mga"))["total"] or Decimal(0)

    total_weight: Decimal | None = None
    if batch.allocation_method == AccLandedCostBatch.METHOD_BY_WEIGHT:
        missing = [line for line in lines if line.weight_kg is None]
        if missing:
            raise ValidationError(
                _(
                    "Répartition par poids impossible : %(count)s ligne(s) du lot "
                    "n'ont pas de poids (weight_kg) renseigne."
                )
                % {"count": len(missing)}
            )
        total_weight = sum(
            (line.weight_kg for line in lines if line.weight_kg is not None), Decimal(0)
        )

    total_qty: Decimal | None = None
    if batch.allocation_method == AccLandedCostBatch.METHOD_BY_QUANTITY:
        total_qty = sum((line.qty for line in lines), Decimal(0))

    rows: list[dict[str, Any]] = []
    for line in lines:
        if batch.allocation_method == AccLandedCostBatch.METHOD_BY_VALUE:
            allocation_key = _ratio_or_none(line.purchase_value_mga, batch.total_purchase_value_mga)
        elif batch.allocation_method == AccLandedCostBatch.METHOD_BY_WEIGHT:
            assert total_weight is not None  # garanti par la garde ci-dessus
            assert line.weight_kg is not None  # idem : verifie par la garde ci-dessus
            allocation_key = _ratio_or_none(line.weight_kg, total_weight)
        else:
            assert total_qty is not None
            allocation_key = _ratio_or_none(line.qty, total_qty)

        allocated_cost = allocation_key * total_cost if allocation_key is not None else None
        landed_total = (
            line.purchase_value_mga + allocated_cost if allocated_cost is not None else None
        )
        landed_unit_cost = (
            _ratio_or_none(landed_total, line.qty) if landed_total is not None else None
        )

        rows.append(
            {
                "description": line.description,
                "variant_id": str(line.variant_id) if line.variant_id else None,
                "qty": line.qty,
                "purchase_value_mga": line.purchase_value_mga,
                "allocation_key_pct": allocation_key,
                "allocated_cost_mga": allocated_cost,
                "landed_total_mga": landed_total,
                "landed_unit_cost_mga": landed_unit_cost,
            }
        )
    return rows
