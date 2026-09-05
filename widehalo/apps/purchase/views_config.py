"""Ecrans de configuration du module `purchase` (PU8), regroupes sous le
hub "Parametres" (meme convention que `apps.mrp.views_config`/
`apps.sales.views_config`) : regles de reapprovisionnement (RG-PUR-3,
`PurReorderingRule`) et substituts (RG-PUR-2, `PurSubstitute`).

`PurSubstitute` est traite comme donnee de reference/parametrage plutot
que comme un ecran transactionnel — meme choix documente que
`PurReorderingRule` (`BaseModel` sans `ReferenceMixin`, cf. leurs
docstrings `models.py` respectives : toutes deux sont des regles de
configuration consultees par d'autres services, jamais des documents
sequences avec un cycle de vie propre) : c'est ce meme critere qui motive
de les regrouper ici sous "Parametres" plutot que sous les ecrans
transactionnels de `views.py`."""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.views.tenant_web import resolve_tenant
from apps.purchase.models import PurReorderingProposal, PurReorderingRule, PurSubstitute
from apps.purchase.services.reordering import (
    create_reordering_rule,
    decide_reordering_proposal,
    get_reordering_acceptance_rate,
)
from apps.purchase.services.substitution import (
    approve_substitute,
    create_substitute,
    list_substitutes_for_variant,
    request_substitute_approval,
)


def _error_message(exc: Exception) -> str:
    return "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


@login_required
def config_index(request: HttpRequest) -> HttpResponse:
    return render(request, "purchase/config_index.html", {})


@login_required
def config_reordering_rules(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "create")
        try:
            if action == "create":
                create_reordering_rule(
                    tenant=tenant,
                    variant_id=uuid.UUID(request.POST.get("variant_id", "")),
                    min_qty=Decimal(request.POST.get("min_qty") or "0"),
                    max_qty=Decimal(request.POST.get("max_qty") or "0"),
                    multiple_qty=Decimal(request.POST.get("multiple_qty") or "1"),
                    lead_time_days=int(request.POST.get("lead_time_days") or "0"),
                    warehouse_id=uuid.UUID(request.POST["warehouse_id"])
                    if request.POST.get("warehouse_id")
                    else None,
                )
            elif action in ("accept", "reject"):
                # Bloc F, F2 (FOR-12/FOR-13) : "depliable + acceptation/
                # rejet" greffe dans cet ecran existant plutot qu'un
                # nouveau — budget d'ecrans a 0/240 de marge depuis E7.
                proposal = get_object_or_404(
                    PurReorderingProposal, id=request.POST.get("proposal_id"), tenant=tenant
                )
                if proposal.approval_request is None:
                    raise ValidationError(
                        "Cette proposition n'a aucune demande d'approbation associée."
                    )
                decide_reordering_proposal(
                    proposal.approval_request,
                    request.user,
                    approved=action == "accept",
                    comment=request.POST.get("rejection_reason", ""),
                )
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("purchase:config_reordering_rules")

    rules = PurReorderingRule.objects.filter(tenant=tenant, is_active=True)
    proposals = PurReorderingProposal.objects.filter(
        tenant=tenant, state=PurReorderingProposal.STATE_PENDING
    ).select_related("rule")
    acceptance_rate = get_reordering_acceptance_rate(tenant)
    acceptance_rate_pct = f"{acceptance_rate * 100:.1f}" if acceptance_rate is not None else None
    return render(
        request,
        "purchase/config_reordering_rules.html",
        {
            "rules": rules,
            "proposals": proposals,
            "acceptance_rate": acceptance_rate,
            "acceptance_rate_pct": acceptance_rate_pct,
            "error": error,
        },
    )


@login_required
def substitute_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "create":
                substitute = create_substitute(
                    tenant=tenant,
                    variant_id=uuid.UUID(post.get("variant_id", "")),
                    substitute_variant_id=uuid.UUID(post.get("substitute_variant_id", "")),
                    compatibility=post.get("compatibility", PurSubstitute.COMPATIBILITY_EQUIVALENT),
                    ratio=Decimal(post.get("ratio") or "1"),
                    conditions=post.get("conditions", ""),
                )
                request_substitute_approval(substitute, requested_by=request.user)
            elif action == "approve":
                substitute = get_object_or_404(PurSubstitute, id=post.get("substitute_id"))
                approve_substitute(substitute, approved_by=request.user)
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("purchase:substitute_list")

    variant_id = request.GET.get("variant_id", "")
    substitutes = (
        list_substitutes_for_variant(uuid.UUID(variant_id))
        if variant_id
        else list(PurSubstitute.objects.filter(tenant=tenant, is_active=True))
    )
    return render(
        request,
        "purchase/config_substitutes.html",
        {
            "substitutes": substitutes,
            "compatibility_choices": PurSubstitute.COMPATIBILITY_CHOICES,
            "variant_id": variant_id,
            "error": error,
        },
    )
