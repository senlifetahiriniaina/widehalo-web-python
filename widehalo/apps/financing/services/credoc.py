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


def create_credoc(
    tenant: Tenant,
    *,
    purchase_order_id: Any,
    bank: str,
    beneficiary: str,
    amount_mga: Decimal,
    validity_date: dt.date,
    currency: str = "MGA",
    advising_bank: str = "",
    log_shipment_id: Any | None = None,
    incoterm: str = "",
    documents_required: list[str] | None = None,
    loan_application: FinLoanApplication | None = None,
) -> FinCredoc:
    if amount_mga <= 0:
        raise ValidationError(_("Le montant du crédit documentaire doit être strictement positif."))
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
        validity_date=validity_date,
        incoterm=incoterm,
        documents_required=documents_required or [],
    )


def _publish_state_changed(credoc: FinCredoc) -> None:
    """INT1 (chantier interactivite native inter-modules) : evenement
    UNIQUE `financing.credoc_state_changed` reutilise par CHAQUE etape du
    cycle de vie RUU 600 (le nouvel etat, deja persiste par l'appelant, est
    porte par `payload["state"]` — un abonne du Studio de workflow visuel
    filtre dessus exactement comme `workflow.transitioned` est deja filtre
    sur `payload.target`, plutot que 4 `event_type` distincts pour la meme
    machine a etats lineaire)."""
    from apps.core.events import publish_event

    publish_event(
        "financing.credoc_state_changed",
        {
            "credoc_id": str(credoc.id),
            "reference": credoc.reference,
            "state": credoc.state,
        },
        tenant_id=str(credoc.tenant_id),
    )


def open_credoc(credoc: FinCredoc, user: User) -> None:
    attempt_transition(credoc, "open", user)
    credoc.save(update_fields=["state"])
    _publish_state_changed(credoc)


def receive_documents(credoc: FinCredoc, user: User) -> None:
    attempt_transition(credoc, "receive_documents", user)
    credoc.save(update_fields=["state"])
    _publish_state_changed(credoc)


def pay_credoc(credoc: FinCredoc, user: User) -> None:
    attempt_transition(credoc, "pay", user)
    credoc.save(update_fields=["state"])
    _publish_state_changed(credoc)


def close_credoc(credoc: FinCredoc, user: User) -> None:
    attempt_transition(credoc, "close", user)
    credoc.save(update_fields=["state"])
    _publish_state_changed(credoc)
