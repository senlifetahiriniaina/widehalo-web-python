"""Commande d'achat (§5.6.4, PU3+PU4 du sous-sequencement `purchase` — cf.
plan) : creation directe, depuis une/plusieurs `PurRequisition` approuvees
(PUR-BULK1), machine a etats complete (`django-fsm-2`/`attempt_transition()`
du socle, meme patron que `apps.sales.services.orders`), et routage
d'approbation conditionnel a la validation (PUR-ROUT1, reutilise
`ApprovalRule`/`request_approval` du socle, meme patron qu'
`apps.accounting.services.invoices`).

Discipline `attempt_transition` (garde-fou architecture T7, cf.
`tests/architecture/test_attempt_transition_saves_state.py`) : chaque
fonction de transition ci-dessous rappelle explicitement
`order.save(update_fields=[...])` en incluant `"state"` juste apres
`attempt_transition(...)`, jamais dans la methode `@transition` elle-meme."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounting.services.public import (
    convert_amount_to_mga,
    get_budget_variance_for_analytic_account,
)
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.models.workflow import ApprovalRequest, ApprovalRule
from apps.core.services.approvals import request_approval
from apps.core.services.sequences import next_reference
from apps.core.services.workflow import attempt_transition
from apps.purchase.models import PurOrder, PurOrderLine, PurRequisition, PurRequisitionLine

LEVEL1_THRESHOLD_MGA = Decimal("2000000")
LEVEL2_THRESHOLD_MGA = Decimal("10000000")

RULE_NAME_LEVEL1 = "purchase.order.approval.level1"
RULE_NAME_LEVEL2 = "purchase.order.approval.level2"
RULE_NAME_IMPORT = "purchase.order.approval.import"
# PUR-BUD1 (PU6, cf. plan) : 4e palier de routage RG-PUR-ROUT1, dimension
# budgetaire — cf. `_order_exceeds_budget`/`_rule_matches` plus bas.
RULE_NAME_BUDGET = "purchase.order.approval.budget"

# B3 (ACH-6, cf. plan) : ecart de change juge materiel a partir de ce seuil
# (%, valeur absolue) — constante LOCALE a `purchase`, jamais importee
# depuis `apps.financing.services.credoc.FX_VARIANCE_ALERT_THRESHOLD_PCT`.
# Deux raisons independantes l'imposent : (1) regle de couplage n°1, seule
# `services.public` est une surface cross-app autorisee, et cette
# constante n'y est pas exposee cote `financing` ; (2) `purchase` ne
# declare pas — et ne doit pas declarer — `financing` comme dependance
# dans `module.py` (le sens va deja dans l'autre sens : `financing` depend
# de `purchase`, cf. `apps.financing.services.credoc.build_dossier_
# timeline`, B2 — une dependance retour creerait un cycle). Meme valeur
# numerique par simple convergence de jugement metier assumee, pas par
# partage de code.
FX_VARIANCE_ALERT_THRESHOLD_PCT = Decimal("2")


class PurchaseApprovalRequiredError(Exception):
    """La commande attend une ou plusieurs decisions d'approbation avant de
    pouvoir etre validee (PUR-ROUT1)."""


def _resolve_exchange_rate(*, tenant: Tenant, currency: str, date: dt.date) -> Decimal:
    """B3 (ACH-6, cf. plan) : capture le taux de change connu de `currency`
    a la date `date`, via l'unique surface autorisee `accounting.services.
    public.convert_amount_to_mga` (jamais `accounting.services.currency.
    get_rate` directement — regle de couplage n°1, `get_rate` n'est pas
    expose par `services.public`). Astuce : `convert_amount_to_mga(
    Decimal(1), ...)` renvoie exactement le taux (`convert_to_mga`
    multiplie par le taux puis `quantize(Decimal("0.0001"))`) — evite
    d'ajouter une fonction dediee a `accounting.services.public` hors
    perimetre de ce sprint. Precision assumee et disclosee : le taux
    capture est donc tronque a 4 decimales alors qu'`AccExchangeRate.
    rate_to_mga`/`PurOrder.exchange_rate` portent 6 decimales —
    simplification coherente avec le reste du schema `purchase` (tous les
    montants MGA du module sont eux-memes a 4 decimales).

    Retourne toujours `Decimal(1)` (jamais d'exception) pour `currency ==
    "MGA"` (pas de recherche, correspond a la devise pivot) ET si aucun
    `AccExchangeRate` n'est configure a cette date pour `currency` — meme
    discipline "gap de configuration a la charge du tenant, jamais un
    blocage" que `_order_exceeds_budget` plus bas dans ce fichier : une
    commande d'achat en devise etrangere reste creable meme si le tenant
    n'a pas encore parametre sa table de taux de change."""
    if currency == "MGA":
        return Decimal(1)
    try:
        return convert_amount_to_mga(Decimal(1), currency, date, tenant=tenant)
    except ValidationError:
        return Decimal(1)


def create_order(
    *,
    tenant: Tenant,
    partner_id: UUID,
    date: dt.date,
    date_expected: dt.date | None = None,
    origin: str = PurOrder.ORIGIN_LOCAL,
    currency: str = "MGA",
    requisition: PurRequisition | None = None,
    **optional_fields: Any,
) -> PurOrder:
    reference = next_reference(tenant, "PCMD", timezone.now().year)
    # RG-PUR-7 (importation, PU6, cf. plan) : **stub honnete documente** —
    # signale automatiquement qu'un dossier d'importation reste a ouvrir
    # des que l'origine n'est pas `local`, jamais pour un achat local. La
    # creation reelle du dossier appartient au futur module `logistics`
    # (§5.7.5) — cf. docstring du champ sur `PurOrder`.
    optional_fields.setdefault("import_dossier_pending", origin != PurOrder.ORIGIN_LOCAL)
    # B3 (ACH-6, cf. plan) : ne recalcule jamais un taux explicitement
    # fourni par l'appelant — respecte un futur appelant qui voudrait
    # forcer un taux negocie. Garde explicite (pas `.setdefault(...)`) pour
    # ne payer l'aller-retour comptable de `_resolve_exchange_rate` que
    # lorsque c'est reellement necessaire (jamais pour un appel qui fournit
    # deja `exchange_rate`, jamais deux fois).
    if "exchange_rate" not in optional_fields:
        optional_fields["exchange_rate"] = _resolve_exchange_rate(
            tenant=tenant, currency=currency, date=date
        )
    return PurOrder.objects.create(
        tenant=tenant,
        reference=reference,
        partner_id=partner_id,
        date=date,
        date_expected=date_expected,
        origin=origin,
        currency=currency,
        requisition=requisition,
        **optional_fields,
    )


def order_fx_variance(order: PurOrder, *, as_of: dt.date | None = None) -> dict[str, Any] | None:
    """B3 (ACH-6, cf. plan) : "taux de change commande d'achat exploité" —
    même patron que `FinCredoc.amount_foreign`/`financing.services.credoc.
    credoc_fx_variance` déjà livré (B2), adapté à une différence
    structurelle de `PurOrder` : il n'existe AUCUN champ de montant en
    devise étrangère stocké (`amount_total_mga` est toujours en MGA). Le
    montant étranger implicite est donc RECONSTRUIT algébriquement à
    partir du taux capturé à la création (`order.exchange_rate`, cf.
    `create_order`/`_resolve_exchange_rate`) :
    `implied_foreign_total = order.amount_total_mga / order.exchange_rate`.
    Cette reconstruction n'est exacte QUE si `exchange_rate` est
    réellement le taux appliqué au booking (vrai depuis ce sprint) — reste
    une grandeur DÉRIVÉE, PAS la reconversion d'un montant en devise
    réellement saisi par l'utilisateur (à la différence de
    `credoc_fx_variance`, garantie plus forte car `FinCredoc.amount_
    foreign` est une vraie saisie) : simplification assumée, à documenter
    comme telle partout où ce résultat est consommé.

    Retourne `None`, jamais une exception :
    (1) pour une commande en MGA (aucun risque de change) ;
    (2) si `order.exchange_rate` est encore à sa valeur par défaut non
        exploitée `Decimal(1)` alors que `currency != "MGA"` — signe
        qu'AUCUN taux réel n'a jamais été capturé pour cette commande
        (commande antérieure à ce sprint, ou dégradation gracieuse de
        `_resolve_exchange_rate` faute de `AccExchangeRate` configuré au
        booking) : diviser par ce `1` produirait un montant étranger
        implicite ARTEFACTUEL (numériquement égal à `amount_total_mga`),
        et donc un écart énorme et totalement faux si on le reconvertissait
        comme si c'était une vraie devise ;
    (3) si aucun `AccExchangeRate` n'est configuré pour `currency` à la
        date `as_of` (même discipline "gap de configuration, jamais un
        blocage").

    `is_material` : `True` si l'écart absolu dépasse
    `FX_VARIANCE_ALERT_THRESHOLD_PCT` — même seuil et même sémantique que
    `credoc_fx_variance`, constante locale distincte (cf. son
    commentaire)."""
    if order.currency == "MGA" or order.exchange_rate == Decimal(1):
        return None

    as_of = as_of or dt.date.today()
    implied_foreign_total = order.amount_total_mga / order.exchange_rate
    try:
        current_amount_mga = convert_amount_to_mga(
            implied_foreign_total, order.currency, as_of, tenant=order.tenant
        )
    except ValidationError:
        return None

    variance_mga = current_amount_mga - order.amount_total_mga
    variance_pct = (
        (variance_mga / order.amount_total_mga * Decimal(100))
        if order.amount_total_mga
        else Decimal(0)
    )
    return {
        "booked_amount_mga": order.amount_total_mga,
        "current_amount_mga": current_amount_mga,
        "variance_mga": variance_mga,
        "variance_pct": variance_pct,
        "is_material": abs(variance_pct) >= FX_VARIANCE_ALERT_THRESHOLD_PCT,
    }


def add_order_line(
    order: PurOrder,
    *,
    variant_id: UUID,
    description: str,
    qty: Decimal,
    unit_price_mga: Decimal,
    uom: str = "",
    discount_pct: Decimal = Decimal(0),
    tax_pct: Decimal = Decimal(0),
    **optional_fields: Any,
) -> PurOrderLine:
    if order.state != PurOrder.STATE_DRAFT:
        raise ValidationError(
            _("Seule une commande d'achat en brouillon peut recevoir de nouvelles lignes.")
        )

    subtotal_mga = (qty * unit_price_mga * (Decimal(100) - discount_pct) / Decimal(100)).quantize(
        Decimal("0.0001")
    )

    line = PurOrderLine.objects.create(
        tenant=order.tenant,
        order=order,
        variant_id=variant_id,
        description=description,
        qty=qty,
        uom=uom,
        unit_price_mga=unit_price_mga,
        discount_pct=discount_pct,
        tax_pct=tax_pct,
        subtotal_mga=subtotal_mga,
        **optional_fields,
    )
    _recompute_totals(order)
    return line


def _recompute_totals(order: PurOrder) -> None:
    amount_untaxed_mga = order.lines.aggregate(total=Sum("subtotal_mga"))["total"] or Decimal(0)
    amount_tax_mga = Decimal(0)
    for line in order.lines.all():
        amount_tax_mga += (line.subtotal_mga * line.tax_pct / Decimal(100)).quantize(
            Decimal("0.0001")
        )
    order.amount_untaxed_mga = amount_untaxed_mga
    order.amount_tax_mga = amount_tax_mga
    order.amount_total_mga = amount_untaxed_mga + amount_tax_mga
    order.save(update_fields=["amount_untaxed_mga", "amount_tax_mga", "amount_total_mga"])


def create_order_from_requisition(requisition: PurRequisition, *, partner_id: UUID) -> PurOrder:
    """RG-PUR-1-aware (cf. plan) : recopie les lignes de la demande d'achat
    approuvee sans re-interroger `catalog` — `estimated_price_mga`, deja
    resolu a la creation de la ligne (PU1/PU2), sert directement de
    `unit_price_mga`. `partner_id` reste un argument explicite : une
    demande d'achat peut porter des `preferred_supplier_id` differents par
    ligne (RG-PUR-1), le choix du fournisseur unique de LA commande
    resultante reste donc une decision de l'appelant, pas une deduction
    automatique."""
    if requisition.state != PurRequisition.STATE_APPROVED:
        raise ValidationError(_("Seule une demande d'achat approuvée peut générer une commande."))

    order = create_order(
        tenant=requisition.tenant,
        partner_id=partner_id,
        date=timezone.now().date(),
        requisition=requisition,
    )
    for line in requisition.lines.all():
        add_order_line(
            order,
            variant_id=line.variant_id,
            description=line.description,
            qty=line.qty,
            unit_price_mga=line.estimated_price_mga,
            uom=line.uom,
            substitute=line.substitute,
        )
    return order


def create_bulk_orders_from_requisitions(
    requisition_ids: list[UUID], *, tenant: Tenant
) -> dict[str, list[Any]]:
    """PUR-BULK1 : regroupe les lignes de PLUSIEURS demandes d'achat
    approuvees par fournisseur prefere (`PurRequisitionLine.
    preferred_supplier_id`) et cree UNE `PurOrder` par fournisseur distinct,
    contenant toutes les lignes correspondantes de toutes les demandes en
    entree. Une ligne sans `preferred_supplier_id` n'est JAMAIS abandonnee
    silencieusement — elle est reportee dans `lines_skipped` du resultat."""
    requisitions = list(PurRequisition.objects.filter(tenant=tenant, id__in=requisition_ids))
    missing = set(requisition_ids) - {r.id for r in requisitions}
    if missing:
        raise ValidationError(_("Demande(s) d'achat introuvable(s) : %(ids)s") % {"ids": missing})
    not_approved = [r for r in requisitions if r.state != PurRequisition.STATE_APPROVED]
    if not_approved:
        raise ValidationError(
            _(
                "Seules des demandes d'achat approuvées peuvent être "
                "groupees en commandes (PUR-BULK1)."
            )
        )

    lines_by_supplier: dict[UUID, list[PurRequisitionLine]] = defaultdict(list)
    lines_skipped: list[dict[str, Any]] = []
    for requisition in requisitions:
        for line in requisition.lines.all():
            if line.preferred_supplier_id is None:
                lines_skipped.append(
                    {
                        "requisition_id": requisition.id,
                        "line_id": line.id,
                        "description": line.description,
                        "reason": "no_preferred_supplier",
                    }
                )
                continue
            lines_by_supplier[line.preferred_supplier_id].append(line)

    orders_created: list[PurOrder] = []
    for partner_id, lines in lines_by_supplier.items():
        order = create_order(tenant=tenant, partner_id=partner_id, date=timezone.now().date())
        for line in lines:
            add_order_line(
                order,
                variant_id=line.variant_id,
                description=line.description,
                qty=line.qty,
                unit_price_mga=line.estimated_price_mga,
                uom=line.uom,
                substitute=line.substitute,
            )
        orders_created.append(order)

    return {"orders_created": orders_created, "lines_skipped": lines_skipped}


def ensure_default_purchase_approval_rules(tenant: Tenant) -> None:
    """PUR-ROUT1 : cree, s'ils n'existent pas encore, les paliers de
    routage par defaut suggeres par le cahier des charges — idempotent,
    modifiable ensuite par le tenant. 2 axes de condition (`ApprovalRule.
    condition`, JSON) : `min_amount` (montant total MGA) et `origin`/
    `origin_prefix` (RG-PUR-ROUT1 ajoute l'origine comme dimension
    supplementaire par rapport au routage purement montant d'
    `accounting`). `category` (mentionne par le CDC) reste hors perimetre :
    aucun modele de "categorie d'achat" n'existe encore dans ce depot (cf.
    plan) — seule l'origine est reellement cablee.

    Regle 3 (import) assumee et documentee : le CDC ne precise pas de seuil
    pour les achats a l'import, une double-validation systematique
    (direction) des que l'origine commence par `"import_"` est retenue par
    defaut, quel que soit le montant — c'est la deviation la plus
    prudente.

    Regle 4 (PUR-BUD1, PU6) : 4e palier, dimension budgetaire — jamais
    fondee sur `min_amount`/`origin` comme les 3 premieres (condition
    dediee `{"budget_check": "true"}`, cf. `_rule_matches` qui la
    reconnait et delegue a `_order_exceeds_budget` au lieu du controle
    montant/origine generique). Role "direction" assume par coherence avec
    la regle 3 (meme absence de seuil precise par le CDC pour ce cas)."""
    content_type = ContentType.objects.get_for_model(PurOrder)
    defaults = [
        (RULE_NAME_LEVEL1, "acheteur", 1, {"min_amount": str(LEVEL1_THRESHOLD_MGA)}),
        (RULE_NAME_LEVEL2, "direction", 2, {"min_amount": str(LEVEL2_THRESHOLD_MGA)}),
        (RULE_NAME_IMPORT, "direction", 3, {"min_amount": "0", "origin_prefix": "import_"}),
        (RULE_NAME_BUDGET, "direction", 4, {"budget_check": "true"}),
    ]
    for name, role, sequence_order, condition in defaults:
        ApprovalRule.objects.get_or_create(
            tenant=tenant,
            content_type=content_type,
            name=name,
            defaults={
                "approver_role": role,
                "sequence_order": sequence_order,
                "condition": condition,
            },
        )


def _order_exceeds_budget(order: PurOrder) -> bool:
    """PUR-BUD1 (PU6, cf. plan) : `True` si le cumul reel deja engage sur
    l'axe analytique de `order` PLUS le montant de CETTE commande
    depasserait le budget approuve de cet axe. Retourne toujours `False`
    (jamais d'exception) si `order.analytic_account_id` n'est pas
    renseigne OU si `accounting.services.public.
    get_budget_variance_for_analytic_account` ne trouve aucun budget/
    aucune ligne budgetaire correspondante — un tenant sans budget
    parametre pour cet axe n'est pas bloque, meme discipline "gap de
    configuration a la charge de l'administrateur du tenant" que le reste
    de ce sous-sequencement (cf. `apps.accounting.services.public`)."""
    if order.analytic_account_id is None:
        return False

    variance = get_budget_variance_for_analytic_account(
        tenant=order.tenant, analytic_account_id=order.analytic_account_id
    )
    if variance is None:
        return False

    projected_actual_mga: Decimal = variance["actual_amount_mga"] + order.amount_total_mga
    budgeted_amount_mga: Decimal = variance["budgeted_amount_mga"]
    return projected_actual_mga > budgeted_amount_mga


def _rule_matches(rule: ApprovalRule, order: PurOrder) -> bool:
    condition = rule.condition or {}

    # PUR-BUD1 (PU6) : la regle budgetaire ne suit jamais le controle
    # montant/origine generique ci-dessous — condition dediee, cf.
    # `ensure_default_purchase_approval_rules`.
    if condition.get("budget_check") == "true":
        return _order_exceeds_budget(order)

    min_amount = Decimal(condition.get("min_amount", "0"))
    if order.amount_total_mga < min_amount:
        return False

    origin_exact = condition.get("origin", "")
    if origin_exact and order.origin != origin_exact:
        return False

    origin_prefix = condition.get("origin_prefix", "")
    return not origin_prefix or order.origin.startswith(origin_prefix)


def _applicable_rules(tenant: Tenant, order: PurOrder) -> list[ApprovalRule]:
    content_type = ContentType.objects.get_for_model(PurOrder)
    rules = ApprovalRule.objects.filter(
        tenant=tenant, content_type=content_type, is_active=True
    ).order_by("sequence_order")
    return [rule for rule in rules if _rule_matches(rule, order)]


def ensure_purchase_approval(order: PurOrder, *, requested_by: User) -> None:
    """A appeler avant de considerer une commande comme validable (cf.
    `validate_order` ci-dessous). Ne fait rien si aucune `ApprovalRule`
    applicable n'existe/n'est configuree. Sinon, cree (ou verifie) chaque
    demande d'approbation requise, dans l'ordre `sequence_order`, et leve
    tant qu'une decision manque ou est en attente (meme patron que
    `accounting.services.invoices.validate_invoice`)."""
    content_type = ContentType.objects.get_for_model(PurOrder)
    rules = _applicable_rules(order.tenant, order)

    for rule in rules:
        existing = ApprovalRequest.objects.filter(
            rule=rule, content_type=content_type, object_id=str(order.id)
        ).first()
        if existing is None:
            request_approval(order, rule, requested_by=requested_by)
            raise PurchaseApprovalRequiredError(
                _("Validation en attente d'approbation (%(role)s).") % {"role": rule.approver_role}
            )
        if existing.status == ApprovalRequest.STATUS_PENDING:
            raise PurchaseApprovalRequiredError(
                _("Validation en attente d'approbation (%(role)s).") % {"role": rule.approver_role}
            )
        if existing.status == ApprovalRequest.STATUS_REJECTED:
            raise ValidationError(
                _("Validation rejetée par %(role)s.") % {"role": rule.approver_role}
            )


def submit_order_for_validation(order: PurOrder, user: User) -> PurOrder:
    attempt_transition(order, "submit_for_validation", user)
    order.save(update_fields=["state"])
    return order


def validate_order(order: PurOrder, user: User) -> PurOrder:
    """PUR-ROUT1 : bloque la transition `to_validate -> validated` tant que
    le routage d'approbation applicable n'est pas entierement satisfait."""
    ensure_purchase_approval(order, requested_by=user)
    attempt_transition(order, "validate", user)
    order.save(update_fields=["state"])
    return order


def send_order(order: PurOrder, user: User) -> PurOrder:
    attempt_transition(order, "send", user)
    order.save(update_fields=["state"])
    return order


def confirm_order(order: PurOrder, user: User) -> PurOrder:
    """INT1 (chantier interactivite native inter-modules) : publie
    `purchase.order_confirmed` apres transition effective — meme patron
    que `helpdesk.services.tickets.escalate_ticket` (transition/`.save()`
    d'abord, `publish_event` ensuite)."""
    attempt_transition(order, "confirm", user)
    order.save(update_fields=["state"])

    from apps.core.events import publish_event

    publish_event(
        "purchase.order_confirmed",
        {
            "order_id": str(order.id),
            "reference": order.reference,
            "partner_id": str(order.partner_id),
            "amount_total_mga": str(order.amount_total_mga),
        },
        tenant_id=str(order.tenant_id),
    )
    return order


def mark_order_in_transit(order: PurOrder, user: User) -> PurOrder:
    attempt_transition(order, "mark_in_transit", user)
    order.save(update_fields=["state"])
    return order


def mark_order_partially_received(order: PurOrder, user: User) -> PurOrder:
    attempt_transition(order, "mark_partially_received", user)
    order.save(update_fields=["state"])
    return order


def mark_order_received(order: PurOrder, user: User) -> PurOrder:
    attempt_transition(order, "mark_received", user)
    order.save(update_fields=["state"])
    return order


def mark_order_invoiced(order: PurOrder, user: User) -> PurOrder:
    """Declaree pour completude de la FSM (§5.6.4) — le cablage reel au
    controle facture 3 voies RG-PUR-6 arrive en PU6 (meme patron que
    `SalesOrder.mark_invoiced` en S2, cf. docstring `models.py`)."""
    attempt_transition(order, "mark_invoiced", user)
    order.save(update_fields=["state"])
    return order


def close_order(order: PurOrder, user: User) -> PurOrder:
    attempt_transition(order, "close", user)
    order.save(update_fields=["state"])
    return order


def cancel_order(order: PurOrder, user: User, *, reason: str) -> PurOrder:
    if not reason:
        raise ValidationError(_("Un motif est obligatoire pour annuler une commande d'achat."))
    attempt_transition(order, "cancel", user, comment=reason)
    order.cancel_reason = reason
    order.save(update_fields=["state", "cancel_reason"])
    return order


def open_order_dispute(order: PurOrder, user: User, *, reason: str) -> PurOrder:
    """INT1 (chantier interactivite native inter-modules) : publie
    `purchase.dispute_opened` apres transition effective. **Choix assume
    et disclosed** : le CDC de ce chantier situe "ouverture d'un litige a
    la reception" cote `apps.purchase.services.receiving` — verification
    faite, ce fichier ne porte AUCUNE fonction d'ouverture de litige
    (seulement `receive_order_line`/`order_reception_variance`) ; la
    transition FSM `open_dispute` reelle de `PurOrder` vit ICI, dans
    `services/orders.py` (branche "en litige" du diagramme §5.6.4, cf.
    docstring `receiving.py` qui la distingue explicitement de `PurCri`).
    L'evenement est donc cable sur cette fonction reelle plutot que sur un
    fichier qui ne contient pas la logique concernee — jamais une
    duplication via `PurCri` (deja verifie : `PurCri` cf.
    `apps.purchase.services.cri` reste un compte-rendu d'incident distinct,
    pas la branche FSM "en litige").

    INT3 (chantier interactivite native inter-modules) : signale AUSSI un
    `RiskItem` generique (`core.services.risk.create_risk_item`,
    `category="fournisseur"` — valeur `CATEGORY_SUPPLIER` deja existante
    dans `RiskItem.CATEGORY_CHOICES`, aucun nouveau choix necessaire) DES
    QU'UNE COMMANDE PASSE EN LITIGE — chaque litige est par nature un
    evenement rare et deja significatif (contrairement a une transition de
    routine comme `confirm_order`), donc AUCUN seuil de filtrage
    supplementaire n'est applique ici : ouvrir un litige EST le seuil
    (jamais de RiskItem sur les transitions normales de la FSM). Score
    fixe assume `likelihood=4, impact=4` (=16, au-dessus de
    `HIGH_SCORE_THRESHOLD=15`) : un litige avec un fournisseur est par
    construction "probable de se reproduire avec ce partenaire"
    (`likelihood` eleve, litige deja materialise) et "a impact fort sur la
    chaine d'approvisionnement" (`impact` eleve, commande deja engagee) —
    ce score fait donc systematiquement franchir le seuil qui publie
    `risk.flagged`, remontant l'alerte au Studio d'automatisation (meme
    reutilisation que PJ9/`projects.flag_project_risk`, jamais un nouveau
    mecanisme de risque). `owner=user` (l'auteur de l'ouverture du litige,
    seul utilisateur humain disponible ici — `PurOrder` ne porte aucun
    champ "acheteur", contrairement a `PurCra.buyer`) ; `content_object=
    order` (rattachement direct a la commande en litige, pas au
    fournisseur — `partner_id` n'est qu'un UUID opaque, cf. regle de
    couplage n1, jamais un objet resoluble ici sans importer `partners`)."""
    if not reason:
        raise ValidationError(_("Un motif est obligatoire pour ouvrir un litige."))
    attempt_transition(order, "open_dispute", user, comment=reason)
    order.dispute_reason = reason
    order.save(update_fields=["state", "dispute_reason"])

    from apps.core.events import publish_event
    from apps.core.models.risk import CATEGORY_SUPPLIER
    from apps.core.services.risk import create_risk_item

    publish_event(
        "purchase.dispute_opened",
        {
            "order_id": str(order.id),
            "reference": order.reference,
            "partner_id": str(order.partner_id),
            "reason": reason,
        },
        tenant_id=str(order.tenant_id),
    )
    create_risk_item(
        tenant=order.tenant,
        category=CATEGORY_SUPPLIER,
        likelihood=4,
        impact=4,
        owner=user,
        mitigation_plan=reason,
        content_object=order,
    )
    return order


def resolve_order_dispute(order: PurOrder, user: User) -> PurOrder:
    attempt_transition(order, "resolve_dispute", user)
    order.save(update_fields=["state"])
    return order
