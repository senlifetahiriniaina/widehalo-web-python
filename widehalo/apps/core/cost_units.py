"""Le vocabulaire des unites de cout — partage, ferme, et defini ICI.

**Pourquoi dans `core` et pas dans le module qui l'utilise le plus.** Deux
compteurs de cout existent dans ce depot : celui de la messagerie
(`core.WhatsAppMessage.cost_ariary`) et celui du hub de flux
(`flows.FlwExchange.cost_ariary`). Ils doivent parler la meme langue —
sans quoi un total transverse melangerait deux vocabulaires — et `core` ne
peut pas importer `flows` (ce serait le socle qui depend d'un module).
Le vocabulaire vit donc au seul endroit que les deux peuvent atteindre.

**Ce que ce jeu ferme resout : l'hypothese H26.** Le cahier de la Phase 4
pose que « le passage de la messagerie professionnelle a une facturation au
message est correctement modelisable dans le compteur existant sans reprise
de l'historique », avec pour repli « deux unites de cout coexistent, avec
une date de bascule », au prix d'« un sprint supplementaire au bloc H ». Il
demande de trancher au sprint 3 : « le prendre apres le sprint 6
signifierait reprendre le socle ».

La branche optimiste est vraie a MOITIE, et c'est ce demi-vrai qui est
dangereux. Vraie : le cout est fige sur la ligne au moment de l'envoi, donc
aucune reprise d'historique n'est necessaire — les lignes passees gardent
le tarif qui leur a ete impute. Fausse : rien n'enregistrait SOUS QUELLE
UNITE. Une somme sur une periode a cheval sur une bascule est exacte a
l'ariary et pourtant incomparable a la periode precedente, sans que rien ne
le signale.

**On ne parie donc sur aucune branche : on rend l'unite DONNEE.** Le cout
devient un couple (montant, unite). Si la bascule n'a jamais lieu, l'unite
reste constante et rien n'est perdu ; si elle a lieu, chaque ligne dit deja
sous quel regime elle a ete tarifee. L'arbitrage cesse de conditionner la
conception — c'est-a-dire qu'il cesse d'etre un risque de projet, et le
sprint supplementaire annonce au bloc H n'a plus lieu d'etre.

**L'unite en vigueur, et la date de bascule, ne sont pas ici.** Elles
vivent dans la table de parametres versionnes (`core.RegulatoryParameter`,
code `messagerie.unite_cout`), parce que le cahier le demande — « les
grilles tarifaires vivent dans les parametres versionnes » — et parce que
cette table porte deja une plage de validite : la « date de bascule »
n'est alors rien d'autre qu'une ligne de plus avec un `valid_from`. Le
mecanisme demande par le repli de H26 existait donc deja, il n'etait
simplement pas employe.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant

#: Facturation A LA CONVERSATION : une fenetre de 24 h par categorie est
#: facturee une fois, quel que soit le nombre de messages qu'elle porte.
COST_UNIT_CONVERSATION = "conversation"

#: Facturation AU MESSAGE : chaque message delivre porte son prix.
COST_UNIT_MESSAGE = "message"

COST_UNIT_CHOICES = [
    (COST_UNIT_CONVERSATION, "À la conversation"),
    (COST_UNIT_MESSAGE, "Au message"),
]

KNOWN_COST_UNITS = frozenset(code for code, _label in COST_UNIT_CHOICES)

#: Le code du parametre versionne qui porte l'unite en vigueur.
COST_UNIT_PARAMETER_CODE = "messagerie.unite_cout"

#: L'unite retenue faute de parametre. `message` et non `conversation`,
#: pour une raison qui n'est pas arbitraire : c'est ce que le compteur
#: FAISAIT deja avant ce chantier — une somme plate ligne par ligne. Un
#: defaut different aurait change en silence le comportement de tous les
#: deploiements existants, ce qui est exactement ce qu'une bascule
#: d'unite non datee produit de pire.
DEFAULT_COST_UNIT = COST_UNIT_MESSAGE


def cost_unit_in_force(*, at_date: dt.date | None = None, tenant: Tenant | None = None) -> str:
    """L'unite de cout applicable a une date, selon les parametres versionnes.

    Retombe sur `DEFAULT_COST_UNIT` quand aucun parametre n'est seme —
    jamais une exception. Un compteur de cout qui leve parce qu'un
    parametre manque bloquerait l'envoi de messages pour un motif de
    configuration, ce qui est la meme faute que le referentiel de TVA
    absent bloquant la construction d'un socle de simulation (corrigee en
    L17).

    Une valeur inconnue est traitee comme absente, et journalisee : un
    parametre mal saisi ne doit pas faire basculer silencieusement toute la
    facturation d'un tenant vers une unite que le code ne sait pas
    totaliser."""
    from apps.core.models.regulatory import RegulatoryParameter
    from apps.core.services.regulatory import get_parameter

    moment = at_date or dt.datetime.now(tz=dt.UTC).date()
    try:
        value = get_parameter(COST_UNIT_PARAMETER_CODE, moment, tenant)
    except RegulatoryParameter.DoesNotExist:
        return DEFAULT_COST_UNIT

    unit = str(value)
    if unit not in KNOWN_COST_UNITS:
        import logging

        logging.getLogger(__name__).warning(
            "Unité de coût inconnue dans le paramètre %s au %s : %r — %r retenue.",
            COST_UNIT_PARAMETER_CODE,
            moment,
            unit,
            DEFAULT_COST_UNIT,
        )
        return DEFAULT_COST_UNIT
    return unit


__all__ = [
    "COST_UNIT_CHOICES",
    "COST_UNIT_CONVERSATION",
    "COST_UNIT_MESSAGE",
    "COST_UNIT_PARAMETER_CODE",
    "DEFAULT_COST_UNIT",
    "KNOWN_COST_UNITS",
    "cost_unit_in_force",
]
