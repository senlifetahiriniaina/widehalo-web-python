"""S3 (Phase 4, bloc A) — les incidents, et le VOCABULAIRE DE L'ECHEC.

Le cahier consacre a ce vocabulaire une section entiere (§10.3) et en donne
le motif : « Un connecteur produit des erreurs qui viennent d'ailleurs,
formulees pour des developpeurs. Les remonter telles quelles est la maniere
la plus sure de rendre la console de flux inutilisable. »

D'ou six familles, fermees, chacune liee a UNE action de reprise. Ce module
porte les deux — l'enumeration vit sur le modele (`FlwIncident`), la table
des actions vit ici — et une seule regle les relie : **toute famille a une
action, aucune action sans famille**. C'est verifie par un test plutot que
tenu par discipline, parce qu'une septieme famille ajoutee sans son action
produirait, dans la console, un incident qui ne dit pas quoi faire — soit
exactement l'inutilisabilite que §10.3 cherche a eviter.

**Ce que ce module fait de FLX-3, et ce qu'il n'en fait pas.** Il tient la
moitie « un incident unique est cree — pas un incident par tentative » :
`record_failure` incremente une ligne vivante au lieu d'en creer une
seconde. Il ne touche PAS au disjoncteur : ouvrir le disjoncteur et ouvrir
un incident sont deux decisions distinctes, prises sur deux grains
differents — le disjoncteur par liaison, l'incident par (liaison, famille)
— et les melanger dans une fonction rendrait impossible de tester l'une
sans l'autre. Le disjoncteur est dans `services/queue.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.services.redaction import redact_secrets
from apps.flows.models import FlwIncident

if TYPE_CHECKING:
    from datetime import datetime

    from apps.flows.models import FlwLink

#: L'action de reprise, par famille. §10.3 : « chacune associee a une action
#: de reprise UNIQUE et comprehensible ». Une table, pas des colonnes : une
#: action stockee sur la ligne divergerait de la famille des la premiere
#: correction du libelle, et deux incidents de la meme famille proposeraient
#: alors deux reprises differentes.
#:
#: Ces phrases sont ecrites pour un comptable, pas pour un developpeur —
#: c'est l'exigence explicite du cahier sur toute la surface de flux
#: (« Ecrit pour un comptable, pas pour un informaticien », §10.2). Chacune
#: dit QUOI FAIRE, jamais ce qui s'est passe : « le tiers a renvoye 401 »
#: n'est pas une action de reprise.
#: Type laisse a l'inference : les valeurs sont des promesses de
#: traduction (`gettext_lazy`), pas des chaines — les annoter `str`
#: serait faux, et `recovery_action` est le point ou elles se
#: resolvent, une fois, au moment ou quelqu'un les lit.
RECOVERY_ACTIONS = {
    FlwIncident.FAMILY_CREDENTIALS: _(
        "Renouveler les identifiants de la liaison, puis relancer les échanges en attente."
    ),
    FlwIncident.FAMILY_INVALID_DATA: _(
        "Corriger la pièce désignée, puis rejouer l'échange : le tiers refuse la donnée, "
        "pas la liaison."
    ),
    FlwIncident.FAMILY_REJECTED: _(
        "Lire le motif du refus, corriger si le tiers l'autorise, sinon traiter la pièce "
        "hors ligne : un refus motivé ne se réessaie pas tel quel."
    ),
    FlwIncident.FAMILY_UNAVAILABLE: _(
        "Aucune action : les échanges repartiront d'eux-mêmes quand le tiers répondra. "
        "Basculer en saisie manuelle si l'échéance approche."
    ),
    FlwIncident.FAMILY_CAP_REACHED: _(
        "Relever le plafond de la liaison ou attendre la période suivante, puis "
        "reprendre les échanges suspendus."
    ),
    FlwIncident.FAMILY_EDITOR: _(
        "Signaler à l'éditeur avec la référence de l'incident : la cause n'est ni dans "
        "vos données ni chez le tiers."
    ),
}


def recovery_action(family: str) -> str:
    """L'action de reprise d'une famille.

    Leve sur une famille inconnue plutot que de renvoyer une chaine vide :
    une console qui affiche un incident sans action de reprise est une
    console qui laisse l'utilisateur devant un probleme sans issue, et
    c'est un defaut qu'il vaut mieux voir echouer en recette qu'en
    production."""
    try:
        return str(RECOVERY_ACTIONS[family])
    except KeyError as exc:
        raise KeyError(
            f"Famille d'erreur sans action de reprise : {family!r}. "
            "Le cahier (§10.3) ferme le jeu à six familles, chacune associée à une "
            "action de reprise unique."
        ) from exc


def live_incident(link: FlwLink, family: str) -> FlwIncident | None:
    """L'incident encore vivant pour ce couple, s'il y en a un."""
    return FlwIncident.objects.filter(
        tenant_id=link.tenant_id,
        link=link,
        family=family,
        state__in=FlwIncident.LIVE_STATES,
    ).first()


def record_failure(
    link: FlwLink,
    *,
    family: str,
    result_code: str = "",
    result_message: str = "",
    now: datetime | None = None,
) -> FlwIncident:
    """Enregistre un echec : ouvre l'incident, ou INCREMENTE celui qui vit.

    C'est la moitie de FLX-3 que ce module porte. Un incident par tentative
    transformerait une plateforme fiscale indisponible pendant une nuit en
    plusieurs centaines de lignes, et l'indicateur « part des echanges en
    incident non traites sous 48 h » n'y survivrait pas.

    **L'increment passe par `F()`, pas par une lecture suivie d'une
    ecriture.** Deux workers qui echouent au meme instant sur la meme
    liaison liraient tous deux `occurrence_count = 3` et ecriraient tous
    deux `4` : une occurrence perdue a chaque collision, et un compteur qui
    sous-estime d'autant plus que la panne est massive — c'est-a-dire au
    moment ou il sert.

    **La creation est protegee par la contrainte, pas par un `if`.** Le
    `get`/`create` naif perd la course : deux workers ne trouvent aucun
    incident vivant, tous deux en creent un, et la contrainte partielle en
    rejette un. On rattrape donc `IntegrityError` et on incremente le
    gagnant. Sans ce rattrapage, FLX-3 serait tenu en base — une seule
    ligne — mais au prix d'une exception remontee dans la vidange, qui
    ferait echouer la passe entiere pour un echec deja gere."""
    moment = now or timezone.now()
    recovery_action(family)  # refuse tout de suite une famille sans reprise
    # FLX-8, surface « message d'erreur affiche a l'utilisateur ».
    # `last_result_message` recopie ce que le TIERS a renvoye, et un tiers
    # qui refuse une authentification renvoie volontiers l'en-tete qu'il a
    # recu. Redige une fois ici, ou la valeur entre — les deux ecritures qui
    # suivent la partagent.
    result_message = redact_secrets(result_message)

    existing = live_incident(link, family)
    if existing is None:
        try:
            with transaction.atomic():
                return FlwIncident.objects.create(
                    tenant_id=link.tenant_id,
                    link=link,
                    family=family,
                    state=FlwIncident.STATE_OPEN,
                    first_seen_at=moment,
                    last_seen_at=moment,
                    occurrence_count=1,
                    last_result_code=result_code,
                    last_result_message=result_message,
                )
        except IntegrityError:
            # Course perdue : un autre worker vient d'ouvrir le meme
            # incident. Ce n'est pas une erreur, c'est le cas que la
            # contrainte existe pour rendre impossible.
            existing = live_incident(link, family)
            if existing is None:  # pragma: no cover - la contrainte garantit l'un ou l'autre
                raise

    FlwIncident.objects.filter(pk=existing.pk).update(
        occurrence_count=F("occurrence_count") + 1,
        last_seen_at=moment,
        last_result_code=result_code,
        last_result_message=result_message,
        updated_at=moment,
    )
    existing.refresh_from_db()
    return existing


def resolve_incident(incident: FlwIncident, *, now: datetime | None = None) -> FlwIncident:
    """Ferme un incident.

    Un incident resolu cesse de bloquer l'ouverture du suivant — c'est le
    role de la condition sur la contrainte. Une liaison reparee puis
    retombee en panne rouvre donc un incident NEUF, avec sa propre premiere
    occurrence : ecraser l'ancien ferait croire que la panne dure depuis
    des semaines alors qu'elle vient de reprendre, et l'indicateur des 48 h
    en serait fausse."""
    moment = now or timezone.now()
    incident.state = FlwIncident.STATE_RESOLVED
    incident.resolved_at = moment
    incident.save(update_fields=["state", "resolved_at", "updated_at"])
    return incident


def open_incident_count(tenant_id: str) -> int:
    """Nombre d'incidents encore vivants, tous connecteurs confondus."""
    return FlwIncident.objects.filter(
        tenant_id=tenant_id, state__in=FlwIncident.LIVE_STATES
    ).count()


__all__ = [
    "RECOVERY_ACTIONS",
    "live_incident",
    "open_incident_count",
    "record_failure",
    "recovery_action",
    "resolve_incident",
]
