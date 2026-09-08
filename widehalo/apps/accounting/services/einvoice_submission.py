"""T4 (bloc C, EFA-1 à EFA-5) — soumettre une facture, ou dire pourquoi non.

**Le mode d'attente EST le livrable, pas une dégradation.** Le cahier le
dit sans ambiguïté sur le risque P4-R1 : « le moteur de conformité est
réputé **complet** lorsqu'il produit, archive et met en file un document
normalisé **sans qu'aucune plateforme ne soit joignable**, et lorsqu'il
rejoue cette file sans perte le jour de l'ouverture ». Et EFA-2 précise ce
que l'utilisateur doit voir dans ce cas : « aucune erreur n'est présentée
à l'utilisateur, et un bandeau indique l'état d'attente ».

C'est pourquoi `submit_invoice` ne lève PAS quand aucun raccordement n'est
ouvert. Elle produit, signe si elle peut, archive, met en file, et rend un
compte rendu qui dit où en est la pièce. Le seul refus dur est celui
qu'EFA-1 exige — un champ obligatoire manquant — et il désigne le champ.

**Ce que ce module ne fait pas, et c'est délibéré.**

- *Il ne touche pas `invoice_state`.* Le lot T3 a tranché la lecture, et
  T4 en vit : le blocage porte sur la SOUMISSION, jamais sur la validité
  comptable de la facture. Une facture invendable au fisc reste due,
  réglable et publiée.
- *Il n'appelle aucun tiers.* La règle de couplage n°1 l'interdit, et
  FLX-2 en dépend. Tout part par le hub, qui draine plus tard.
- *Il ne rouvre jamais un échange rejeté* (EFA-5). Une correction produit
  un ÉCHANGE NEUF ; la machine à états du hub le garantit déjà en base —
  `STATE_REJECTED` est terminal, sans transition sortante — et ce module
  ne tente pas de la contourner.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.utils import timezone

from apps.accounting.services.einvoice_completeness import (
    CompletenessReport,
    is_submittable_type,
    submission_blockers,
)
from apps.accounting.services.einvoice_profile import get_profile

if TYPE_CHECKING:
    from apps.accounting.models import AccMove

#: Le code du connecteur fiscal. Une liaison absente ou inactive n'est pas
#: une erreur : c'est le mode d'attente, et c'est le livrable.
CONNECTOR_CODE = "efacture"

#: Le type de pièce sous lequel le hub range ces échanges — même convention
#: que partout ailleurs (`app_label.NomDeModele`), pour que la console
#: retrouve la facture en un clic et réciproquement (CON-1).
DOCUMENT_TYPE = "accounting.AccMove"

#: Ce qui fait qu'une soumission ne part pas. Trois raisons, et un écran
#: les présente différemment : la première n'appelle aucune action, la
#: deuxième en appelle une de l'exploitant, la troisième du comptable.
OUTCOME_NOT_CONCERNED = "hors_champ"
OUTCOME_NO_PROFILE = "pays_sans_profil"
OUTCOME_INCOMPLETE = "mentions_manquantes"
#: Ce qui fait qu'elle part — ou qu'elle attend de partir.
OUTCOME_QUEUED = "en_file"
OUTCOME_WAITING_FOR_LINK = "attente_raccordement"


@dataclass(frozen=True)
class SubmissionResult:
    """Ce qu'il est advenu de la soumission. Jamais une exception pour les
    cas normaux — dont l'absence de raccordement fait partie."""

    outcome: str
    report: CompletenessReport | None = None
    exchange_id: Any = None
    signed: bool = False
    archived: bool = False

    @property
    def is_blocked(self) -> bool:
        """Vrai seulement quand quelqu'un doit AGIR.

        « Hors du champ » n'est pas un blocage : une écriture diverse n'a
        jamais eu vocation à partir. « En attente de raccordement » non
        plus : le document est produit et archivé, il attend une ouverture
        qui ne dépend pas de l'utilisateur."""
        return self.outcome in {OUTCOME_NO_PROFILE, OUTCOME_INCOMPLETE}


def submit_invoice(move: AccMove, *, now: dt.datetime | None = None) -> SubmissionResult:
    """Produit, signe, archive et met en file — ou dit pourquoi non.

    Ne lève JAMAIS pour une absence de raccordement : c'est le mode
    d'attente du cahier, et EFA-2 interdit d'y présenter une erreur."""
    from apps.accounting.models import AccMove

    if not is_submittable_type(move):
        return SubmissionResult(outcome=OUTCOME_NOT_CONCERNED)

    rapport = submission_blockers(move)
    if rapport.no_profile:
        return SubmissionResult(outcome=OUTCOME_NO_PROFILE, report=rapport)
    if not rapport.can_submit:
        # EFA-1 : « bloque la soumission et désigne le champ, SANS
        # invalider la facture ». Rien n'est écrit sur la pièce ici — pas
        # même `fiscal_state`, qui dirait un état que la facture pourrait
        # quitter par une simple correction de fiche tiers.
        return SubmissionResult(outcome=OUTCOME_INCOMPLETE, report=rapport)

    maintenant = now or timezone.now()
    profil = get_profile(move.tenant.country_code or "")
    assert profil is not None  # garanti par `no_profile` ci-dessus  # noqa: S101

    document = build_structured_document(move)
    octets = canonical_bytes(document)

    signature = _sign_or_none(move, octets)
    archive = _archive(move, octets)

    corps = canonical_bytes({"document": document, "signature": signature}).decode("utf-8")
    echange = _queue(move, corps, profil.archive_years, maintenant)

    move.fiscal_state = (
        AccMove.FISCAL_STATE_AWAITING if echange is not None else AccMove.FISCAL_STATE_TO_SUBMIT
    )
    move.save(update_fields=["fiscal_state"])

    return SubmissionResult(
        outcome=OUTCOME_QUEUED if echange is not None else OUTCOME_WAITING_FOR_LINK,
        report=rapport,
        exchange_id=echange,
        signed=signature is not None,
        archived=archive,
    )


def canonical_bytes(payload: Any) -> bytes:
    """La forme d'octets d'un document, STABLE et explicite.

    **La signature porte sur ces octets exacts** (EFA-2, EFA-8) : deux
    rendus différents du même document produiraient deux signatures
    différentes, et une vérification faite plus tard échouerait sans que
    rien ne dise pourquoi. Trois choix, tous nécessaires à cette
    stabilité :

    - `sort_keys` : l'ordre d'insertion d'un dictionnaire Python est un
      détail d'implémentation du code qui l'a construit, pas une propriété
      du document.
    - `ensure_ascii=False` : une raison sociale malgache porte des accents,
      et les échapper en `\\uXXXX` gonflerait la charge utile sans rien
      apporter — l'encodage est UTF-8, déclaré.
    - `separators` sans espace : un rendu compact ne dépend d'aucun réglage
      d'agrément.

    **Le convertisseur est NOMMÉ plutôt que `default=str`.** Une date rendue
    par `str()` donne « 2026-01-15 » aujourd'hui, mais rien ne le garantit
    pour un `datetime` (« 2026-01-15 08:30:00+00:00 », avec un espace au
    milieu) ni pour un `Decimal` en notation exponentielle. Sur un document
    soumis à une administration et signé, laisser le format dépendre du
    `__str__` d'un type est le genre de dépendance implicite qui se
    découvre le jour d'un contrôle."""
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_render_value,
    ).encode("utf-8")


def _render_value(valeur: Any) -> str:
    """Rend ce que `json` ne sait pas rendre — sans jamais deviner.

    Un type inattendu LÈVE plutôt que d'être rendu par son `repr` : un
    objet qui partirait vers une administration sous la forme
    `<AccAccount: 411100>` serait à la fois illisible et une fuite (§9.2
    interdit précisément le numéro de compte complet)."""
    if isinstance(valeur, dt.datetime):
        return valeur.isoformat()
    if isinstance(valeur, dt.date):
        return valeur.isoformat()
    if isinstance(valeur, Decimal):
        # `format(..., "f")` évite la notation exponentielle que `str()`
        # produit sur les très grands et très petits nombres.
        return format(valeur, "f")
    if isinstance(valeur, UUID):
        return str(valeur)
    raise TypeError(
        f"Type non sérialisable dans un document soumis : {type(valeur).__name__}. "
        "Ajouter un rendu explicite plutôt que de laisser `str()` décider."
    )


def build_structured_document(move: AccMove) -> dict[str, Any]:
    """La pièce, dans la forme que la soumission transporte.

    **Construit depuis la projection déclarée du lot T0**, jamais à la
    main : `flow_schema_registration.build_move` sait déjà quels champs ont
    le droit de sortir et lesquels sont refusés par le §9.2 — le numéro de
    compte complet en tête. Reconstruire un dictionnaire ici en recopiant
    des noms de champs contournerait cette déclaration sans qu'aucune garde
    ne s'en aperçoive, et c'est exactement le défaut que T0 existait pour
    fermer.

    L'identité fiscale des deux parties s'y ajoute — la projection décrit
    la pièce, pas les parties — et c'est ce qu'EFA-1 exige des deux côtés."""
    from apps.accounting.services.flow_schema_registration import build_move
    from apps.partners.services.public import get_partner_fiscal_identity

    piece = build_move(move.id) or {}
    tenant = move.tenant
    tiers = get_partner_fiscal_identity(move.partner_id) if move.partner_id else {}
    return {
        "piece": piece,
        "emetteur": {
            "name": tenant.name,
            "nif": tenant.nif,
            "stat": tenant.stat,
            "address": tenant.address,
            "country_code": tenant.country_code,
        },
        "client": {
            "name": tiers.get("name", ""),
            "nif": tiers.get("nif", ""),
            "stat": tiers.get("stat", ""),
        },
    }


def _sign_or_none(move: AccMove, octets: bytes) -> dict[str, Any] | None:
    """Signe si un certificat est fourni ; laisse passer sinon.

    Le refus d'un certificat PÉRIMÉ remonte, lui : `sign_document` lève, et
    on ne l'absorbe pas — EFA-8 demande que la soumission soit « refusée
    avant d'être émise », donc avant l'archivage et la mise en file."""
    from apps.flows.services.public import sign_document

    return sign_document(move.tenant, connector_code=CONNECTOR_CODE, payload=octets)


def _archive(move: AccMove, octets: bytes) -> bool:
    """Archive le document SOUMIS, distinct de la représentation lisible.

    Deux documents et non un, et c'est une décision : RPT-9 impose que le
    PDF d'une facture ne soit produit qu'une fois et resservi
    octet-pour-octet, tandis qu'EFA-4 exige que « l'identifiant attribué et
    le marquage vérifiable soient reportés sur la représentation lisible ».
    Les deux ne peuvent pas être vrais du même fichier. Ce qui est archivé
    ici est ce qui PART — figé, signé, jamais retouché ; le marquage ira
    sur la représentation remise au client, produite quand le verdict
    arrive."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.core.services.documents import store_document

    fichier = SimpleUploadedFile(
        f"{move.reference or move.pk}-soumission.json", octets, content_type="application/json"
    )
    store_document(tenant=move.tenant, uploaded_file=fichier, uploaded_by=None, content_object=move)
    return True


def _queue(move: AccMove, corps: str, archive_years: int, now: dt.datetime) -> Any:
    """Met en file si un raccordement est ouvert ; rend `None` sinon.

    `None` n'est pas un échec : c'est le mode d'attente. Le document est
    déjà produit, signé et archivé au moment où l'on arrive ici — c'est
    exactement l'ordre qu'EFA-2 décrit.

    **Tout passe par `flows.services.public`, et une garde l'exige.** La
    première rédaction de cette fonction importait `flows.models` et
    `flows.services.queue` pour construire l'échange elle-même ; la règle
    de couplage n°1 l'interdit et `test_module_boundaries` l'a refusé. Ce
    n'est pas une question de style : un module métier qui sait construire
    un échange peut en construire un que le registre du hub n'a pas
    validé, et le socle de flux existe pour que cela soit impossible.

    Ce module dit donc ce qu'il veut — « faire valider cette pièce » — et
    ignore la liaison, la préparation et la file."""
    from apps.flows.services.public import submit_document_for_verdict

    echange = submit_document_for_verdict(
        move.tenant,
        connector_code=CONNECTOR_CODE,
        document_type=DOCUMENT_TYPE,
        document_id=move.id,
        body=corps,
        # EFA-7 : la durée d'archivage bascule avec le pays. La colonne
        # existait sur `FlwPayload` depuis S1 en attendant ce premier
        # appelant.
        retain_until=(now + dt.timedelta(days=365 * archive_years)).date(),
    )
    return echange["id"] if echange is not None else None


__all__ = [
    "CONNECTOR_CODE",
    "canonical_bytes",
    "DOCUMENT_TYPE",
    "OUTCOME_INCOMPLETE",
    "OUTCOME_NOT_CONCERNED",
    "OUTCOME_NO_PROFILE",
    "OUTCOME_QUEUED",
    "OUTCOME_WAITING_FOR_LINK",
    "SubmissionResult",
    "build_structured_document",
    "submit_invoice",
]
