"""Ecrans du module `quality` (HACCP, Phase 3 Bloc D) — L11.

**Ce que ces ecrans reparent.** Le module etait livre complet et teste, et
inatteignable depuis le produit : aucune vue, aucune URL, aucune API (ecart
§3.4 de l'audit). Un responsable qualite ne pouvait ni enregistrer une
mesure, ni ouvrir une non-conformite, ni declarer un rappel de lot — alors
que toute la mecanique existait sous les tests.

Quatre ecrans, pas davantage : plans de controle (avec la liste des
controles EN RETARD, qui est la raison d'etre de QUA-9), detail d'un plan et
saisie d'une mesure, non-conformites, dossiers de rappel. Meme idiome que
`apps.core.views.quality` et `apps.helpdesk.views` — formulaires HTML bruts,
aucun `forms.py` (ce depot n'en a aucun), aucun `django.contrib.messages`.

Aucune regle metier ici : tout passe par `apps.quality.services.public`,
deja teste. En particulier le refus de liberer un lot sous non-conformite
ouverte reste porte par `release_lot_hold`, jamais redit dans une vue.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.core.models.user import User
from apps.core.views.tenant_web import resolve_tenant
from apps.quality.models import (
    QltControlPlan,
    QltCriticalPoint,
    QltMeasurement,
    QltNonConformity,
    QltRecallDossier,
)
from apps.quality.services import public as quality_public


def _optional_decimal(raw: str) -> Decimal | None:
    raw = (raw or "").strip()
    return Decimal(raw) if raw else None


@login_required
def control_plan_list(request: HttpRequest) -> HttpResponse:
    """Plans de controle et, en tete, les controles en retard.

    Les deux sur le meme ecran a dessein : un plan de controle sans la
    reponse a « qu'est-ce qui est en retard ? » est un document, pas un
    outil. C'est aussi le seul endroit ou QUA-9 devient consultable — la
    commande periodique notifie, elle ne montre rien."""
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            quality_public.create_control_plan(
                tenant=tenant,
                name=request.POST.get("name", ""),
                frequency_days=int(request.POST.get("frequency_days") or 0),
                notes=request.POST.get("notes", ""),
            )
            return redirect("quality:control_plan_list")
        except (ValidationError, ValueError, IntegrityError) as exc:
            error = str(exc)

    plans = (
        QltControlPlan.objects.filter(tenant=tenant, is_active=True)
        .prefetch_related("critical_points")
        .order_by("name")
    )
    return render(
        request,
        "quality/control_plan_list.html",
        {
            "plans": plans,
            # LECTURE PURE : consulter l'ecran ne doit jamais declencher les
            # notifications que la commande periodique envoie.
            "overdue": quality_public.check_overdue_controls(tenant=tenant),
            "error": error,
        },
    )


@login_required
def control_plan_detail(request: HttpRequest, plan_id: str) -> HttpResponse:
    """Points critiques du plan, et saisie d'une mesure.

    Une mesure hors limites ouvre une non-conformite et bloque le lot dans
    la meme transaction — l'ecran ne previent pas de cet effet avant coup
    parce que c'est justement ce qu'on attend de lui (QUA-1/2/3) ; il
    l'affiche apres, sur la mesure enregistree."""
    tenant = resolve_tenant(request)
    plan = get_object_or_404(QltControlPlan, id=plan_id, tenant=tenant)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "add_point")
        try:
            if action == "add_point":
                quality_public.add_critical_point(
                    plan,
                    name=request.POST.get("name", ""),
                    unit=request.POST.get("unit", ""),
                    limit_min=_optional_decimal(request.POST.get("limit_min", "")),
                    limit_max=_optional_decimal(request.POST.get("limit_max", "")),
                    sequence=int(request.POST.get("sequence") or 0),
                )
            elif action == "record_measurement":
                point = plan.critical_points.get(id=request.POST.get("critical_point_id", ""))
                quality_public.record_measurement(
                    point,
                    tenant=tenant,
                    value=Decimal(request.POST.get("value", "")),
                    measured_by=cast(User, request.user),
                    lot_variant_id=request.POST.get("lot_variant_id") or None,
                    lot_name=request.POST.get("lot_name", ""),
                )
            return redirect("quality:control_plan_detail", plan_id=str(plan.id))
        except QltCriticalPoint.DoesNotExist:
            error = _("Point critique introuvable.")
        except (ValidationError, ValueError, InvalidOperation, IntegrityError) as exc:
            error = str(exc)

    measurements = (
        QltMeasurement.objects.filter(critical_point__control_plan=plan)
        .select_related("critical_point")
        .order_by("-measured_at")[:50]
    )
    return render(
        request,
        "quality/control_plan_detail.html",
        {
            "plan": plan,
            "critical_points": plan.critical_points.all(),
            "measurements": measurements,
            "error": error,
        },
    )


@login_required
def non_conformity_list(request: HttpRequest) -> HttpResponse:
    """Non-conformites ouvertes et cloturees, ouverture manuelle, cloture,
    et liberation d'un lot.

    La liberation est ici et non sur un ecran de stock : refuser de liberer
    un lot sous non-conformite ouverte est une decision QUALITE, et la
    mettre a portee de main de qui gere le stock reviendrait a la contourner
    sans le vouloir."""
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "open")
        try:
            if action == "open":
                quality_public.create_non_conformity(
                    tenant=tenant,
                    opened_by=cast(User, request.user),
                    description=request.POST.get("description", ""),
                    lot_variant_id=request.POST.get("lot_variant_id") or None,
                    lot_name=request.POST.get("lot_name", ""),
                )
            elif action == "close":
                non_conformity = QltNonConformity.objects.get(
                    id=request.POST.get("non_conformity_id", ""), tenant=tenant
                )
                quality_public.close_non_conformity(
                    non_conformity,
                    closed_by=cast(User, request.user),
                    closing_reason=request.POST.get("closing_reason", ""),
                )
            elif action == "release_lot":
                quality_public.release_lot_hold(
                    tenant=tenant,
                    lot_variant_id=request.POST.get("lot_variant_id") or None,
                    lot_name=request.POST.get("lot_name", ""),
                    released_by=cast(User, request.user),
                    reason=request.POST.get("reason", ""),
                )
            return redirect("quality:non_conformity_list")
        except QltNonConformity.DoesNotExist:
            error = _("Non-conformité introuvable.")
        except (ValidationError, ValueError, IntegrityError) as exc:
            error = str(exc)

    non_conformities = QltNonConformity.objects.filter(tenant=tenant).order_by(
        "state", "-opened_at"
    )
    return render(
        request,
        "quality/non_conformity_list.html",
        {
            "non_conformities": non_conformities,
            "open_state": QltNonConformity.STATE_OPEN,
            "error": error,
        },
    )


@login_required
def recall_list(request: HttpRequest) -> HttpResponse:
    """Dossiers de rappel : declaration et cloture.

    Declarer un rappel met en quarantaine le lot ET toute sa descendance, et
    fige la genealogie a cet instant — un dossier de rappel est la preuve de
    ce qui etait su et declare, jamais un etat recalcule."""
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "declare")
        try:
            if action == "declare":
                quality_public.declare_recall(
                    tenant=tenant,
                    lot_variant_id=request.POST.get("lot_variant_id") or None,
                    lot_name=request.POST.get("lot_name", ""),
                    reason=request.POST.get("reason", ""),
                    initiated_by=cast(User, request.user),
                )
            elif action == "close":
                dossier = QltRecallDossier.objects.get(
                    id=request.POST.get("dossier_id", ""), tenant=tenant
                )
                quality_public.close_recall(
                    dossier,
                    closed_by=cast(User, request.user),
                    closing_reason=request.POST.get("closing_reason", ""),
                )
            return redirect("quality:recall_list")
        except QltRecallDossier.DoesNotExist:
            error = _("Dossier de rappel introuvable.")
        except (ValidationError, ValueError, IntegrityError) as exc:
            error = str(exc)

    dossiers = QltRecallDossier.objects.filter(tenant=tenant).order_by("-initiated_at")
    return render(
        request,
        "quality/recall_list.html",
        {
            "dossiers": dossiers,
            "open_state": QltRecallDossier.STATE_OPEN,
            "error": error,
        },
    )
