"""Ecrans HTMX transactionnels du module `stocks` (§5.8, ST8, dernier lot du
sous-sequencement — cf. plan) : session-authentifie (`@login_required`),
appel direct aux `services/*` de `stocks`, jamais l'API JWT interne — meme
patron exact que `apps.purchase.views`/`apps.sales.views`/`apps.mrp.views`.

**Un SEUL gabarit pour l'integralite du module (`stocks/index.html`),
deviation MAJEURE et DELIBEREE par rapport au patron `purchase`/`sales`/
`mrp` (un gabarit par ecran/entite)** : `tests/architecture/test_budget.py`
plafonne le nombre d'ecrans a 90 — le depot en comptait deja 89/90 juste
avant ce lot (`purchase` PU8), ne laissant qu'UN SEUL emplacement de
gabarit disponible pour l'integralite du perimetre ST8 (config entrepots/
emplacements/defauts/exceptions stock negatif, vue stock, mouvements,
pickings, mesures, qualite, reservations, inventaire, retours, tracabilite,
redistribution, obsolescence, ABC, rapports). Un decoupage "un gabarit par
entite" a la `purchase`/PU8 aurait immediatement fait exploser ce plafond
(rien qu'un decoupage liste/detail/creation pour les ~12 entites
transactionnelles de ce module en aurait demande plus de 20). Solution
retenue, seule compatible avec ce plafond dur : UNE application
mono-page — `stocks/index.html` — dont la section affichee est pilotee par
le parametre `?tab=...` (et `?subtab=...` pour la configuration), chaque
vue de ce fichier faisant `render(request, "stocks/index.html", {...})`
avec `active_tab` fixe et SEUL le contexte necessaire a cette section
peuple (le gabarit garde chaque section derriere `{% if active_tab ==
"..." %}`, les sections non actives n'ont besoin d'aucune des variables de
contexte des autres). Les actions de creation/transition (POST) redirigent
toutes vers l'URL `GET` de leur propre section une fois traitees — meme
discipline de redirection post-POST que partout ailleurs dans ce depot,
seule la CIBLE du rendu final differe (toujours le meme fichier)."""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.catalog.services.public import convert_textile_measurement
from apps.core.models.audit import AuditLog
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.views.tenant_web import resolve_tenant
from apps.stocks.models import (
    StkAbcClassification,
    StkInventory,
    StkLocation,
    StkLot,
    StkMove,
    StkPicking,
    StkQualityState,
    StkQuant,
    StkRecall,
    StkReservation,
    StkReturn,
    StkWarehouse,
)
from apps.stocks.services import scan
from apps.stocks.services.abc_classification import compute_abc_classification
from apps.stocks.services.barcodes import lookup_by_barcode
from apps.stocks.services.expiry_alerts import list_expiring_lots
from apps.stocks.services.inventory import (
    add_inventory_line,
    cancel_inventory,
    create_inventory,
    record_count,
    start_inventory,
    validate_inventory,
)
from apps.stocks.services.measurements import record_measurement
from apps.stocks.services.moves import cancel_move, create_move, validate_move
from apps.stocks.services.obsolescence import dormant_stock_report
from apps.stocks.services.pickings import (
    add_picking_line,
    cancel_picking,
    create_picking,
    mark_picking_ready,
    validate_picking,
)
from apps.stocks.services.quality import apply_quality_decision, set_quality_state
from apps.stocks.services.quants import select_lot_fefo
from apps.stocks.services.recall import close_recall, declare_recall
from apps.stocks.services.redistribution import suggest_redistribution
from apps.stocks.services.reservations import release_reservation, reserve_stock
from apps.stocks.services.returns import assess_return, cancel_return, create_return, process_return
from apps.stocks.services.traceability import lot_traceability

_EXC = (ValidationError, InvalidOperation, ValueError)


def _error_message(exc: Exception) -> str:
    return "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


def _uuid_or_none(value: str) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None


def _render(request: HttpRequest, active_tab: str, context: dict[str, Any]) -> HttpResponse:
    context["active_tab"] = active_tab
    return render(request, "stocks/index.html", context)


# ---------------------------------------------------------------------------
# Vue stock (produit x emplacement) — CDC "Vue stock"
# ---------------------------------------------------------------------------


@login_required
def stock_view(request: HttpRequest) -> HttpResponse:
    """Grille produit x emplacement — quantite disponible/reservee/nette.

    **"En commande"/"en production" honnetement absents** : le CDC (§5.8)
    cite ces deux colonnes pour l'ecran "Vue stock", mais `stocks` n'a
    aucune primitive de LECTURE exposee cote `purchase`/`mrp` pour "quantite
    actuellement commandee fournisseur non recue"/"quantite actuellement en
    cours de fabrication" au niveau produit — construire ce gap depasserait
    le perimetre ST8 (ajout d'un nouveau contrat public `purchase`/`mrp`,
    hors fichiers a modifier de ce lot, cf. plan). Cette grille affiche donc
    honnetement les deux colonnes que `stocks` sait calculer nativement
    (disponible = qty-qty_reserved, reserve), documente ici plutot que
    fabrique.

    **Double unite (nicetohave)** : quand un `variant_id` precis est
    filtre, `convert_textile_measurement` est appele sur la quantite totale
    (si convertible — produit textile avec grammage/laize connus cote
    `catalog`) pour un affichage m/kg simultane, cf. RG-STK-5. Renvoie
    `None` silencieusement pour un produit non textile — pas une erreur."""
    variant_raw = request.GET.get("variant_id", "")
    location_id = request.GET.get("location_id", "")
    quants = StkQuant.objects.filter(qty__gt=0, location__type=StkLocation.TYPE_INTERNE)
    variant_id = None
    if variant_raw:
        variant_id = uuid.UUID(variant_raw)
        quants = quants.filter(variant_id=variant_id)
    if location_id:
        quants = quants.filter(location_id=uuid.UUID(location_id))
    quants = list(quants.select_related("location").order_by("location__code"))
    for quant in quants:
        quant.available = quant.qty - quant.qty_reserved  # type: ignore[attr-defined]

    conversion = None
    if variant_id is not None:
        total_qty = sum((q.qty for q in quants), Decimal(0))
        conversion = convert_textile_measurement(variant_id, length_m=total_qty)

    return _render(
        request,
        "stock",
        {
            "quants": quants,
            "variant_id": variant_raw,
            "location_id": location_id,
            "conversion": conversion,
            "locations": StkLocation.objects.filter(type=StkLocation.TYPE_INTERNE),
        },
    )


# ---------------------------------------------------------------------------
# Mouvements (StkMove)
# ---------------------------------------------------------------------------


@login_required
def move_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        try:
            create_move(
                tenant=tenant,
                variant_id=uuid.UUID(request.POST.get("variant_id", "")),
                qty=Decimal(request.POST.get("qty") or "1"),
                uom=request.POST.get("uom", ""),
                location_from=get_object_or_404(
                    StkLocation, id=request.POST.get("location_from_id")
                ),
                location_to=get_object_or_404(StkLocation, id=request.POST.get("location_to_id")),
                date=parse_date(request.POST.get("date", "")) or timezone.now().date(),
                move_type=request.POST.get("move_type", StkMove.TYPE_AJUSTEMENT),
                source_document=request.POST.get("source_document", ""),
                unit_cost_mga=Decimal(request.POST.get("unit_cost_mga") or "0"),
                operator=user,
            )
        except _EXC as exc:
            error = _error_message(exc)
        else:
            return redirect("stocks:move_list")

    moves = StkMove.objects.filter(is_active=True).order_by("-date", "-created_at")[:200]
    return _render(
        request,
        "moves",
        {
            "moves": moves,
            "move_type_choices": StkMove.MOVE_TYPE_CHOICES,
            "locations": StkLocation.objects.all(),
            "error": error,
        },
    )


@login_required
def move_detail(request: HttpRequest, move_id: str) -> HttpResponse:
    move = get_object_or_404(StkMove, id=move_id)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "validate":
                validate_move(move)
            elif action == "cancel":
                cancel_move(move, reason=request.POST.get("reason", ""))
        except _EXC as exc:
            error = _error_message(exc)
        else:
            return redirect("stocks:move_detail", move_id=move.id)

    return _render(request, "moves", {"move": move, "error": error, "moves": None})


# ---------------------------------------------------------------------------
# Pickings (StkPicking)
# ---------------------------------------------------------------------------


@login_required
def picking_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            create_picking(
                tenant=tenant,
                type=request.POST.get("type", StkPicking.TYPE_INTERNE),
                location_from=get_object_or_404(
                    StkLocation, id=request.POST.get("location_from_id")
                ),
                location_to=get_object_or_404(StkLocation, id=request.POST.get("location_to_id")),
                partner_id=_uuid_or_none(request.POST.get("partner_id", "")),
                date_scheduled=parse_date(request.POST.get("date_scheduled", "")),
                source_document=request.POST.get("source_document", ""),
                carrier=request.POST.get("carrier", ""),
                tracking=request.POST.get("tracking", ""),
            )
        except _EXC as exc:
            error = _error_message(exc)
        else:
            return redirect("stocks:picking_list")

    pickings = StkPicking.objects.filter(is_active=True).order_by("-created_at")[:200]
    return _render(
        request,
        "pickings",
        {
            "pickings": pickings,
            "type_choices": StkPicking.TYPE_CHOICES,
            "locations": StkLocation.objects.all(),
            "error": error,
        },
    )


def _lot_for_add_line(picking: StkPicking, variant_id: uuid.UUID, post: Any) -> StkLot | None:
    """A1 refonte UX (Sprint 6 / L4, cf. docs/planning/2026-refonte-ux-sprints.md
    §5 -- "Réception + lots + DLC/DLUO") : a la reception, cree/recupere le
    lot avec sa DLC/DLUO directement depuis le formulaire d'ajout de ligne
    (plus besoin d'un ecran separe) ; a la sortie/en interne, l'operateur
    reference un lot deja existant par id (typiquement celui suggere par
    `fefo_suggestion` ci-dessous)."""
    lot_id = post.get("lot_id", "").strip()
    if lot_id:
        return get_object_or_404(StkLot, id=uuid.UUID(lot_id))

    lot_name = post.get("lot_name", "").strip()
    if not lot_name:
        return None
    lot, _created = StkLot.objects.get_or_create(
        tenant=picking.tenant,
        variant_id=variant_id,
        name=lot_name,
        defaults={
            "date_production": parse_date(post.get("date_production", "")),
            "date_expiry": parse_date(post.get("date_expiry", "")),
            "supplier_lot": post.get("supplier_lot", ""),
        },
    )
    return lot


@login_required
def picking_detail(request: HttpRequest, picking_id: str) -> HttpResponse:
    picking = get_object_or_404(StkPicking, id=picking_id)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "add_line":
                variant_id = uuid.UUID(post.get("variant_id", ""))
                add_picking_line(
                    picking,
                    variant_id=variant_id,
                    qty=Decimal(post.get("qty") or "1"),
                    uom=post.get("uom", ""),
                    unit_cost_mga=Decimal(post.get("unit_cost_mga") or "0"),
                    lot=_lot_for_add_line(picking, variant_id, post),
                    operator=user,
                )
            elif action == "ready":
                mark_picking_ready(picking)
            elif action == "validate":
                validate_picking(picking)
            elif action == "cancel":
                cancel_picking(picking, reason=post.get("reason", ""))
        except _EXC as exc:
            error = _error_message(exc)
        else:
            return redirect("stocks:picking_detail", picking_id=picking.id)

    return _render(
        request,
        "pickings",
        {
            "picking": picking,
            "lines": picking.moves.select_related("lot").all(),
            "error": error,
            "pickings": None,
        },
    )


@login_required
def fefo_suggestion(request: HttpRequest, picking_id: str) -> HttpResponse:
    """A1 refonte UX (Sprint 6 / L4, cf. docs/planning/2026-refonte-ux-sprints.md
    §5) : expose `services.quants.select_lot_fefo` comme suggestion
    actionnable dans l'ecran de picking plutot que de laisser l'operateur
    deviner un lot au hasard a la sortie. Reste une SUGGESTION -- l'operateur
    reste libre de saisir un autre `lot_id` -- coherent avec la conception
    deliberee de `select_lot_fefo` comme primitive de LECTURE (cf. sa
    docstring : jamais appelee automatiquement par `validate_move`)."""
    picking = get_object_or_404(StkPicking, id=picking_id)
    suggestions: list[dict[str, Any]] = []
    error = None
    variant_id_raw = request.GET.get("variant_id", "")
    if variant_id_raw:
        try:
            allocations = select_lot_fefo(
                uuid.UUID(variant_id_raw),
                location=picking.location_from,
                qty_needed=Decimal(request.GET.get("qty") or "1"),
            )
            lots_by_id = {
                lot.id: lot
                for lot in StkLot.objects.filter(id__in=[a["lot_id"] for a in allocations])
            }
            suggestions = [
                {"lot": lots_by_id[a["lot_id"]], "qty": a["qty"]}
                for a in allocations
                if a["lot_id"] in lots_by_id
            ]
        except (ValueError, ValidationError) as exc:
            error = _error_message(exc)
    return render(
        request, "stocks/_fefo_suggestion.html", {"suggestions": suggestions, "error": error}
    )


# ---------------------------------------------------------------------------
# Mesures physiques (StkMeasurement, RG-STK-4)
# ---------------------------------------------------------------------------


@login_required
def measurement_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        post = request.POST
        try:
            theoretical_raw = post.get("theoretical_value", "")
            record_measurement(
                tenant=tenant,
                type=post.get("type", "longueur"),
                value=Decimal(post.get("value") or "0"),
                uom=post.get("uom", ""),
                theoretical_value=Decimal(theoretical_raw) if theoretical_raw else None,
                device=post.get("device", ""),
                measured_by=user,
                partner_id_for_dispute=_uuid_or_none(post.get("partner_id_for_dispute", "")),
            )
        except _EXC as exc:
            error = _error_message(exc)
        else:
            return redirect("stocks:measurement_create")

    from apps.stocks.models import StkMeasurement

    measurements = StkMeasurement.objects.filter(is_active=True).order_by("-measured_at")[:100]
    return _render(
        request,
        "measurements",
        {"measurements": measurements, "type_choices": StkMeasurement.TYPE_CHOICES, "error": error},
    )


# ---------------------------------------------------------------------------
# Etats qualite (StkQualityState, RG-STK-7)
# ---------------------------------------------------------------------------


@login_required
def quality_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "set_state":
                quant = (
                    get_object_or_404(StkQuant, id=post.get("quant_id"))
                    if post.get("quant_id")
                    else None
                )
                lot = (
                    get_object_or_404(StkLot, id=post.get("lot_id")) if post.get("lot_id") else None
                )
                from apps.stocks.models import StkDefectType

                defect_type = (
                    get_object_or_404(StkDefectType, id=post.get("defect_type_id"))
                    if post.get("defect_type_id")
                    else None
                )
                quality_state = set_quality_state(
                    tenant=tenant,
                    quant=quant,
                    lot=lot,
                    state=post.get("state", StkQualityState.STATE_CONFORME),
                    defect_type=defect_type,
                    defect_qty=Decimal(post.get("defect_qty") or "0"),
                    description=post.get("description", ""),
                    decided_by=user,
                )
                if post.get("relocate_location_id"):
                    apply_quality_decision(
                        quality_state,
                        quarantine_or_scrap_location=get_object_or_404(
                            StkLocation, id=post.get("relocate_location_id")
                        ),
                    )
        except _EXC as exc:
            error = _error_message(exc)
        else:
            return redirect("stocks:quality_list")

    from apps.stocks.models import StkDefectType

    entries = StkQualityState.objects.filter(is_active=True).order_by("-created_at")[:200]
    return _render(
        request,
        "quality",
        {
            "entries": entries,
            "state_choices": StkQualityState.STATE_CHOICES,
            "defect_types": StkDefectType.objects.filter(is_active=True),
            "locations": StkLocation.objects.all(),
            "error": error,
        },
    )


# ---------------------------------------------------------------------------
# Reservations (StkReservation, RG-STK-8)
# ---------------------------------------------------------------------------


@login_required
def reservation_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "reserve":
                quant = get_object_or_404(StkQuant, id=post.get("quant_id"))
                reserve_stock(
                    tenant=tenant,
                    quant=quant,
                    qty=Decimal(post.get("qty") or "0"),
                    date=parse_date(post.get("date", "")) or timezone.now().date(),
                )
            elif action == "release":
                reservation = get_object_or_404(StkReservation, id=post.get("reservation_id"))
                release_reservation(reservation, reason=post.get("reason", ""))
        except _EXC as exc:
            error = _error_message(exc)
        else:
            return redirect("stocks:reservation_list")

    reservations = StkReservation.objects.filter(is_active=True).order_by("-created_at")[:200]
    return _render(request, "reservations", {"reservations": reservations, "error": error})


# ---------------------------------------------------------------------------
# Inventaire (StkInventory/StkInventoryLine, RG-STK-9)
# ---------------------------------------------------------------------------


@login_required
def inventory_list(request: HttpRequest) -> HttpResponse:
    from apps.stocks.models import StkWarehouse

    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            create_inventory(
                tenant=tenant,
                warehouse=get_object_or_404(StkWarehouse, id=request.POST.get("warehouse_id")),
                date=parse_date(request.POST.get("date", "")) or timezone.now().date(),
                type=request.POST.get("type", StkInventory.TYPE_PONCTUEL),
                # STK-6 (L13) : choix explicite a la creation, jamais
                # modifiable ensuite. La case est INVERSEE (L12-3) : ne rien
                # cocher laisse le comptage aveugle, montrer la quantite
                # theorique est l'action explicite. Une case `is_blind`
                # simple faisait de l'absence de choix un devoilement — et
                # tout formulaire qui ne portait pas le champ (API interne,
                # test, script) desactivait la regle en silence.
                is_blind=not request.POST.get("reveal_expected"),
            )
        except _EXC as exc:
            error = _error_message(exc)
        else:
            return redirect("stocks:inventory_list")

    inventories = StkInventory.objects.filter(is_active=True).order_by("-date", "-created_at")[:100]
    return _render(
        request,
        "inventories",
        {
            "inventories": inventories,
            "type_choices": StkInventory.TYPE_CHOICES,
            "warehouses": StkWarehouse.objects.filter(is_active=True),
            "error": error,
        },
    )


@login_required
def inventory_detail(request: HttpRequest, inventory_id: str) -> HttpResponse:
    inventory = get_object_or_404(StkInventory, id=inventory_id)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "add_line":
                add_inventory_line(
                    inventory,
                    variant_id=uuid.UUID(post.get("variant_id", "")),
                    location=get_object_or_404(StkLocation, id=post.get("location_id")),
                )
            elif action == "start":
                start_inventory(inventory)
            elif action == "record_count":
                from apps.stocks.models import StkInventoryLine

                line = get_object_or_404(
                    StkInventoryLine, id=post.get("line_id"), inventory=inventory
                )
                record_count(
                    line,
                    qty_counted=Decimal(post.get("qty_counted") or "0"),
                    counted_by=user,
                    reason=post.get("reason", ""),
                )
            elif action == "validate":
                validate_inventory(inventory, validated_by=user)
            elif action == "cancel":
                cancel_inventory(inventory, reason=post.get("reason", ""))
        except _EXC as exc:
            error = _error_message(exc)
        else:
            return redirect("stocks:inventory_detail", inventory_id=inventory.id)

    return _render(
        request,
        "inventories",
        {
            "inventory": inventory,
            "lines": inventory.lines.all(),
            "error": error,
            "inventories": None,
        },
    )


# ---------------------------------------------------------------------------
# Retours client (StkReturn, STK-RMA1)
# ---------------------------------------------------------------------------


@login_required
def return_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        post = request.POST
        try:
            create_return(
                tenant=tenant,
                partner_id=uuid.UUID(post.get("partner_id", "")),
                variant_id=uuid.UUID(post.get("variant_id", "")),
                qty=Decimal(post.get("qty") or "1"),
                date=parse_date(post.get("date", "")) or timezone.now().date(),
                reason=post.get("reason", ""),
                source_document=post.get("source_document", ""),
            )
        except _EXC as exc:
            error = _error_message(exc)
        else:
            return redirect("stocks:return_list")

    returns = StkReturn.objects.filter(is_active=True).order_by("-created_at")[:200]
    return _render(request, "returns", {"returns": returns, "error": error})


@login_required
def return_detail(request: HttpRequest, return_id: str) -> HttpResponse:
    return_obj = get_object_or_404(StkReturn, id=return_id)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "assess":
                assess_return(
                    return_obj,
                    quality_state=post.get("quality_state", StkReturn.QUALITY_CONFORME),
                    decision=post.get("decision", StkReturn.DECISION_AVOIR),
                )
            elif action == "process":
                process_return(
                    return_obj,
                    location_to=get_object_or_404(StkLocation, id=post.get("location_to_id")),
                    user=user,
                )
            elif action == "cancel":
                cancel_return(return_obj, reason=post.get("reason", ""))
        except _EXC as exc:
            error = _error_message(exc)
        else:
            return redirect("stocks:return_detail", return_id=return_obj.id)

    return _render(
        request,
        "returns",
        {
            "return_obj": return_obj,
            "error": error,
            "returns": None,
            "locations": StkLocation.objects.all(),
            "quality_choices": StkReturn.QUALITY_CHOICES,
            "decision_choices": StkReturn.DECISION_CHOICES,
        },
    )


# ---------------------------------------------------------------------------
# Tracabilite lot (STK-TRAC, acceptance test §5.8.7 n°5)
# ---------------------------------------------------------------------------


@login_required
def traceability_lookup(request: HttpRequest) -> HttpResponse:
    lot_name = request.GET.get("lot_name", "")
    result = None
    lot = None
    if lot_name:
        lot = StkLot.objects.filter(name=lot_name, is_active=True).first()
        if lot is not None:
            result = lot_traceability(lot)
    return _render(request, "traceability", {"lot_name": lot_name, "lot": lot, "result": result})


# ---------------------------------------------------------------------------
# Rappel produit (StkRecall, RG-STK-11, A3)
# ---------------------------------------------------------------------------


@login_required
def recall_declare(request: HttpRequest, lot_id: str) -> HttpResponse:
    tenant = resolve_tenant(request)
    user = cast(User, request.user)
    lot = get_object_or_404(StkLot, id=lot_id, tenant=tenant)
    if request.method == "POST":
        try:
            declare_recall(lot=lot, reason=request.POST.get("reason", ""), initiated_by=user)
        except _EXC as exc:
            return _render(
                request,
                "traceability",
                {
                    "lot_name": lot.name,
                    "lot": lot,
                    "result": lot_traceability(lot),
                    "error": _error_message(exc),
                },
            )
    return redirect("stocks:recall_list")


@login_required
def recall_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    user = cast(User, request.user)
    error = None
    if request.method == "POST" and request.POST.get("action") == "close":
        try:
            recall = get_object_or_404(StkRecall, id=request.POST.get("recall_id"), tenant=tenant)
            close_recall(recall, closed_by=user)
        except _EXC as exc:
            error = _error_message(exc)
        else:
            return redirect("stocks:recall_list")
    recalls = StkRecall.objects.filter(tenant=tenant, is_active=True).order_by("-created_at")
    return _render(request, "recall", {"recalls": recalls, "error": error})


# ---------------------------------------------------------------------------
# Redistribution inter-sites (lecture seule, STK-REDIS1)
# ---------------------------------------------------------------------------


@login_required
def redistribution_view(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    suggestions = suggest_redistribution(tenant)
    return _render(request, "redistribution", {"suggestions": suggestions})


# ---------------------------------------------------------------------------
# Obsolescence / stock dormant (lecture seule, STK-OBS1)
# ---------------------------------------------------------------------------


@login_required
def obsolescence_view(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    rows = dormant_stock_report(tenant)
    # Bloc F, F4 (FOR-15) : greffe en lecture seule dans cet onglet
    # existant plutot qu'un nouvel ecran — budget d'ecrans a 240/240,
    # zero marge. Jamais `check_expiring_lots` (la variante notifiante,
    # reservee a la commande planifiee `run_expiry_alerts`) : un simple
    # affichage ne doit jamais renvoyer une notification a chaque
    # chargement de page.
    expiring_lots = list_expiring_lots(tenant)
    return _render(request, "obsolescence", {"rows": rows, "expiring_lots": expiring_lots})


# ---------------------------------------------------------------------------
# Classification ABC (STK-ABC1)
# ---------------------------------------------------------------------------


@login_required
def abc_view(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None
    if request.method == "POST" and request.POST.get("action") == "recompute":
        try:
            compute_abc_classification(tenant)
        except _EXC as exc:
            error = _error_message(exc)
        else:
            return redirect("stocks:abc_view")

    classifications = StkAbcClassification.objects.filter(is_active=True).order_by("abc_class")
    return _render(request, "abc", {"classifications": classifications, "error": error})


# ---------------------------------------------------------------------------
# Ecran magasinier scan-first (STK-9/STK-10, sprint A6, mode degrade)
# ---------------------------------------------------------------------------


def _resolve_scanned_location(tenant: Tenant, raw: str) -> StkLocation | None:
    """Un lecteur de codes-barres est vu comme un clavier — une valeur
    scannee et une saisie manuelle du CODE produisent la meme chaine en
    entree (cahier §9.1), donc la meme resolution ici : code-barres
    (`services.barcodes.lookup_by_barcode`) d'abord, code d'emplacement
    en repli — restreint aux emplacements INTERNES (un magasinier ne
    receptionne jamais directement sur un emplacement virtuel)."""
    if not raw:
        return None
    location = lookup_by_barcode(tenant, raw)
    if location is not None:
        return location
    return StkLocation.objects.filter(
        tenant=tenant, code=raw, type=StkLocation.TYPE_INTERNE, is_active=True
    ).first()


@login_required
def scan_screen(request: HttpRequest) -> HttpResponse:
    """STK-9/STK-10 (Phase 3 §7.3/§13.1, sprint A6) : ecran magasinier
    mobile-first, scan-first — gabarit `stocks/tw-scan.html`, patron `tw-*`
    autonome (`<c-shell>`, PAS `stocks/index.html`/`active_tab`, deviation
    assumee du reste de ce fichier, cf. plan de session). Seule l'action
    « Recevoir » est cablee de bout en bout dans ce sprint — les 3 autres
    tuiles du cahier (ranger/prelever/compter) restent visibles mais
    desactivees dans le gabarit, ecart de perimetre documente
    explicitement plutot que silencieux."""
    tenant = resolve_tenant(request)
    warehouse_id = request.GET.get("warehouse_id", "")
    location_scan = request.GET.get("location_scan", "")
    warehouse_uuid = _uuid_or_none(warehouse_id)

    warehouses = StkWarehouse.objects.filter(tenant=tenant, is_active=True).order_by("code")
    location_to = _resolve_scanned_location(tenant, location_scan)
    suppliers = (
        StkLocation.objects.filter(
            tenant=tenant, warehouse_id=warehouse_uuid, type=StkLocation.TYPE_FOURNISSEUR
        ).order_by("code")
        if warehouse_uuid is not None
        else StkLocation.objects.none()
    )
    recent_moves = (
        StkMove.objects.filter(
            tenant=tenant, location_to=location_to, move_type=StkMove.TYPE_RECEPTION
        ).order_by("-created_at")[:10]
        if location_to is not None
        else StkMove.objects.none()
    )
    # Panneau "a traiter" (rejeu explicite, cahier §7.3) — les lignes
    # rejetees recentes du tenant, quel que soit l'emplacement, pour que
    # rien ne se perde meme si le magasinier a change de destination
    # entre-temps. Journalisees dans `AuditLog` (pas un modele stocks
    # dedie, cf. docstring `services.scan`) : `tenant_id` y est un UUID
    # simple (pas de FK Django), filtre donc sur `tenant.id`.
    pending_arbitration = AuditLog.objects.filter(
        tenant_id=tenant.id, action=scan.ACTION_REJECTED
    ).order_by("-created_at")[:10]

    return render(
        request,
        "stocks/tw-scan.html",
        {
            "warehouses": warehouses,
            "warehouse_id": warehouse_id,
            "location_scan": location_scan,
            "location_to": location_to,
            "suppliers": suppliers,
            "recent_moves": recent_moves,
            "pending_arbitration": pending_arbitration,
            "today": timezone.now().date().isoformat(),
        },
    )


@login_required
def scan_receive_submit(request: HttpRequest) -> HttpResponse:
    """POST ordinaire (jamais `fetch`) — condition necessaire pour que
    `static/js/offline_queue.js` (deja global, cf. `base.html`) intercepte
    la soumission hors ligne sans code JS specifique a cet ecran (cahier
    §7.3, protocole POS reutilise, H19). Meme garde de permission EXACTE
    que `apps.pos.views.sale_submit` (aucun decorateur de permission dedie
    n'existe pour les vues HTML de ce depot, seulement pour l'API) :
    verification manuelle plutot qu'un nouveau decorateur.

    Redirige TOUJOURS vers l'ecran de scan (succes ou echec) — jamais de
    `?error=` volatil perdu au rechargement suivant comme
    `apps.pos.views.sale_submit` : un rejet est deja journalise
    (`AuditLog` "rejected", cf. `services.scan`) et reste visible dans le panneau
    "a traiter" tant qu'il n'a pas ete corrige par un nouveau scan reussi
    — c'est precisement l'amelioration "reconciliation explicite" que le
    cahier §7.3 demande par rapport au protocole POS existant."""
    if request.method != "POST" or not request.user.has_perm("stocks.add_stkmove"):
        return HttpResponse(status=403)

    tenant = resolve_tenant(request)
    user = cast(User, request.user)
    warehouse_id = request.POST.get("warehouse_id", "")
    location_scan = request.POST.get("location_scan", "")
    redirect_url = f"/stocks/scan/?warehouse_id={warehouse_id}&location_scan={location_scan}"

    try:
        client_uuid = uuid.UUID(request.POST.get("client_uuid", ""))
        location_from = get_object_or_404(StkLocation, id=request.POST.get("location_from_id"))
        location_to = get_object_or_404(StkLocation, id=request.POST.get("location_to_id"))
        scan.sync_scan_reception_line(
            tenant,
            client_uuid=client_uuid,
            location_from=location_from,
            location_to=location_to,
            ean13=request.POST.get("ean13", ""),
            qty=Decimal(request.POST.get("qty") or "1"),
            uom=request.POST.get("uom", "pc"),
            date=parse_date(request.POST.get("date", "")) or timezone.now().date(),
            operator=user,
        )
    except _EXC:
        # Deja journalise (`AuditLog` "rejected") par
        # `sync_scan_reception_line` pour toute erreur de validation —
        # seule une entree de formulaire malformee (client_uuid/qty
        # illisible) echappe au journal, cas limite non atteignable par
        # l'ecran normal (champs generes cote serveur/JS, jamais saisis
        # a la main).
        pass

    return redirect(redirect_url)
