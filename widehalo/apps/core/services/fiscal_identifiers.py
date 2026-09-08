"""T3 (Phase 4, l.224 et EFA-1) — les identifiants fiscaux, déclarés par
pays plutôt que codés en dur.

**Pourquoi dans `core` et pas dans `partners`.** Deux modèles portent un
identifiant fiscal dans ce dépôt : le TIERS (`partners.Partner.nif`) et
l'ÉMETTEUR (`core.Tenant.nif`). Une facture soumise à une administration
porte les deux, et EFA-1 les exige tous les deux. Ils doivent donc parler
la même langue — sans quoi le contrôle de complétude du bloc C
appliquerait deux règles différentes aux deux moitiés du même document —
et `core` ne peut pas importer `partners` (ce serait le socle qui dépend
d'un module). Le vocabulaire vit au seul endroit que les deux peuvent
atteindre : c'est mot pour mot le raisonnement déjà tenu pour
`core/cost_units.py`.

**Le critère, et ce qu'il exige vraiment.** Le cahier place la qualité du
référentiel tiers parmi les « trois travaux que la Phase 4 impose au
CLIENT » : « un identifiant fiscal absent ou faux, qui n'empêchait qu'une
impression jusqu'ici, **empêchera désormais une validation** » (l.224). Et
le critère EFA-1 dit où le refus tombe : « un champ obligatoire manquant
**bloque la soumission** et désigne le champ, **sans invalider la
facture** ».

**Ce que la mesure a trouvé.** `Partner.nif` est un
`CharField(max_length=32, blank=True, db_index=True)` — aucun validateur,
aucune unicité — écrit sans contrôle par six surfaces
(`services/onboarding.py`, `services/partner_import.py`, `api.py`,
`views.py`, `seed_partners.py`, `core/services/sandbox.py`). Le numéro
statistique n'existait pas. Et `nif` sert DÉJÀ de clef de rapprochement de
doublons (`onboarding.py`, `partner_import.py`) : deux saisies du même
identifiant sous deux formes — « MG-NIF-100002 » et « mg nif 100002 » — ne
se rapprochent pas aujourd'hui.

**La décision la plus importante de ce module : on n'invente pas le
format.** Le format exact du NIF malgache n'est pas dans le cahier, et
aucune source primaire n'est disponible dans ce dépôt — le jeu de
démonstration lui-même utilise des valeurs manifestement fictives
(« MG-NIF-100001 »). Écrire ici une expression régulière stricte
fabriquerait une règle fiscale et la présenterait comme vérifiée, ce que
ce projet s'interdit (§0.5). C'est exactement la posture retenue au lot T2
pour `tva.taux_export`.

Ce que ce registre contrôle donc, pour Madagascar, est **structurel et
défendable** : un identifiant n'est pas vide, tient dans des bornes de
longueur, et ne contient que des caractères qu'un identifiant administratif
emploie. Cela refuse le déchet — une chaîne vide, un espace, « n/a », un
paragraphe — sans prétendre reconnaître un NIF authentique. Le « faux » au
sens fort se vérifie ailleurs, par l'opération OP8 auprès du référentiel.

**Le jour où une source primaire existera**, resserrer le motif est un
changement de PARAMÈTRE dans ce fichier, pas une reprise de code : c'est ce
que le critère EFA-7 exige déjà pour le format de facture — « le changement
de pays du paramétrage bascule format, contrôles, durée d'archivage et
libellés, sans déploiement de code ».
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

#: Longueur minimale d'une réserve écrite, même seuil que les autres
#: registres à motif du dépôt (`endpoint_governance`, `outbound_schemas`).
RESERVE_MINIMUM = 40

#: Les deux identifiants qu'une administration fiscale demande d'un tiers :
#: le numéro d'identification fiscale et le numéro statistique. Jeu FERMÉ —
#: en ajouter un troisième est une décision explicite, pas un ajout de
#: chaîne.
IDENTIFIER_NIF = "nif"
IDENTIFIER_STAT = "stat"
IDENTIFIER_CHOICES: list[tuple[str, str | Promise]] = [
    (IDENTIFIER_NIF, _("Numéro d'identification fiscale")),
    (IDENTIFIER_STAT, _("Numéro statistique")),
]
KNOWN_IDENTIFIERS: frozenset[str] = frozenset(code for code, _label in IDENTIFIER_CHOICES)

#: Les caractères qu'un identifiant administratif emploie. Volontairement
#: large : lettres, chiffres, tiret, barre oblique, point et espace. Ce
#: qu'il REFUSE est ce qui compte — la ponctuation de phrase, les accents,
#: les caractères de contrôle, tout ce qui trahit un texte libre saisi dans
#: le mauvais champ.
_CARACTERES_ADMIS = re.compile(r"^[A-Z0-9\-/. ]+$")

#: Pour la COMPARAISON seulement : on retire tout ce qui n'est ni lettre ni
#: chiffre. « MG-NIF-100002 » et « MGNIF100002 » désignent le même tiers ;
#: les rapprocher est le but, mais on ne réécrit pas pour autant la valeur
#: saisie — l'un des deux pourrait être la forme officielle.
_NON_ALPHANUMERIQUE = re.compile(r"[^A-Z0-9]")


@dataclass(frozen=True)
class FiscalIdentifierFormat:
    """Le format déclaré d'un identifiant, pour un pays.

    `pattern` est une expression régulière appliquée à la forme
    NORMALISÉE. `reserve` dit ce que ce contrôle vaut, et ce qu'il ne vaut
    pas — elle est obligatoire et longue, parce qu'un contrôle réglementaire
    sans réserve écrite se lit comme une conformité vérifiée."""

    identifier: str
    country_code: str
    label: str
    pattern: str
    length_min: int
    length_max: int
    example: str
    reserve: str

    def __post_init__(self) -> None:
        if self.identifier not in KNOWN_IDENTIFIERS:
            raise ValidationError(
                _("Identifiant hors du jeu fermé : %(code)s.") % {"code": self.identifier}
            )
        if len(self.reserve) < RESERVE_MINIMUM:
            raise ValidationError(
                _(
                    "La réserve du format « %(id)s/%(pays)s » fait %(n)s caractères ; "
                    "il en faut au moins %(min)s. Un contrôle réglementaire sans "
                    "réserve écrite se lit comme une conformité vérifiée."
                )
                % {
                    "id": self.identifier,
                    "pays": self.country_code,
                    "n": len(self.reserve),
                    "min": RESERVE_MINIMUM,
                }
            )
        if self.length_min < 1 or self.length_max < self.length_min:
            raise ValidationError(_("Bornes de longueur incohérentes."))
        re.compile(self.pattern)


_RESERVE_MG = (
    "contrôle STRUCTUREL seulement : longueur et caractères admis. Le format "
    "exact du NIF/STAT malgache n'est pas publié dans une source primaire "
    "accessible à ce dépôt — le resserrer est un changement de paramètre ici, "
    "à faire confirmer auprès de la DGI ou d'un cabinet OECFM. La vérification "
    "de l'existence réelle de l'identifiant relève de l'opération OP8."
)

#: Les formats déclarés, par (identifiant, pays). Un pays absent de ce
#: registre n'a PAS de contrôle de format — et c'est un état explicite, pas
#: un oubli : inventer un motif pour un pays qu'on ne connaît pas serait
#: pire que de ne rien contrôler.
FORMATS: dict[tuple[str, str], FiscalIdentifierFormat] = {
    (IDENTIFIER_NIF, "MG"): FiscalIdentifierFormat(
        identifier=IDENTIFIER_NIF,
        country_code="MG",
        label="NIF malgache",
        pattern=r"^[A-Z0-9\-/. ]{4,32}$",
        length_min=4,
        length_max=32,
        example="MG-NIF-100001",
        reserve=_RESERVE_MG,
    ),
    (IDENTIFIER_STAT, "MG"): FiscalIdentifierFormat(
        identifier=IDENTIFIER_STAT,
        country_code="MG",
        label="Numéro statistique malgache",
        pattern=r"^[A-Z0-9\-/. ]{4,32}$",
        length_min=4,
        length_max=32,
        example="12345 11 2026 0 00123",
        reserve=_RESERVE_MG,
    ),
}

#: Le pays de repli quand le tenant n'en déclare pas. `Tenant.country_code`
#: vaut « MG » par défaut ; cette constante existe pour que le repli soit
#: NOMMÉ plutôt que dispersé en littéraux.
DEFAULT_COUNTRY_CODE = "MG"


def normalize(valeur: str | None) -> str:
    """La forme STOCKÉE : espaces extérieurs retirés, espaces intérieurs
    ramenés à un seul, majuscules.

    Ce qu'elle NE fait pas, et c'est délibéré : elle ne retire pas les
    séparateurs. « MG-NIF-100002 » et « MGNIF100002 » désignent
    probablement le même tiers, mais l'un des deux peut être la forme
    officielle ; réécrire la saisie d'un comptable au motif qu'on croit
    savoir mieux est le genre de service qu'on ne rend qu'une fois. Le
    rapprochement, lui, se fait sur `canonical` ci-dessous."""
    if not valeur:
        return ""
    return re.sub(r"\s+", " ", valeur.strip()).upper()


def canonical(valeur: str | None) -> str:
    """La forme de COMPARAISON : uniquement lettres et chiffres.

    Sert la détection de doublons (`services/onboarding.py`,
    `services/partner_import.py`), qui comparait jusqu'ici des chaînes
    brutes — deux saisies du même identifiant sous deux ponctuations ne se
    rapprochaient donc pas."""
    return _NON_ALPHANUMERIQUE.sub("", normalize(valeur))


def get_format(identifier: str, country_code: str) -> FiscalIdentifierFormat | None:
    return FORMATS.get((identifier, (country_code or DEFAULT_COUNTRY_CODE).upper()))


def validate_identifier(
    valeur: str | None, *, identifier: str, country_code: str = DEFAULT_COUNTRY_CODE
) -> str:
    """Rend la forme normalisée, ou lève en NOMMANT ce qui ne va pas.

    **Une valeur vide passe.** Le critère refuse un identifiant absent *là
    où la soumission l'exige* (EFA-1), pas partout : un prospect saisi en
    trente secondes n'a pas encore de NIF, et exiger le champ à la création
    rendrait le CRM inutilisable. C'est le contrôle de complétude du bloc C
    qui refuse la soumission, en désignant le champ — et ce module lui
    fournit de quoi le faire.

    Un pays sans format déclaré ne contrôle rien : l'inconnu se dit, il ne
    se devine pas."""
    normalisee = normalize(valeur)
    if not normalisee:
        return ""

    if identifier not in KNOWN_IDENTIFIERS:
        raise ValidationError(_("Identifiant hors du jeu fermé : %(code)s.") % {"code": identifier})

    format_declare = get_format(identifier, country_code)
    if format_declare is None:
        return normalisee

    if not _CARACTERES_ADMIS.match(normalisee):
        raise ValidationError(
            _(
                "%(label)s : caractères non admis. Un identifiant administratif "
                "s'écrit en lettres, chiffres, tirets, barres obliques, points et "
                "espaces — exemple : %(exemple)s."
            )
            % {"label": format_declare.label, "exemple": format_declare.example}
        )
    if not (format_declare.length_min <= len(normalisee) <= format_declare.length_max):
        raise ValidationError(
            _(
                "%(label)s : longueur de %(n)s caractères hors des bornes "
                "%(min)s–%(max)s — exemple : %(exemple)s."
            )
            % {
                "label": format_declare.label,
                "n": len(normalisee),
                "min": format_declare.length_min,
                "max": format_declare.length_max,
                "exemple": format_declare.example,
            }
        )
    if not re.match(format_declare.pattern, normalisee):
        raise ValidationError(
            _("%(label)s : format attendu — exemple : %(exemple)s.")
            % {"label": format_declare.label, "exemple": format_declare.example}
        )
    return normalisee


def validate_partner_nif(valeur: str) -> None:
    """Validateur de CHAMP pour un NIF, au format du pays par défaut.

    **Il ne remplace pas le contrôle de `save()`, il le double**, et la
    nuance mérite d'être écrite. Un validateur de champ Django ne reçoit
    que la valeur : il ne peut pas savoir de quel pays relève la société
    qui la porte. Il applique donc le format du pays par défaut, ce qui en
    fait un plancher — utile aux formulaires et à l'OpenAPI, qui le voient,
    là où `save()` ne parle qu'à la base.

    `Partner.save()` refait le contrôle avec le VRAI pays de la société, et
    c'est lui qui fait autorité. Même montage que
    `FlwConnector.supported_operations` (S6), et pour la même raison :
    Django ne fait tourner les validateurs de champ que dans
    `full_clean()`, jamais dans `save()`."""
    validate_identifier(valeur, identifier=IDENTIFIER_NIF)


def validate_partner_stat(valeur: str) -> None:
    """Idem pour le numéro statistique — cf. `validate_partner_nif`."""
    validate_identifier(valeur, identifier=IDENTIFIER_STAT)


__all__ = [
    "DEFAULT_COUNTRY_CODE",
    "FORMATS",
    "IDENTIFIER_CHOICES",
    "IDENTIFIER_NIF",
    "IDENTIFIER_STAT",
    "KNOWN_IDENTIFIERS",
    "RESERVE_MINIMUM",
    "FiscalIdentifierFormat",
    "canonical",
    "get_format",
    "normalize",
    "validate_identifier",
    "validate_partner_nif",
    "validate_partner_stat",
]
