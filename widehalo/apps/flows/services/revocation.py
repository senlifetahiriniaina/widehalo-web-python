"""T9 (CON-3) — couper un connecteur, sans rien effacer de ce qu'il a fait.

**Le critere** : « Une revocation coupe le connecteur immediatement,
conserve les echanges passes et propose la purge des charges utiles
restantes. »

**Trois exigences distinctes, et aucune ne se deduit des autres.**

1. *Couper immediatement.* La vidange ne sert deja que les liaisons
   `active` — une liaison revoquee cesse donc d'emettre sans qu'on ajoute
   quoi que ce soit. C'est verifie plutot que suppose : une clause de
   filtre se change, et le jour ou elle changerait, la revocation
   deviendrait decorative.
2. *Conserver les echanges passes.* Rien n'est supprime. Le registre est la
   preuve de ce qui est parti, et une revocation qui effacerait cette
   preuve serait exactement l'inverse de ce que la Phase 4 construit.
3. *Proposer la purge des charges utiles restantes.* PROPOSER, pas faire :
   le contenu echange peut encore etre necessaire — a une reclamation, a un
   controle. La purge est donc une seconde decision, offerte au moment de
   la revocation parce que c'est le moment ou la question se pose.

**Revoquee n'est pas suspendue.** Une liaison suspendue reprend — plafond
atteint, panne passagere. Une liaison revoquee ne reprend pas : le
consentement de sortie a ete retire, et la rouvrir demande un nouveau
consentement, ce que la garde d'activation impose deja.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.flows.models import FlwLink, FlwPayload

if TYPE_CHECKING:
    import datetime as dt

    from apps.core.models.user import User

#: Motif minimal exige. Meme discipline que partout ailleurs dans ce depot :
#: un motif d'une lettre n'explique rien a celui qui relira la decision dans
#: six mois.
MOTIF_MINIMUM = 40


def revoke_link(
    link: FlwLink,
    *,
    revoked_by: User,
    reason: str,
    now: dt.datetime | None = None,
) -> FlwLink:
    """Revoque une liaison. Ne purge rien : la purge est une seconde
    decision, cf. `purge_remaining_payloads`."""
    motif = (reason or "").strip()
    if len(motif) < MOTIF_MINIMUM:
        raise ValidationError(
            _(
                "Un motif de révocation d'au moins %(n)d caractères est exigé : "
                "cette décision coupe un canal, et celui qui la relira dans six "
                "mois doit savoir pourquoi."
            )
            % {"n": MOTIF_MINIMUM}
        )
    if link.state == FlwLink.STATE_REVOKED:
        return link

    link.state = FlwLink.STATE_REVOKED
    link.revoked_at = now or timezone.now()
    link.revoked_by = revoked_by
    link.revoked_reason = motif
    link.save(update_fields=["state", "revoked_at", "revoked_by", "revoked_reason"])
    return link


def remaining_payload_count(link: FlwLink) -> int:
    """Combien de charges utiles cette liaison porte encore.

    Le chiffre est ce qui rend la proposition de purge intelligible : « 0 »
    dispense de la poser, « 12 400 » n'appelle pas la meme reflexion que
    « 3 »."""
    return FlwPayload.objects.filter(exchange__link=link).count()


def purge_remaining_payloads(link: FlwLink) -> int:
    """Supprime les charges utiles restantes de cette liaison, et rend leur
    nombre.

    **Les ECHANGES survivent, et c'est tout le mecanisme de FLX-5** :
    l'empreinte reste sur l'echange, la ligne de charge utile disparait, et
    `FlwExchange.payload_is_purged` sait ensuite distinguer « purgee » de
    « jamais ecrite ». On peut donc toujours prouver CE QUI a ete envoye
    sans conserver les donnees personnelles qu'il contenait."""
    with transaction.atomic():
        queryset = FlwPayload.objects.filter(exchange__link=link)
        nombre = queryset.count()
        queryset.delete()
    return nombre


__all__ = [
    "MOTIF_MINIMUM",
    "purge_remaining_payloads",
    "remaining_payload_count",
    "revoke_link",
]
