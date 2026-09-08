"""T4 (bloc C, EFA-1) — ce qui manque pour soumettre, nommé champ par champ.

**Le critère, mot pour mot** : « Une facture validée produit un document
structuré conforme au schéma paramétré, contrôlé avant soumission ; un
champ obligatoire manquant **bloque la soumission et désigne le champ,
sans invalider la facture**. »

Les trois moitiés de cette phrase sont trois décisions, et aucune n'est
évidente.

**« Bloque la soumission »** — pas la validation, pas la publication, pas
l'impression. Une facture incomplète au sens fiscal reste une facture
parfaitement valide au sens comptable : elle est publiée, elle est due,
elle se règle. Le lot T3 a déjà tranché cette lecture contre la prose du
cahier (l.224, qui parle de « validation ») au motif que le critère
prévaut. C'est ici que la conséquence se voit : aucune fonction de ce
module n'appelle `validate_invoice` ni ne touche `invoice_state`.

**« Désigne le champ »** — un code technique ne désigne rien pour un
comptable. Le rapport rend le LIBELLÉ porté par le profil pays, qui
bascule avec le pays (EFA-7) au même titre que la liste elle-même.

**« Sans invalider »** — le rapport est une LECTURE. Il ne modifie aucune
pièce, ne lève aucune exception sur une facture incomplète, et peut être
demandé autant de fois qu'on veut. Une facture se corrige et se
re-contrôle ; refuser en levant obligerait chaque appelant à envelopper
son appel dans un `try`, ce qui finirait par masquer autre chose.

**Le tiers est lu par le contrat public de `partners`**, jamais par son
modèle : `accounting` ne peut pas importer `partners.models` (règle de
couplage n°1), et le lot T3 a livré `get_partner_fiscal_identity`
exactement pour cet appelant-ci.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from django.utils.functional import Promise

from apps.accounting.services.einvoice_profile import (
    EInvoiceProfile,
    get_profile,
)

if TYPE_CHECKING:
    from apps.accounting.models import AccMove

#: Les natures de pièce qu'un dispositif à contrôle continu attend. Une
#: facture FOURNISSEUR n'est pas soumise par nous — c'est son émetteur qui
#: la soumet, et la soumettre à notre tour créerait un doublon chez
#: l'administration. L'avoir client, lui, en fait partie : le §14.3 range
#: explicitement « l'annulation et l'avoir » dans le périmètre.
SUBMITTABLE_MOVE_TYPES: frozenset[str] = frozenset({"customer_invoice", "customer_credit_note"})


@dataclass(frozen=True)
class MissingField:
    """Un champ exigé que la pièce ne porte pas.

    Porte le code ET le libellé : le premier pour qu'un écran sache où
    renvoyer l'utilisateur, le second pour que le message soit lisible."""

    code: str
    label: str | Promise
    origin: str


@dataclass(frozen=True)
class CompletenessReport:
    """Ce que le contrôle a trouvé. Une lecture, jamais une décision.

    Patron repris de `MappingReport` (S5) : un rapport qu'on interroge,
    plutôt qu'une exception qui interrompt. La différence compte ici parce
    qu'un écran doit pouvoir AFFICHER les manques d'une facture sans que
    les afficher ne soit un incident."""

    profile_country: str
    missing: tuple[MissingField, ...]
    #: Renseigné quand aucun profil n'est déclaré pour le pays du tenant.
    #: Distinct d'une liste de manques vide : « rien ne manque » et « on ne
    #: sait pas ce qui est exigé » sont deux réponses opposées, et les
    #: confondre ferait soumettre selon des règles devinées.
    no_profile: bool = False

    @property
    def can_submit(self) -> bool:
        return not self.missing and not self.no_profile

    def as_sentence(self) -> str:
        """Le refus tel qu'un comptable doit le lire.

        Les champs sont nommés, pas comptés : « trois champs manquants » ne
        dit à personne quoi corriger."""
        if self.no_profile:
            return str(
                "Aucun profil de facturation électronique n'est déclaré pour "
                f"le pays « {self.profile_country} » : rien n'est soumis."
            )
        if not self.missing:
            return "La pièce porte toutes les mentions exigées."
        noms = ", ".join(str(champ.label) for champ in self.missing)
        return f"Soumission impossible — mentions manquantes : {noms}."


def submission_blockers(move: AccMove) -> CompletenessReport:
    """Les mentions exigées que cette pièce ne porte pas.

    Ne modifie rien, ne lève rien sur une pièce incomplète — voir la
    docstring de module."""
    tenant = move.tenant
    pays = tenant.country_code or ""
    profil = get_profile(pays)
    if profil is None:
        return CompletenessReport(profile_country=pays, missing=(), no_profile=True)

    valeurs = _readable_values(move)
    manques = tuple(
        MissingField(code=champ.code, label=champ.label, origin=champ.origin)
        for champ in profil.required_fields
        if _is_absent(valeurs.get(champ.code))
    )
    return CompletenessReport(profile_country=profil.country_code, missing=manques)


def is_submittable_type(move: AccMove) -> bool:
    """Cette NATURE de pièce relève-t-elle du dispositif ?

    Séparé de `submission_blockers` à dessein : « cette écriture n'a pas à
    être soumise » et « cette facture ne peut pas l'être encore » sont deux
    réponses qu'un écran présente différemment, et qu'un total ne doit
    jamais additionner."""
    return move.move_type in SUBMITTABLE_MOVE_TYPES


def _is_absent(valeur: object) -> bool:
    """Vide, blanc, nul — ou zéro pour un montant.

    Un total à zéro n'est pas une donnée manquante au sens strict, mais une
    facture à zéro n'a rien à faire chez une administration fiscale : la
    laisser passer ferait soumettre du bruit."""
    if valeur is None:
        return True
    if isinstance(valeur, Decimal):
        return valeur == 0
    return not str(valeur).strip()


def _readable_values(move: AccMove) -> dict[str, object]:
    """Résout chaque code de champ exigé vers la valeur réellement portée.

    Une table explicite plutôt qu'un `getattr` sur le code : les champs du
    profil ne sont pas des attributs d'`AccMove` (l'identité de l'émetteur
    vit sur le tenant, celle du client chez `partners`), et un `getattr`
    silencieux rendrait `None` pour un code mal orthographié — donc un
    manque inventé, sur un champ qui existe."""
    from apps.partners.services.public import get_partner_fiscal_identity

    tenant = move.tenant
    tiers: dict[str, object] = (
        get_partner_fiscal_identity(move.partner_id) if move.partner_id else {}
    )
    return {
        "issuer_name": tenant.name,
        "issuer_nif": tenant.nif,
        "issuer_stat": tenant.stat,
        "issuer_address": tenant.address,
        "customer_name": tiers.get("name", ""),
        "customer_nif": tiers.get("nif", ""),
        "customer_stat": tiers.get("stat", ""),
        "reference": move.reference,
        "date": move.date,
        "total": move.total_credit or move.total_debit,
        "currency": move.currency,
    }


def declared_field_codes(profile: EInvoiceProfile) -> frozenset[str]:
    """Les codes qu'un profil exige — pour la garde qui vérifie que chacun
    est réellement résolu par `_readable_values`.

    Un profil qui exigerait un champ que le résolveur ne connaît pas
    produirait un manque PERMANENT et inexplicable : la facture serait
    éternellement incomplète sur une mention que rien ne peut renseigner."""
    return frozenset(champ.code for champ in profile.required_fields)


#: Les codes que `_readable_values` sait résoudre. ÉCRITS, et non déduits
#: d'un appel sur une pièce factice : le résolveur lit le tenant et le
#: tiers, donc un appel factice explose ou ment. Une garde compare cette
#: liste à celle qu'exigent les profils — sans quoi un profil pourrait
#: exiger un champ que rien ne renseigne, et la facture serait
#: éternellement incomplète sur une mention impossible à fournir.
RESOLVABLE_FIELD_CODES: frozenset[str] = frozenset(
    {
        "issuer_name",
        "issuer_nif",
        "issuer_stat",
        "issuer_address",
        "customer_name",
        "customer_nif",
        "customer_stat",
        "reference",
        "date",
        "total",
        "currency",
    }
)


__all__ = [
    "RESOLVABLE_FIELD_CODES",
    "SUBMITTABLE_MOVE_TYPES",
    "CompletenessReport",
    "MissingField",
    "declared_field_codes",
    "is_submittable_type",
    "submission_blockers",
]
