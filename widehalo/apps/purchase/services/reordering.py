"""Réapprovisionnement automatique (RG-PUR-3, §5.6.2, PU5 du
sous-sequencement `purchase` — cf. plan, section "Decisions de
sequencement et de perimetre pour ce lot").

**Stock ET commandes en cours reellement lus** : `run_reordering`
compare desormais `min_qty` a la disponibilite REELLE
(`stocks.services.public.get_available_stock_qty`, agrege sur les
emplacements INTERNES uniquement) PLUS les commandes fournisseur deja
EN COURS (`services.public.get_open_order_qty`, Bloc F/F1) — jamais un
stub, jamais un recalcul duplique ici. Ferme le second volet de FOR-12
("réapprovisionnement existant ignore les commandes en cours") : une
regle dont le disponible est bas mais dont une commande est deja en
route pour la couvrir ne genere plus de proposition redondante.

**Bloc F, F2 (FOR-12/FOR-13) : jamais automatique.** Une regle
declenchee ne cree plus directement de `PurRequisition` — elle genere
une `PurReorderingProposal` (instantanee, EN ATTENTE) et ouvre une
`ApprovalRule`/`ApprovalRequest` du socle (meme patron exact que
`apps.purchase.services.substitution`, RG-PUR-2, et
`apps.accounting.services.cash_journal_import`, RG-QUALIF) — la demande
d'achat n'est creee que par `decide_reordering_proposal` SI ET SEULEMENT
SI la proposition est explicitement ACCEPTEE. Approbateur par defaut :
`"acheteur"` (domaine cible du module, deja proprietaire de RG-PUR-3
via la permission custom `purchase.run_reordering`)."""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal
from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.models.workflow import ApprovalRequest, ApprovalRule
from apps.core.services.approvals import decide, request_approval
from apps.purchase.models import PurReorderingProposal, PurReorderingRule
from apps.purchase.services.public import get_open_order_qty
from apps.purchase.services.requisitions import add_requisition_line, create_requisition
from apps.stocks.services.public import get_available_stock_qty

RULE_NAME = "purchase.reordering.proposal_acceptance"
DEFAULT_APPROVER_ROLE = "acheteur"


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


def _ensure_rule(tenant: Tenant) -> ApprovalRule:
    content_type = ContentType.objects.get_for_model(PurReorderingProposal)
    rule, _created = ApprovalRule.objects.get_or_create(
        tenant=tenant,
        content_type=content_type,
        name=RULE_NAME,
        defaults={"approver_role": DEFAULT_APPROVER_ROLE, "sequence_order": 1},
    )
    return rule


def run_reordering(tenant: Tenant) -> list[PurReorderingProposal]:
    """RG-PUR-3 : pour chaque `PurReorderingRule` active du tenant, compare
    `min_qty` à la couverture REELLE — stock disponible
    (`get_available_stock_qty`) PLUS commandes fournisseur déjà en cours
    (`get_open_order_qty`, Bloc F/F1). Se déclenche dès que cette
    couverture est strictement inférieure à `min_qty` — sauf `min_qty <=
    0` (règle effectivement désactivée, cas valide qu'un admin peut
    choisir : jamais un déclenchement forcé).

    Chaque règle déclenchée génère UNE `PurReorderingProposal` EN
    ATTENTE — jamais de `PurRequisition` créée ici (Bloc F, F2/FOR-13,
    "jamais automatique") : cf. `decide_reordering_proposal` pour la
    suite du cycle.

    Quantité proposée : `max_qty - couverture` arrondi au multiple
    supérieur de `multiple_qty` (cf. `_round_up_to_multiple`) — le vrai
    besoin pour ramener la couverture jusqu'à `max_qty`, jamais un
    montant négatif (garde défensive explicite).

    Demandeur de l'approbation (`requested_by`) : résolu comme le
    premier superutilisateur du tenant — même repli que
    `apps.sales.services.recurrence.run_sales_recurrences`. Un tenant
    sans aucun superutilisateur renvoie une liste vide pour CE tenant."""
    rules = PurReorderingRule.objects.filter(tenant=tenant, is_active=True)
    triggered: list[tuple[PurReorderingRule, Decimal, Decimal]] = []
    # L0-1 : une regle dont une proposition est deja EN ATTENTE ne redeclenche
    # pas. Sans cette garde, brancher un ordonnanceur sur cette commande
    # creerait une proposition ET une demande d'approbation A CHAQUE
    # EXECUTION tant que la couverture reste sous le seuil — c'est-a-dire
    # jusqu'a la reception reelle des marchandises. C'est le cas le plus
    # couteux des cinq commandes non idempotentes du depot.
    rules_with_pending = set(
        PurReorderingProposal.objects.filter(
            tenant=tenant, state=PurReorderingProposal.STATE_PENDING
        ).values_list("rule_id", flat=True)
    )
    for rule in rules:
        if rule.min_qty <= 0:
            continue
        if rule.id in rules_with_pending:
            continue
        available = get_available_stock_qty(rule.variant_id)
        on_order = get_open_order_qty(rule.variant_id)
        if available + on_order < rule.min_qty:
            triggered.append((rule, available, on_order))
    if not triggered:
        return []

    fallback_requester = User.objects.filter(is_superuser=True).order_by("id").first()
    if fallback_requester is None:
        return []

    approval_rule = _ensure_rule(tenant)
    proposals: list[PurReorderingProposal] = []
    for rule, available, on_order in triggered:
        needed = max(rule.max_qty - available - on_order, Decimal(0))
        qty = _round_up_to_multiple(needed, rule.multiple_qty)
        proposal = PurReorderingProposal.objects.create(
            tenant=tenant,
            rule=rule,
            variant_id=rule.variant_id,
            warehouse_id=rule.warehouse_id,
            qty_proposed=qty,
            available_stock=available,
            on_order_qty=on_order,
        )
        approval_request = request_approval(
            proposal, approval_rule, requested_by=fallback_requester
        )
        proposal.approval_request = approval_request
        proposal.save(update_fields=["approval_request"])
        proposals.append(proposal)

    from apps.core.events import publish_event

    # INT1 (chantier interactivite native inter-modules) : UN evenement
    # par execution de `run_reordering` (jamais un par regle), meme
    # granularite qu'avant F2 — seule la cle de payload change
    # (`proposal_ids`, plus de `PurRequisition` creee a ce stade).
    publish_event(
        "purchase.reorder_triggered",
        {"proposal_ids": [str(proposal.id) for proposal in proposals], "count": len(proposals)},
        tenant_id=str(tenant.id),
    )

    return proposals


def decide_reordering_proposal(
    approval_request: ApprovalRequest, decided_by: User, *, approved: bool, comment: str = ""
) -> PurReorderingProposal:
    """Bloc F, F2 : seul point d'entrée qui fait évoluer une
    `PurReorderingProposal` — même patron exact que
    `apps.accounting.services.cash_journal_import.decide_qualification`
    (enveloppe de `apps.core.services.approvals.decide`, jamais une
    mutation directe de `ApprovalRequest.status`).

    Si acceptée : crée ENFIN la vraie `PurRequisition` (brouillon,
    jamais soumise/approuvée automatiquement, RG-PUR-3) — le code qui
    vivait auparavant directement dans `run_reordering` avant F2.

    Si rejetée : la proposition reste sans effet (aucune `PurRequisition`
    créée) — un motif est OBLIGATOIRE (FOR-13 exige un rejet explicite,
    pas un simple silence ; même discipline "motif obligatoire sur toute
    décision négative" que E6/D4 dans ce dépôt)."""
    if not approved and not comment:
        raise ValidationError(
            _("Un motif est obligatoire pour rejeter une proposition de réapprovisionnement.")
        )

    decide(approval_request, decided_by, approved=approved, comment=comment)
    proposal = PurReorderingProposal.objects.get(approval_request=approval_request)

    if approved:
        requisition = create_requisition(
            tenant=proposal.tenant,
            requester=decided_by,
            date_needed=timezone.now().date(),
            justification=_(
                "Réapprovisionnement (RG-PUR-3), proposition acceptée : couverture "
                "(stock %(available)s + commandes en cours %(on_order)s) sous le "
                "seuil minimum de la règle (%(min_qty)s)."
            )
            % {
                "available": proposal.available_stock,
                "on_order": proposal.on_order_qty,
                "min_qty": proposal.rule.min_qty,
            },
            source_document=f"pur_reordering_proposal:{proposal.id}",
        )
        add_requisition_line(
            requisition,
            variant_id=proposal.variant_id,
            description=_("Réapprovisionnement automatique"),
            qty=proposal.qty_proposed,
        )
        proposal.requisition = requisition
        proposal.state = PurReorderingProposal.STATE_ACCEPTED
        proposal.save(update_fields=["requisition", "state"])
    else:
        proposal.state = PurReorderingProposal.STATE_REJECTED
        proposal.rejection_reason = comment
        proposal.save(update_fields=["state", "rejection_reason"])

    return proposal


def get_reordering_acceptance_rate(tenant: Tenant) -> Decimal | None:
    """Taux d'acceptation mesuré (FOR-13) — calcul honnête, jamais un
    taux fabriqué : `None` si aucune proposition n'a encore été décidée
    (même discipline que `apps.helpdesk.services.reports.
    sla_compliance_report`, pas une anomalie à masquer en la forçant à
    0)."""
    decided = PurReorderingProposal.objects.filter(
        tenant=tenant,
        state__in=(PurReorderingProposal.STATE_ACCEPTED, PurReorderingProposal.STATE_REJECTED),
    )
    total = decided.count()
    if total == 0:
        return None
    accepted = decided.filter(state=PurReorderingProposal.STATE_ACCEPTED).count()
    return Decimal(accepted) / Decimal(total)
