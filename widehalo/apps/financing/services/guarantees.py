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


def flag_guarantee_coverage_risk(
    application: FinLoanApplication, *, owner: User, mitigation_plan: str = ""
) -> Any:
    """INT3 (chantier interactivite native inter-modules) : materialise un
    `RiskItem` generique (`core.services.risk.create_risk_item`, RSK1-2)
    quand les suretes ACTIVES d'un dossier ne couvrent PAS encore
    `GUARANTEE_COVERAGE_RATIO` (120%) — reutilise DIRECTEMENT
    `check_guarantee_coverage` ci-dessus (deja enveloppe cote advisor par
    `apps.financing.services.ai_advisor_registration._advise_on_financing`,
    INT2), AUCUN second calcul divergent. Retourne `None` (jamais
    d'exception) si le dossier EST deja couvert — un dossier normalement
    garanti est le cas ATTENDU, pas une erreur d'appel.

    **Jamais automatique sur chaque creation de surete** : `add_guarantee`
    ci-dessus n'appelle JAMAIS cette fonction — ajouter une surete est une
    operation de routine (un dossier commence forcement sous-couvert avant
    sa premiere surete), la declencher a CHAQUE `add_guarantee` noierait le
    registre. Point d'entree explicite (vue/action manuelle, ou
    verification periodique avant decision bancaire) a appeler quand on
    veut suivre formellement un risque de contrepartie deja diagnostique
    par `check_guarantee_coverage`.

    Score assume : `impact=5` (un credit insuffisamment garanti expose
    l'entreprise a une perte totale de la surete en cas de defaut,
    impact maximal) ; `likelihood=3` (risque "moyen" tant que le dossier
    n'est pas encore accepte — une insuffisance de couverture reste
    corrigible avant decision, contrairement a un litige fournisseur deja
    materialise). Score = 15, exactement au seuil `HIGH_SCORE_THRESHOLD`
    (publie `risk.flagged`) — une couverture insuffisante merite toujours
    l'alerte transverse, jamais un simple risque "bas bruit". `owner` doit
    etre fourni par l'appelant (`FinLoanApplication` ne porte aucun champ
    utilisateur exploitable, cf. `models.py`)."""
    coverage = check_guarantee_coverage(application)
    if coverage["is_covered"]:
        return None

    from apps.core.models.risk import CATEGORY_FINANCIAL
    from apps.core.services.risk import create_risk_item

    return create_risk_item(
        tenant=application.tenant,
        category=CATEGORY_FINANCIAL,
        likelihood=3,
        impact=5,
        owner=owner,
        mitigation_plan=mitigation_plan,
        content_object=application,
    )
