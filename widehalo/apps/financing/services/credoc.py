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
