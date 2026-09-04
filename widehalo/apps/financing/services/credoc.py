"""FIN3 — credit documentaire a l'importation (`FinCredoc`), workflow RUU
600 lineaire `demande -> ouvert -> documents_recus -> paye -> clos`.

Discipline `attempt_transition` (garde-fou architecture, `tests/
architecture/test_attempt_transition_saves_state.py`) : chaque fonction
appelle `credoc.save(update_fields=[...])` en incluant `"state"` juste
apres `attempt_transition(...)`, jamais dans la methode `@transition`
elle-meme."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.sequences import next_reference
from apps.core.services.workflow import attempt_transition
from apps.financing.models import FinCredoc, FinLoanApplication

# Ecart de change juge materiel a partir de ce seuil (%, valeur absolue) —
# seuil assume et disclosed, le CDC ne fixe aucun chiffre pour "l'alerte
# sur ecart de change Ariary" (T3). Meme discipline que DEFAULT_WINDOW_DAYS
# de `stocks.services.consistency` : un defaut documente plutot qu'un
# silence du cahier des charges laisse a interpreter au hasard.
FX_VARIANCE_ALERT_THRESHOLD_PCT = Decimal("2")


def create_credoc(
    tenant: Tenant,
    *,
    purchase_order_id: Any,
    bank: str,
    beneficiary: str,
    amount_mga: Decimal,
    validity_date: dt.date,
    currency: str = "MGA",
    amount_foreign: Decimal | None = None,
    advising_bank: str = "",
    log_shipment_id: Any | None = None,
    incoterm: str = "",
    documents_required: list[str] | None = None,
    loan_application: FinLoanApplication | None = None,
) -> FinCredoc:
    if amount_mga <= 0:
        raise ValidationError(_("Le montant du crédit documentaire doit être strictement positif."))
    if currency != "MGA" and not amount_foreign:
        raise ValidationError(
            _(
                "Le montant en devise d'origine est requis pour un crédit documentaire "
                "libellé dans une devise autre que MGA (suivi de l'écart de change, T3)."
            )
        )
    reference = next_reference(tenant, "FINCREDOC", validity_date.year)
    return FinCredoc.objects.create(
        tenant=tenant,
        reference=reference,
        loan_application=loan_application,
        purchase_order_id=purchase_order_id,
        log_shipment_id=log_shipment_id,
        bank=bank,
        advising_bank=advising_bank,
        beneficiary=beneficiary,
        amount_mga=amount_mga,
        currency=currency,
        amount_foreign=amount_foreign,
        validity_date=validity_date,
        incoterm=incoterm,
        documents_required=documents_required or [],
    )


def credoc_fx_variance(credoc: FinCredoc, *, as_of: dt.date | None = None) -> dict[str, Any] | None:
    """T3 : "alerte sur écart de change Ariary" — reconvertit
    `amount_foreign` au taux `as_of` (aujourd'hui par défaut) et compare
    au montant MGA constaté à l'ouverture (`amount_mga`, jamais
    recalculé). Retourne `None`, jamais une exception, pour un CREDOC
    libellé en MGA (aucun risque de change) ou sans `amount_foreign`
    renseigné — cas normal, pas une erreur.

    `is_material` : `True` si l'écart absolu dépasse
    `FX_VARIANCE_ALERT_THRESHOLD_PCT` — c'est ce champ, pas la simple
    présence d'un écart non nul (quasi toujours vrai en change flottant),
    que l'écran doit utiliser pour décider d'afficher une alerte visible
    plutôt qu'une simple information."""
    if credoc.currency == "MGA" or not credoc.amount_foreign:
        return None

    from apps.accounting.services.public import convert_amount_to_mga

    as_of = as_of or dt.date.today()
    current_amount_mga = convert_amount_to_mga(
        credoc.amount_foreign, credoc.currency, as_of, tenant=credoc.tenant
    )
    variance_mga = current_amount_mga - credoc.amount_mga
    variance_pct = (
        (variance_mga / credoc.amount_mga * Decimal(100)) if credoc.amount_mga else Decimal(0)
    )
    return {
        "booked_amount_mga": credoc.amount_mga,
        "current_amount_mga": current_amount_mga,
        "variance_mga": variance_mga,
        "variance_pct": variance_pct,
        "is_material": abs(variance_pct) >= FX_VARIANCE_ALERT_THRESHOLD_PCT,
    }


def _publish_state_changed(credoc: FinCredoc, *, reason: str) -> None:
    """INT1 (chantier interactivite native inter-modules) : evenement
    UNIQUE `financing.credoc_state_changed` reutilise par CHAQUE etape du
    cycle de vie RUU 600 (le nouvel etat, deja persiste par l'appelant, est
    porte par `payload["state"]` — un abonne du Studio de workflow visuel
    filtre dessus exactement comme `workflow.transitioned` est deja filtre
    sur `payload.target`, plutot que 4 `event_type` distincts pour la meme
    machine a etats lineaire). `reason` (B2, motif obligatoire desormais
    exige par chaque transition ci-dessous) rejoint le payload — meme
    discipline que `purchase.dispute_opened`/`logistics.shipment_blocked`,
    qui portent deja leur motif dans l'evenement publie."""
    from apps.core.events import publish_event

    publish_event(
        "financing.credoc_state_changed",
        {
            "credoc_id": str(credoc.id),
            "reference": credoc.reference,
            "state": credoc.state,
            "reason": reason,
        },
        tenant_id=str(credoc.tenant_id),
    )


def credoc_transition_history(credoc: FinCredoc) -> list[dict[str, Any]]:
    """B2 (Phase 3, "chronologie unifiée CREDOC/import/coût débarqué", cf.
    plan) : historique DES transitions réellement effectuées pour ce
    CREDOC, motif inclus — lit directement `core.StateTransitionLog`
    (journal générique déjà alimenté automatiquement par le signal
    `django_fsm.post_transition`, cf. `apps.core.workflows`), jamais un
    champ dédié sur `FinCredoc` : le cycle RUU 600 est linéaire, un seul
    historique ordonné suffit, pas de "motif courant" à afficher
    séparément (à la différence de `PurOrder.cancel_reason`/
    `LogShipment.block_reason`, qui existent pour un état ATTEINT et
    persistant, jamais le cas ici). Exclut les tentatives refusées
    (`was_refused=True`) — seules les VRAIES transitions effectuées
    intéressent la frise chronologique, un refus de permission n'est pas
    un évènement du dossier.

    Retourne des dicts primitifs `{"at", "from_state", "to_state",
    "reason", "performed_by"}`, triés chronologiquement. Liste vide,
    jamais une exception, si ce CREDOC n'a encore subi aucune
    transition."""
    from django.contrib.contenttypes.models import ContentType

    from apps.core.models.workflow import StateTransitionLog

    content_type = ContentType.objects.get_for_model(FinCredoc)
    logs = StateTransitionLog.objects.filter(
        content_type=content_type, object_id=str(credoc.id), was_refused=False
    ).order_by("created_at")
    return [
        {
            "at": log.created_at,
            "from_state": log.from_state,
            "to_state": log.to_state,
            "reason": log.comment,
            "performed_by": log.performed_by.email if log.performed_by is not None else "",
        }
        for log in logs
    ]


def _require_reason(reason: str, message: str) -> None:
    if not reason:
        raise ValidationError(message)


def open_credoc(credoc: FinCredoc, user: User, *, reason: str) -> None:
    """B2 : motif désormais OBLIGATOIRE et journalisé (`StateTransitionLog.
    comment`, via `attempt_transition(..., comment=reason)`) sur les 4
    transitions du cycle RUU 600 — le plan exige "chaque transition CREDOC
    exige un motif obligatoire journalisé", sans exception par étape."""
    _require_reason(reason, _("Un motif est obligatoire pour ouvrir un crédit documentaire."))
    attempt_transition(credoc, "open", user, comment=reason)
    credoc.save(update_fields=["state"])
    _publish_state_changed(credoc, reason=reason)


def receive_documents(credoc: FinCredoc, user: User, *, reason: str) -> None:
    _require_reason(reason, _("Un motif est obligatoire pour marquer les documents comme reçus."))
    attempt_transition(credoc, "receive_documents", user, comment=reason)
    credoc.save(update_fields=["state"])
    _publish_state_changed(credoc, reason=reason)


def pay_credoc(credoc: FinCredoc, user: User, *, reason: str) -> None:
    _require_reason(reason, _("Un motif est obligatoire pour marquer un crédit documentaire payé."))
    attempt_transition(credoc, "pay", user, comment=reason)
    credoc.save(update_fields=["state"])
    _publish_state_changed(credoc, reason=reason)


def close_credoc(credoc: FinCredoc, user: User, *, reason: str) -> None:
    _require_reason(reason, _("Un motif est obligatoire pour clôturer un crédit documentaire."))
    attempt_transition(credoc, "close", user, comment=reason)
    credoc.save(update_fields=["state"])
    _publish_state_changed(credoc, reason=reason)


def build_dossier_timeline(credoc: FinCredoc) -> dict[str, Any]:
    """B2 (Phase 3, "chronologie unifiée CREDOC/import/coût débarqué", cf.
    plan) : agrège, EN LECTURE SEULE, tout ce qui est connu du dossier
    d'importation ancré par ce CREDOC (`credoc.purchase_order_id`) — la
    commande d'achat elle-même (`purchase.services.public.
    get_order_summary`), les expéditions qui la transportent et leurs
    dossiers douaniers (`logistics.services.public.
    list_shipments_for_purchase_order`), et l'historique de CE CREDOC
    (`credoc_transition_history` ci-dessus). Aucun accès direct à un
    modèle `purchase`/`logistics`, uniquement leurs `services.public`
    respectifs (règle de couplage n°1) — `financing` est le SEUL des
    trois modules à déclarer une dépendance vers les DEUX autres
    (`apps/financing/module.py`), ce qui en fait le seul emplacement
    architecturalement cohérent pour cette agrégation (`purchase` ->
    `financing` ou `logistics` -> `financing` créerait un cycle, puisque
    `financing` dépend déjà des deux).

    Construit aussi `events` : la fusion, triée chronologiquement, de TOUS
    les évènements datés du dossier (transitions CREDOC, transitions de
    chaque expédition, ouverture/dédouanement/clôture de chaque dossier
    douanier) — la "frise chronologique" demandée par le plan, une simple
    liste triée de dicts primitifs `{"at", "source", "label"}`, jamais un
    nouveau modèle (aucune persistance nécessaire, tout est déjà
    matérialisé ailleurs : `StateTransitionLog`/`LogCustomsFile` restent
    l'unique source de vérité, cette fonction ne fait que les relire et
    les ordonner)."""
    from apps.logistics.services.public import list_shipments_for_purchase_order
    from apps.purchase.services.public import get_order_summary

    order = get_order_summary(credoc.purchase_order_id)
    shipments = list_shipments_for_purchase_order(credoc.purchase_order_id)
    credoc_history = credoc_transition_history(credoc)

    events: list[dict[str, Any]] = [
        {"at": credoc.created_at, "source": "credoc", "label": _("Crédit documentaire créé")}
    ]
    for entry in credoc_history:
        events.append(
            {
                "at": entry["at"],
                "source": "credoc",
                "label": f"{entry['from_state']} → {entry['to_state']} : {entry['reason']}",
            }
        )
    for shipment in shipments:
        for entry in shipment["history"]:
            events.append(
                {
                    "at": entry["at"],
                    "source": "shipment",
                    "label": (
                        f"{shipment['reference']} : {entry['from_state']} → "
                        f"{entry['to_state']} ({entry['reason']})"
                    ),
                }
            )
        for customs_file in shipment["customs_files"]:
            if customs_file["opened_at"]:
                events.append(
                    {
                        "at": customs_file["opened_at"],
                        "source": "customs",
                        "label": f"{customs_file['reference']} — {_('dossier douanier ouvert')}",
                    }
                )
            if customs_file["cleared_at"]:
                events.append(
                    {
                        "at": customs_file["cleared_at"],
                        "source": "customs",
                        "label": f"{customs_file['reference']} — {_('marchandise dédouanée')}",
                    }
                )
            if customs_file["closed_at"]:
                landed_cost_suffix = (
                    f" ({_('coût débarqué appliqué')})"
                    if customs_file["landed_cost_batch_id"]
                    else ""
                )
                events.append(
                    {
                        "at": customs_file["closed_at"],
                        "source": "customs",
                        "label": (
                            f"{customs_file['reference']} — {_('dossier douanier clôturé')}"
                            f"{landed_cost_suffix}"
                        ),
                    }
                )
    events.sort(key=lambda event: _timeline_sort_key(event["at"]))

    return {
        "order": order,
        "shipments": shipments,
        "credoc_history": credoc_history,
        "events": events,
    }


def _timeline_sort_key(value: dt.date | dt.datetime) -> dt.datetime:
    """`build_dossier_timeline` mélange des `datetime` (`StateTransitionLog.
    created_at`) et de simples `date` (`LogCustomsFile.opened_at`/
    `cleared_at`/`closed_at`) dans une même liste triée — Python refuse de
    comparer directement les deux types (`TypeError`). Normalise toute
    `date` en `datetime` à minuit UTC pour rendre le tri possible ; un
    `datetime` déjà timezone-aware (garanti par `USE_TZ=True`) traverse
    inchangé."""
    if isinstance(value, dt.datetime):
        return value
    return dt.datetime.combine(value, dt.time.min, tzinfo=dt.UTC)
