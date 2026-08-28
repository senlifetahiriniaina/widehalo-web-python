"""Reapprovisionnement automatique (RG-PUR-3, §5.6.2, PU5 du
sous-sequencement `purchase` — cf. plan, section "Decisions de
sequencement et de perimetre pour ce lot").

**Stub honnete documente** : la comparaison "stock disponible" exigee par
le CDC n'est pas calculable (`stocks`/`logistics` n'existent pas encore
dans ce depot). `PurReorderingRule` est construite completement (min/max/
multiple/lead_time), mais `run_reordering` compare `min_qty` a
`Decimal(0)` par convention — equivalent a "aucun stock connu, toujours en
dessous du seuil". Consequence assumee : au pire une demande d'achat en
brouillon superflue est generee (jamais une commande confirmee, jamais un
oubli — c'est le sens de "jamais un faux positif/negatif qui ferait perdre
un vrai besoin" du plan). Deviation temporaire, a corriger des que
`stocks` expose un service public de stock disponible (remplacer
`_STUBBED_AVAILABLE_STOCK` par un appel a ce futur `stocks.services.
public`)."""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal
from uuid import UUID

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.purchase.models import PurReorderingRule, PurRequisition
from apps.purchase.services.requisitions import add_requisition_line, create_requisition

# cf. docstring du module : stock disponible toujours considere a zero tant
# que `stocks` n'existe pas — jamais une lecture de stock inventee.
_STUBBED_AVAILABLE_STOCK = Decimal(0)


def create_reordering_rule(
    *,
    tenant: Tenant,
    variant_id: UUID,
    min_qty: Decimal,
    max_qty: Decimal,
    multiple_qty: Decimal = Decimal(1),
    lead_time_days: int = 0,
    warehouse_id: UUID | None = None,
) -> PurReorderingRule:
    return PurReorderingRule.objects.create(
        tenant=tenant,
        variant_id=variant_id,
        warehouse_id=warehouse_id,
        min_qty=min_qty,
        max_qty=max_qty,
        multiple_qty=multiple_qty,
        lead_time_days=lead_time_days,
    )


def _round_up_to_multiple(qty: Decimal, multiple: Decimal) -> Decimal:
    """Arrondit `qty` au multiple superieur ou egal le plus proche de
    `multiple` — formule `ceil(qty / multiple) * multiple`, calculee
    entierement en `Decimal` (jamais un `float`, memes contraintes que les
    montants de ce depot) via `Decimal.to_integral_value(rounding=
    ROUND_CEILING)`. `multiple <= 0` est traite comme "pas de contrainte de
    multiple" (retourne `qty` inchangee) plutot que de lever une division
    par zero — un `multiple_qty` de 0/negatif reste un parametrage valide
    (achat a l'unite, pas de conditionnement)."""
    if multiple <= 0:
        return qty
    return (qty / multiple).to_integral_value(rounding=ROUND_CEILING) * multiple


def run_reordering(tenant: Tenant) -> list[PurRequisition]:
    """RG-PUR-3 : pour chaque `PurReorderingRule` active du tenant, compare
    le stock stube (toujours zero, cf. docstring du module) a `min_qty`. Se
    declenche des que `_STUBBED_AVAILABLE_STOCK < min_qty` — donc TOUJOURS,
    sauf `min_qty <= 0` (regle effectivement desactivee, cas valide qu'un
    admin peut choisir : jamais un declenchement force meme dans le cas
    stube).

    Chaque regle declenchee genere UNE `PurRequisition` EN BROUILLON
    UNIQUEMENT — jamais soumise/approuvee automatiquement (RG-PUR-3
    explicite : "genere des demandes d'achat en brouillon, jamais des
    commandes confirmees").

    **Regroupement (une demande par regle, jamais un regroupement
    multi-regles)** : `create_bulk_orders_from_requisitions` (PUR-BULK1,
    PU3+PU4) regroupe par fournisseur prefere de chaque ligne — mais
    `PurReorderingRule` ne porte aucun champ fournisseur (RG-PUR-3 ne
    resout pas de fournisseur, seulement un besoin quantitatif), donc
    aucune cle de regroupement metier equivalente n'existe ici. Une
    demande par regle reste l'option la plus simple ET la plus tracable :
    l'origine exacte (quelle regle a declenche quelle demande, retrouvable
    via `PurRequisition.source_document`) est immediatement lisible sans
    re-deriver un regroupement arbitraire.

    Quantite commandee : `max_qty` arrondi au multiple superieur de
    `multiple_qty` (cf. `_round_up_to_multiple`) — puisque le stock est
    toujours stube a zero, la quantite necessaire pour atteindre `max_qty`
    est `max_qty - 0 = max_qty`.

    Demandeur (`PurRequisition.requester`, FK obligatoire) : resolu comme
    le premier superutilisateur du tenant — meme repli que
    `apps.sales.services.recurrence.run_due_recurrences`/
    `run_sales_recurrences` (systeme partage entre tenants, `core.User`
    n'est pas duplique par tenant). Un tenant sans aucun superutilisateur
    renvoie une liste vide pour CE tenant (la commande de management
    ci-dessous journalise ce cas par tenant, meme discipline que
    `run_sales_recurrences`)."""
    rules = PurReorderingRule.objects.filter(tenant=tenant, is_active=True)
    triggered = [rule for rule in rules if rule.min_qty > _STUBBED_AVAILABLE_STOCK]
    if not triggered:
        return []

    fallback_requester = User.objects.filter(is_superuser=True).order_by("id").first()
    if fallback_requester is None:
        return []

    today = timezone.now().date()
    created: list[PurRequisition] = []
    for rule in triggered:
        qty = _round_up_to_multiple(rule.max_qty - _STUBBED_AVAILABLE_STOCK, rule.multiple_qty)
        requisition = create_requisition(
            tenant=tenant,
            requester=fallback_requester,
            date_needed=today,
            justification=_(
                "Reapprovisionnement automatique (RG-PUR-3) : stock "
                "disponible (stube, cf. plan) sous le seuil minimum de la regle."
            ),
            source_document=f"pur_reordering_rule:{rule.id}",
        )
        add_requisition_line(
            requisition,
            variant_id=rule.variant_id,
            description=_("Reapprovisionnement automatique"),
            qty=qty,
        )
        created.append(requisition)

    return created
