"""Reapprovisionnement automatique (RG-PUR-3, §5.6.2, PU5 du
sous-sequencement `purchase` — cf. plan, section "Decisions de
sequencement et de perimetre pour ce lot").

**Stock reellement lu depuis le chantier de durcissement retroactif** :
`run_reordering` compare desormais `min_qty` a la disponibilite REELLE
(`stocks.services.public.get_available_stock_qty`, agrege sur les
emplacements INTERNES uniquement — jamais un stub, jamais un recalcul
duplique ici) plutot qu'a une constante zero. Le principe "jamais un faux
positif/negatif qui ferait perdre un vrai besoin" enonce au plan est
desormais tenu par de vraies donnees, pas seulement par l'hypothese
conservatrice "stock toujours nul" retenue avant que `stocks` n'existe :
une regle dont le stock disponible est deja au-dessus de `min_qty` ne
declenche plus de demande d'achat superflue."""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal
from uuid import UUID

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.purchase.models import PurReorderingRule, PurRequisition
from apps.purchase.services.requisitions import add_requisition_line, create_requisition
from apps.stocks.services.public import get_available_stock_qty


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
    le stock REELLEMENT disponible (`stocks.services.public.
    get_available_stock_qty(rule.variant_id)`, cf. docstring du module) a
    `min_qty`. Se declenche des que la disponibilite reelle est
    strictement inferieure a `min_qty` — sauf `min_qty <= 0` (regle
    effectivement desactivee, cas valide qu'un admin peut choisir : jamais
    un declenchement force).

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

    Quantite commandee : `max_qty - available_qty` arrondi au multiple
    superieur de `multiple_qty` (cf. `_round_up_to_multiple`) — le vrai
    besoin pour ramener le stock reel jusqu'a `max_qty`, jamais un montant
    negatif (garde defensive : une regle ne se declenche que quand
    `available_qty < min_qty <= max_qty`, donc `max_qty - available_qty`
    est arithmetiquement toujours strictement positif ici, mais la garde
    reste explicite plutot qu'implicite).

    Demandeur (`PurRequisition.requester`, FK obligatoire) : resolu comme
    le premier superutilisateur du tenant — meme repli que
    `apps.sales.services.recurrence.run_due_recurrences`/
    `run_sales_recurrences` (systeme partage entre tenants, `core.User`
    n'est pas duplique par tenant). Un tenant sans aucun superutilisateur
    renvoie une liste vide pour CE tenant (la commande de management
    ci-dessous journalise ce cas par tenant, meme discipline que
    `run_sales_recurrences`)."""
    rules = PurReorderingRule.objects.filter(tenant=tenant, is_active=True)
    triggered: list[tuple[PurReorderingRule, Decimal]] = []
    for rule in rules:
        if rule.min_qty <= 0:
            continue
        available = get_available_stock_qty(rule.variant_id)
        if available < rule.min_qty:
            triggered.append((rule, available))
    if not triggered:
        return []

    fallback_requester = User.objects.filter(is_superuser=True).order_by("id").first()
    if fallback_requester is None:
        return []

    today = timezone.now().date()
    created: list[PurRequisition] = []
    for rule, available in triggered:
        needed = max(rule.max_qty - available, Decimal(0))
        qty = _round_up_to_multiple(needed, rule.multiple_qty)
        requisition = create_requisition(
            tenant=tenant,
            requester=fallback_requester,
            date_needed=today,
            justification=_(
                "Reapprovisionnement automatique (RG-PUR-3) : stock "
                "disponible (%(available)s) sous le seuil minimum de la regle "
                "(%(min_qty)s)."
            )
            % {"available": available, "min_qty": rule.min_qty},
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
