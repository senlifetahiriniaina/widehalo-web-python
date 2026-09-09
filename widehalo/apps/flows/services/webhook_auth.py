"""T5 (bloc B, API-3) — authentifier un appel entrant, une fois pour tous.

**Le critère** : « Un appel de webhook non signé, mal signé ou horodaté
hors fenêtre est rejeté sans traitement, et journalisé sans révéler le
motif à l'appelant. »

Les trois refus sont distincts et se vérifient séparément ; la dernière
moitié de la phrase l'est tout autant : **le motif n'est jamais rendu à
l'appelant**. Dire « signature invalide » plutôt que « horodatage hors
fenêtre » apprend à qui essaie où il en est de son attaque. L'exploitant,
lui, a besoin du motif — il va dans le journal.

**Pourquoi ce module vit dans `flows` et pas dans `logistics`.** La
vérification HMAC existe déjà — `logistics/services/webhooks.py`, écrite
pour le webhook transporteur — et sa docstring demande elle-même ce qui se
passe ici : « à généraliser vers `core` si un futur module en a besoin à
son tour ». Ce futur module est arrivé. Elle atterrit dans `flows` plutôt
que dans `core` parce que c'est le hub qui possède la notion de LIAISON,
et qu'une signature entrante se vérifie contre le secret d'une liaison.

**Ce que les deux webhooks existants font chacun à moitié**, et que
celui-ci fait en entier : `logistics` signe mais ne traite rien ;
`whatsapp` traite mais ne signe pas, et le fait en synchrone dans le
thread web. Aucun des deux n'horodate ni ne se protège du rejeu.

**Le secret n'a pas de champ neuf.** `FlwCredential` porte déjà
`KIND_WEBHOOK_SECRET` et un `secret` chiffré — le cahier exige ce logement
(§13.2, « table à part, chiffrée, jamais exportée »), et lui en inventer
un second sur `FlwLink` aurait créé une seconde source de vérité pour la
même question.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import logging
from dataclasses import dataclass

from django.utils import timezone

from apps.flows.models import FlwCredential, FlwExchange, FlwLink

logger = logging.getLogger(__name__)

#: La fenêtre d'acceptation d'un horodatage, en secondes. Cinq minutes :
#: assez large pour absorber une horloge mal réglée chez un opérateur et
#: une re-livraison immédiate, assez étroite pour qu'un appel capturé ne
#: soit pas rejouable une heure plus tard.
#:
#: La fenêtre est SYMÉTRIQUE — un horodatage dans le futur est refusé au
#: même titre qu'un horodatage trop ancien. N'en border qu'un seul côté
#: laisserait passer un appel daté de 2030, que rien n'expirerait jamais.
TIMESTAMP_WINDOW_SECONDS = 300

#: Les en-têtes lus. Nommés ici plutôt que dans la vue : trois adaptateurs
#: qui les recopieraient chacun de son côté finiraient par en écrire un de
#: travers, et le défaut serait un refus silencieux.
HEADER_SIGNATURE = "X-Signature"
HEADER_TIMESTAMP = "X-Timestamp"

#: Les motifs de refus. Ils vont au JOURNAL, jamais à l'appelant.
#
# `noqa: S105` : l'analyseur voit un mot de passe codé en dur. C'est un
# MESSAGE DE REFUS, qui dit qu'aucun secret n'est configuré — il ne
# contient aucun secret. Même traitement et même motif que
# `FlwCredential.KIND_WEBHOOK_SECRET` : le motif est écrit plutôt que
# contourné par un renommage qui ferait taire l'analyseur sans rien
# changer, et rendrait la constante moins lisible.
REASON_NO_SECRET = "aucun secret de webhook configuré sur la liaison"  # noqa: S105
REASON_MISSING_SIGNATURE = "signature absente"
REASON_BAD_SIGNATURE = "signature invalide"
REASON_MISSING_TIMESTAMP = "horodatage absent"
REASON_MALFORMED_TIMESTAMP = "horodatage illisible"
REASON_STALE_TIMESTAMP = "horodatage hors fenêtre"
REASON_REPLAY = "charge utile déjà reçue sur cette liaison"


@dataclass(frozen=True)
class Verdict:
    """Accepté, ou refusé AVEC son motif.

    Un booléen aurait suffi à la vue — qui ne fait que refuser — mais pas
    au journal, et c'est le journal qui rend le refus exploitable. Le motif
    ne franchit jamais la frontière HTTP : c'est l'appelant de
    `verify_inbound_call` qui décide de le journaliser, et il ne le rend
    jamais dans la réponse."""

    accepted: bool
    reason: str = ""


def verify_inbound_call(
    link: FlwLink,
    *,
    payload: bytes,
    signature: str,
    timestamp: str,
    now: dt.datetime | None = None,
) -> Verdict:
    """Les trois contrôles d'API-3, dans l'ordre le moins coûteux d'abord.

    L'ordre n'est pas indifférent : vérifier l'horodatage avant la
    signature évite de calculer un HMAC pour un appel qu'on va refuser de
    toute façon, et refuser un appel sans secret configuré avant tout le
    reste évite de comparer contre rien.

    **Un secret absent refuse**, il n'accepte pas par défaut. C'est la
    règle que `logistics/services/webhooks.py` a posée en premier — « un
    webhook non configuré pour la signature ne doit jamais être traité
    comme valide par défaut » — et l'inverse ouvrirait le point d'entrée à
    quiconque connaît un identifiant de liaison."""
    secret = _webhook_secret(link)
    if not secret:
        return Verdict(accepted=False, reason=REASON_NO_SECRET)

    verdict_horodatage = _check_timestamp(timestamp, now=now)
    if not verdict_horodatage.accepted:
        return verdict_horodatage

    if not signature:
        return Verdict(accepted=False, reason=REASON_MISSING_SIGNATURE)
    attendu = hmac.new(secret.encode("utf-8"), _signed_bytes(timestamp, payload), hashlib.sha256)
    if not hmac.compare_digest(attendu.hexdigest(), signature):
        return Verdict(accepted=False, reason=REASON_BAD_SIGNATURE)

    if _already_received(link, payload):
        return Verdict(accepted=False, reason=REASON_REPLAY)

    return Verdict(accepted=True)


def _signed_bytes(timestamp: str, payload: bytes) -> bytes:
    """Ce sur quoi la signature porte : l'horodatage ET le corps.

    Signer le seul corps laisserait rejouer un appel authentique avec un
    horodatage neuf — la fenêtre ne servirait alors à rien, puisque
    l'attaquant choisirait lui-même la valeur qu'elle contrôle. Les lier
    est ce qui rend la fenêtre opposable."""
    return timestamp.encode("utf-8") + b"." + payload


def _check_timestamp(timestamp: str, *, now: dt.datetime | None) -> Verdict:
    if not timestamp:
        return Verdict(accepted=False, reason=REASON_MISSING_TIMESTAMP)
    try:
        envoye_le = dt.datetime.fromtimestamp(int(timestamp), tz=dt.UTC)
    except (ValueError, OverflowError, OSError):
        return Verdict(accepted=False, reason=REASON_MALFORMED_TIMESTAMP)

    maintenant = now or timezone.now()
    ecart = abs((maintenant - envoye_le).total_seconds())
    if ecart > TIMESTAMP_WINDOW_SECONDS:
        return Verdict(accepted=False, reason=REASON_STALE_TIMESTAMP)
    return Verdict(accepted=True)


def _already_received(link: FlwLink, payload: bytes) -> bool:
    """API-4 — « un même événement entrant reçu deux fois produit un seul
    traitement métier ».

    L'empreinte est celle que `FlwExchange` calcule déjà et qui SURVIT à la
    purge de la charge utile (FLX-5) : la protection tient donc encore
    quand le corps a été purgé, ce qu'une comparaison de corps ne ferait
    pas. Portée à la liaison, jamais au tenant seul : deux liaisons peuvent
    légitimement recevoir la même charge utile."""
    empreinte = FlwExchange.fingerprint_of(payload.decode("utf-8", errors="replace"))
    return FlwExchange.objects.filter(
        tenant=link.tenant,
        link=link,
        direction=FlwExchange.DIRECTION_INBOUND,
        payload_fingerprint=empreinte,
    ).exists()


def _webhook_secret(link: FlwLink) -> str:
    """Le secret de webhook porté par le connecteur de cette liaison.

    Lu par le CONNECTEUR et non par la liaison : c'est l'adaptateur qui
    définit la façon de signer, et deux liaisons du même connecteur chez le
    même tenant partagent donc le même secret. Le jour où un opérateur
    exigerait un secret par liaison, c'est ici que la lecture change."""
    credential = FlwCredential.objects.filter(
        tenant=link.tenant,
        connector=link.connector,
        kind=FlwCredential.KIND_WEBHOOK_SECRET,
    ).first()
    return credential.secret if credential is not None else ""


__all__ = [
    "HEADER_SIGNATURE",
    "HEADER_TIMESTAMP",
    "TIMESTAMP_WINDOW_SECONDS",
    "Verdict",
    "verify_inbound_call",
]
