"""FIN2 — suretes (`FinGuarantee`) rattachees a un dossier de financement,
regle de couverture >= 120% verifiee en service (jamais un blocage a la
creation, cf. docstring `models.py::FinGuarantee`)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.document import Document
from apps.core.models.user import User
from apps.core.services.documents import store_document
from apps.core.services.sequences import next_reference
from apps.financing.models import FinGuarantee, FinLoanApplication

# Ratio observe au cadrage (cf. plan, "valeur estimee >= 120% du credit —
# regle observee") : pas de reference chiffree unique dans le document
# source pour ce coefficient exact, retenu tel quel comme le plan le
# demande explicitement.
GUARANTEE_COVERAGE_RATIO = Decimal("1.20")


def add_guarantee(
    application: FinLoanApplication,
    *,
    type: str,  # noqa: A002 — coherent avec le champ CDC `FinGuarantee.type`
    estimated_value_mga: Decimal,
    asset_description: str = "",
) -> FinGuarantee:
    if estimated_value_mga <= 0:
        raise ValidationError(_("La valeur estimee d'une surete doit etre strictement positive."))
    reference = next_reference(application.tenant, "FINGUAR", timezone.now().year)
    return FinGuarantee.objects.create(
        tenant=application.tenant,
        reference=reference,
        loan_application=application,
        type=type,
        asset_description=asset_description,
        estimated_value_mga=estimated_value_mga,
    )


def attach_legal_document(
    guarantee: FinGuarantee, *, uploaded_file: UploadedFile[Any], uploaded_by: User | None = None
) -> Document:
    """Piece jointe juridique (titre de propriete, acte de nantissement...)
    — passe-plat vers `core.services.documents.store_document`, aucune
    logique de stockage propre a `financing` (regle "un seul mecanisme de
    document" deja appliquee partout ailleurs dans ce depot)."""
    return store_document(
        tenant=guarantee.tenant,
        uploaded_file=uploaded_file,
        uploaded_by=uploaded_by,
        content_object=guarantee,
    )


def check_guarantee_coverage(application: FinLoanApplication) -> dict[str, Any]:
    """Diagnostic (jamais un blocage) : la somme des `estimated_value_mga`
    des suretes ACTIVES du dossier couvre-t-elle au moins `amount_requested_
    mga * GUARANTEE_COVERAGE_RATIO` (120% par defaut) ? Denominateur nul
    exclu par construction (`FinLoanApplication.amount_requested_mga` est
    toujours strictement positif, cf. `create_loan_application`)."""
    total_value = Decimal(0)
    for guarantee in application.guarantees.filter(is_active=True):
        total_value += guarantee.estimated_value_mga
    required = application.amount_requested_mga * GUARANTEE_COVERAGE_RATIO
    ratio = (
        (total_value / application.amount_requested_mga)
        if application.amount_requested_mga
        else None
    )
    return {
        "total_guarantee_value_mga": total_value,
        "required_value_mga": required,
        "coverage_ratio": ratio,
        "is_covered": total_value >= required,
    }
