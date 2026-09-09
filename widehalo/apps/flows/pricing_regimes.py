"""Les trois regimes tarifaires d'un connecteur — jeu FERME (cahier §15.1).

**Pourquoi ce jeu existe, et ce qu'il decide.** Le cahier §15.2 pose une
obligation d'activation : « **Plafond obligatoire avant activation.** Aucun
connecteur du regime a l'usage ne peut etre active sans qu'un plafond ne
soit defini. La valeur par defaut est volontairement basse. » Cette phrase
est inapplicable tant que le produit ne sait pas de quel regime releve un
connecteur : sans le regime, on ne peut ni exiger le plafond la ou il faut,
ni s'en dispenser la ou il ne sert a rien.

**Ce que la mesure disait avant d'ecrire.** `FlwConnector` ne portait aucun
regime, et le plafond n'existait nulle part — alors que `cost.py::
cost_total` calculait deja un total de periode sans appelant, que l'etat
`SUSPENDU` de l'echange etait declare avec son invariant sans que rien ne
l'ecrive, et que `incidents.py` proposait comme action de reprise
« relever le plafond de la liaison ». Un compteur, un etat et une action de
reprise, tous les trois ecrits et coherents entre eux, et aucun branche.

**Aucun regime par defaut, et c'est deliberé.** Mettre « socle inclus » par
defaut exempterait silencieusement du plafond un connecteur qui coute a
chaque appel ; mettre « a l'usage » imposerait un plafond a un connecteur
gratuit. Le champ est donc VIDE tant que personne ne l'a declare, et
l'activation refuse : « aucun connecteur n'est actif par defaut » (§9.1),
et un regime non declare est exactement le genre de silence que ce depot
refuse de combler par une valeur inventee.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

#: Compris dans l'abonnement de base, sans limite d'usage autre que
#: technique. API publique, exports, stockage objet, courriel, bureautique,
#: commerce generique.
REGIME_INCLUDED = "socle_inclus"

#: Supplement mensuel par tenant, independant du volume. Conformite
#: e-facture. Le cout est un cout de veille reglementaire, pas un cout par
#: message.
REGIME_SUBSCRIPTION = "abonnement_module"

#: Refacturation du cout du tiers, majoree d'une marge declaree. Messagerie
#: conversationnelle, encaissement mobile, passerelle de carte, SMS. **Le
#: seul des trois qui exige un plafond avant activation.**
REGIME_USAGE = "a_l_usage"

REGIME_CHOICES = [
    (REGIME_INCLUDED, _("Socle inclus")),
    (REGIME_SUBSCRIPTION, _("Abonnement de module")),
    (REGIME_USAGE, _("À l'usage")),
]

REGIME_CODES = frozenset(code for code, _label in REGIME_CHOICES)

#: Les regimes qui exigent un plafond defini avant activation (§15.2).
#: Un frozenset plutot qu'une comparaison a `REGIME_USAGE` : le jour ou un
#: quatrieme regime factureria au volume, la regle se lit ici et non dans un
#: `if` perdu au milieu d'un service.
REGIMES_REQUIRING_A_CAP = frozenset({REGIME_USAGE})


def validate_pricing_regime(value: str) -> None:
    """Refuse un regime hors du jeu ferme. La chaine vide est acceptee : elle
    signifie « pas encore declare », et c'est l'activation qui la refuse —
    pas l'enregistrement du catalogue, ou l'exploitant peut legitimement
    creer un connecteur avant d'avoir tranche son regime."""
    if value and value not in REGIME_CODES:
        raise ValidationError(
            _("Régime tarifaire inconnu : « %(value)s ». Le cahier §15.1 en déclare trois.")
            % {"value": value}
        )


def requires_a_cap(regime: str) -> bool:
    """`True` si le §15.2 exige un plafond avant activation pour ce régime."""
    return regime in REGIMES_REQUIRING_A_CAP


def assert_regime_vocabulary_is_closed() -> None:
    """Auto-test appele depuis `apps.py::ready()`, meme patron que les
    autres jeux fermes du depot.

    Il verifie que les regimes exigeant un plafond font bien partie du jeu :
    une entree mal orthographiee dans `REGIMES_REQUIRING_A_CAP` ne
    correspondrait a aucun connecteur, et l'obligation du §15.2 cesserait de
    s'appliquer **sans qu'aucun test ne tombe**."""
    inconnus = REGIMES_REQUIRING_A_CAP - REGIME_CODES
    if inconnus:
        raise AssertionError(
            f"Régime(s) exigeant un plafond hors du jeu fermé : {sorted(inconnus)}. "
            "L'obligation du §15.2 ne s'appliquerait à aucun connecteur."
        )


__all__ = [
    "REGIMES_REQUIRING_A_CAP",
    "REGIME_CHOICES",
    "REGIME_CODES",
    "REGIME_INCLUDED",
    "REGIME_SUBSCRIPTION",
    "REGIME_USAGE",
    "assert_regime_vocabulary_is_closed",
    "requires_a_cap",
    "validate_pricing_regime",
]
