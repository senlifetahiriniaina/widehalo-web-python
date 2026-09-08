"""T4 (bloc C, EFA-1 et EFA-7) — le profil e-facture d'un pays, DÉCLARÉ.

**Le cahier a déjà tranché la question qui paraissait bloquante**, et il
faut le citer avant d'écrire une ligne. Sur l'option « attendre la
publication des spécifications avant tout développement » : « **Écarté.**
Le moteur est construit sur la structure commune des dispositifs
régionaux, **le format est un paramètre** » (§12.3). Et sur le risque P4-R1
: « le moteur de conformité est réputé complet lorsqu'il produit, archive
et met en file un document normalisé **sans qu'aucune plateforme ne soit
joignable** ». Le mode d'attente est le livrable, pas une dégradation.

**Ce que ce module EST.** La liste, par pays, de ce qu'une soumission
exige : les champs obligatoires — avec le libellé sous lequel un comptable
les reconnaît —, la durée d'archivage, et la réserve qui dit ce que cette
liste vaut. C'est ce fichier, et lui seul, que l'on modifie le jour où un
pays change ses règles : EFA-7 exige que « le changement de pays du
paramétrage bascule format, contrôles, durée d'archivage et libellés,
**sans déploiement de code** ».

**Ce que ce module N'EST PAS, et c'est la décision centrale du lot.** Il
n'invente aucune règle fiscale malgache. Le format exact du document
normalisé, la liste officielle des mentions et la durée légale
d'archivage ne sont publiés dans aucune source primaire accessible à ce
dépôt — le cahier lui-même ne les donne pas, et son §12.3 explique
pourquoi (le dispositif n'est pas ouvert). Écrire ici une liste stricte et
la présenter comme conforme fabriquerait une obligation légale.

Ce que la liste ci-dessous contient est donc **ce que le cahier nomme
lui-même** et rien de plus : l'identité de l'ÉMETTEUR autant que celle du
CLIENT (EFA-1 parle des deux), et les données sans lesquelles aucun
dispositif régional connu ne peut rien faire — numéro de pièce, date,
montants. Chaque profil porte sa réserve. C'est la posture déjà tenue au
lot T2 pour `tva.taux_export` et au lot T3 pour le format du NIF.

**Pourquoi dans `accounting` et pas dans `core`.** Le profil décrit ce
qu'une PIÈCE COMPTABLE doit porter pour être soumise ; ses champs
désignent des attributs d'`AccMove` et du tiers. `core` n'a pas à
connaître la facture. La règle de couplage n°1 reste tenue : le contrôle
de complétude lit le tiers par `partners.services.public`, jamais par
`partners.models`.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

#: Longueur minimale d'une réserve écrite — même seuil que les autres
#: registres à motif du dépôt (`endpoint_governance`, `outbound_schemas`,
#: `fiscal_identifiers`). Un contrôle réglementaire sans réserve écrite se
#: lit comme une conformité vérifiée.
RESERVE_MINIMUM = 40

#: D'où vient la valeur d'un champ exigé. Jeu FERMÉ : ajouter une
#: troisième origine est une décision, pas un ajout de chaîne — et chaque
#: origine a son lecteur distinct dans le contrôle de complétude.
ORIGIN_ISSUER = "emetteur"
ORIGIN_CUSTOMER = "client"
ORIGIN_DOCUMENT = "piece"
ORIGIN_CHOICES: list[tuple[str, str | Promise]] = [
    (ORIGIN_ISSUER, _("Société émettrice")),
    (ORIGIN_CUSTOMER, _("Tiers destinataire")),
    (ORIGIN_DOCUMENT, _("Pièce elle-même")),
]
KNOWN_ORIGINS: frozenset[str] = frozenset(code for code, _label in ORIGIN_CHOICES)


@dataclass(frozen=True)
class RequiredField:
    """Un champ sans lequel la soumission est refusée.

    `label` n'est pas décoratif : EFA-1 exige que le refus « DÉSIGNE le
    champ ». Un code technique (`stat`, `partner_id`) ne désigne rien pour
    un comptable — c'est ce libellé qui part dans le message de refus, et
    c'est aussi lui qu'EFA-7 fait basculer avec le pays."""

    code: str
    label: str | Promise
    origin: str

    def __post_init__(self) -> None:
        if self.origin not in KNOWN_ORIGINS:
            raise ValidationError(
                _("Origine hors du jeu fermé : %(origine)s.") % {"origine": self.origin}
            )
        if not self.code:
            raise ValidationError(_("Un champ exigé sans code ne peut désigner personne."))


@dataclass(frozen=True)
class EInvoiceProfile:
    """Le profil d'un pays. Une donnée, jamais du code.

    `archive_years` porte la « durée réglementaire » du §14.3 et alimente
    `FlwPayload.retain_until` — dont le commentaire, écrit au sprint S1,
    anticipait déjà le cas : « une soumission fiscale se conserve plus
    longtemps qu'un catalogue publié »."""

    country_code: str
    label: str
    required_fields: tuple[RequiredField, ...]
    archive_years: int
    reserve: str

    def __post_init__(self) -> None:
        if len(self.reserve) < RESERVE_MINIMUM:
            raise ValidationError(
                _(
                    "La réserve du profil « %(pays)s » fait %(n)s caractères ; il en "
                    "faut au moins %(min)s. Un profil sans réserve écrite se lit "
                    "comme une conformité vérifiée."
                )
                % {"pays": self.country_code, "n": len(self.reserve), "min": RESERVE_MINIMUM}
            )
        if self.archive_years < 1:
            raise ValidationError(_("Une durée d'archivage nulle n'est pas une durée."))
        if not self.required_fields:
            raise ValidationError(
                _(
                    "Un profil sans aucun champ exigé rendrait le contrôle de "
                    "complétude toujours vert, donc inutile."
                )
            )
        codes = [champ.code for champ in self.required_fields]
        if len(codes) != len(set(codes)):
            raise ValidationError(_("Deux champs exigés portent le même code."))


_RESERVE_MG = (
    "liste MINIMALE et non officielle : le dispositif malgache de facturation "
    "électronique n'est pas ouvert, et ni le cahier ni aucune source primaire "
    "accessible à ce dépôt ne publie la liste des mentions ni la durée légale "
    "d'archivage. Ce profil retient ce que le cahier nomme lui-même — l'identité "
    "de l'émetteur ET du client (EFA-1) — et les données sans lesquelles aucun "
    "dispositif régional connu ne peut rien faire. À confirmer auprès de la DGI "
    "ou d'un cabinet OECFM avant tout raccordement réel ; le resserrer est un "
    "changement de paramètre dans ce fichier, pas une reprise de code (EFA-7)."
)

#: Les profils déclarés, par code pays. Un pays absent n'a PAS de profil —
#: état explicite, pas un oubli : un tenant dans un pays inconnu ne soumet
#: rien, plutôt que de soumettre selon des règles inventées pour lui.
PROFILES: dict[str, EInvoiceProfile] = {
    "MG": EInvoiceProfile(
        country_code="MG",
        label="Madagascar — dispositif à contrôle continu",
        required_fields=(
            RequiredField("issuer_name", _("Raison sociale de la société"), ORIGIN_ISSUER),
            RequiredField("issuer_nif", _("NIF de la société"), ORIGIN_ISSUER),
            RequiredField("issuer_stat", _("Numéro statistique de la société"), ORIGIN_ISSUER),
            RequiredField("issuer_address", _("Adresse de la société"), ORIGIN_ISSUER),
            RequiredField("customer_name", _("Raison sociale du client"), ORIGIN_CUSTOMER),
            RequiredField("customer_nif", _("NIF du client"), ORIGIN_CUSTOMER),
            RequiredField("reference", _("Numéro de facture"), ORIGIN_DOCUMENT),
            RequiredField("date", _("Date de la facture"), ORIGIN_DOCUMENT),
            RequiredField("total", _("Montant total"), ORIGIN_DOCUMENT),
            RequiredField("currency", _("Devise"), ORIGIN_DOCUMENT),
        ),
        # Cinq ans : durée retenue par défaut, explicitement couverte par la
        # réserve ci-dessus. Elle n'est pas tirée d'un texte malgache — elle
        # est la borne basse commune aux dispositifs régionaux cités par le
        # cahier, et elle EXISTE pour que `retain_until` ait une valeur
        # plutôt qu'un `None` qui laisserait la purge décider seule.
        archive_years=5,
        reserve=_RESERVE_MG,
    ),
}


def get_profile(country_code: str) -> EInvoiceProfile | None:
    """Le profil d'un pays, ou `None` s'il n'en a pas.

    `None` n'est pas une erreur : c'est l'état d'un pays dont on ne connaît
    pas les règles, et il vaut mieux ne rien soumettre que soumettre selon
    des règles devinées."""
    return PROFILES.get((country_code or "").upper())


__all__ = [
    "KNOWN_ORIGINS",
    "ORIGIN_CHOICES",
    "ORIGIN_CUSTOMER",
    "ORIGIN_DOCUMENT",
    "ORIGIN_ISSUER",
    "PROFILES",
    "RESERVE_MINIMUM",
    "EInvoiceProfile",
    "RequiredField",
    "get_profile",
]
