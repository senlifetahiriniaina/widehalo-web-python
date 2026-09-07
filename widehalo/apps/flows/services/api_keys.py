"""S7 — emission, authentification et revocation des cles publiques.

Trois criteres tiennent ici : API-1 (aucune elevation par l'API), API-6
(revocation immediate, « y compris pour les appels en cours
d'authentification ») et API-7 (debit par cle).

**Le clair du jeton n'existe qu'une fois.** `issue_key` le rend a
l'appelant et n'en garde que l'empreinte. Ce n'est pas une precaution de
principe : une cle qu'on peut relire est une cle qu'un export, une
sauvegarde ou une capture d'ecran de support peut emporter, et le cahier
range explicitement les identifiants de tiers parmi ce qui n'est « jamais
exporte » (§13.2).

**La revocation est verifiee A CHAQUE APPEL, jamais mise en cache**, et
c'est la lecture stricte d'API-6. « Effective immediatement, Y COMPRIS POUR
LES APPELS EN COURS D'AUTHENTIFICATION » : un cache d'une seconde suffirait
a laisser passer l'appel qu'on cherche justement a arreter. Le cout est une
lecture indexee par requete, ce qui est exactement ce que fait deja
l'authentification par jeton JWT du produit.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from apps.flows.models import FlwApiKey

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User

#: Longueur du secret, en octets avant encodage. 32 octets = 256 bits, meme
#: ordre que les jetons d'invitation du depot. En dessous, une cle devient
#: devinable par force brute sur une adresse publique ; au-dessus, on
#: n'ajoute rien qu'un jeton plus penible a recopier.
TOKEN_BYTES = 32

#: Le prefixe affichable, en tete du jeton. `wh_` pour que la cle soit
#: reconnaissable dans un journal de client tiers et attrapable par un
#: detecteur de secrets — le notre comme celui d'un depot de code ou elle
#: serait collee par erreur.
#
#: `noqa: S105` : l'analyseur y voit un mot de passe code en dur. C'est le
#: contraire — c'est la partie PUBLIQUE du jeton, celle qu'on affiche.
TOKEN_PREFIX = "wh_"  # noqa: S105

#: Ce qui est stocke en clair pour l'affichage : le prefixe et les six
#: premiers caracteres du SECRET. Assez pour distinguer trois cles a
#: l'ecran, trop peu pour reduire la recherche exhaustive de facon utile.
VISIBLE_SECRET_CHARS = 6


def tenant_id_of(raw_token: str) -> str | None:
    """La societe designee par le jeton, LUE SANS TOUCHER A LA BASE.

    **Le defaut que cette fonction repare, et il etait fatal en
    production.** `FlwApiKey` herite de `BaseModel`, donc de la
    Row-Level Security : la policy PostgreSQL n'expose une ligne que si
    `app.tenant_id` designe sa societe. Or l'authentification se produit
    AVANT que la societe soit connue — c'est justement la cle qui la
    designe. En debut de requete, `app.tenant_id` est vide, la policy ne
    rend AUCUNE ligne, et la cle n'est jamais trouvee : l'API publique
    n'aurait pu authentifier personne.

    Le test ne l'avait pas vu tout de suite, et pour une raison qu'il faut
    ecrire : sous pytest, une transaction englobante fait survivre le
    `SET LOCAL` d'un `use_tenant` precedent, si bien que la policy laissait
    passer par accident. C'est le second faux positif de ce genre releve
    dans ce depot — le premier concernait la falsification de la policy
    elle-meme.

    **La societe voyage donc DANS le jeton**, en clair et sans secret :
    `wh_<societe>_<secret>`. Ce n'est pas une fuite — un integrateur de
    l'API interne envoie deja `X-Tenant-Id` — et cela ne relache aucun
    controle : un attaquant qui remplacerait la societe par une autre
    ferait chercher l'empreinte sous cette societe-la, ou la policy la
    cache. La verification echoue donc, et elle echoue FERMEE.

    Rend `None` sur tout jeton mal forme, sans lever : cette fonction
    s'execute dans le middleware, ou une exception transformerait un jeton
    mal recopie en panne generale."""
    if not raw_token.startswith(TOKEN_PREFIX):
        return None
    reste = raw_token.removeprefix(TOKEN_PREFIX)
    societe, _separateur, secret = reste.partition("_")
    if not secret or len(societe) != 32:
        return None
    try:
        return str(uuid.UUID(hex=societe))
    except ValueError:
        return None


def fingerprint(raw_token: str) -> str:
    """Empreinte SHA-256 d'un jeton. Deterministe, donc indexable — c'est
    ce qui permet de retrouver une cle en une lecture, contrairement a un
    hachage sale par ligne, qui obligerait a parcourir toute la table."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def issue_key(
    tenant: Tenant,
    user: User,
    *,
    label: str,
    scopes: Sequence[str],
    rate_limit_per_hour: int = 1000,
    expires_at: datetime | None = None,
) -> tuple[FlwApiKey, str]:
    """Cree une cle et rend le couple (ligne, JETON EN CLAIR).

    Le clair est rendu UNE FOIS et n'est jamais relisible. L'appelant doit
    le montrer immediatement a l'utilisateur ; s'il le perd, la reponse est
    d'emettre une nouvelle cle, jamais de retrouver l'ancienne."""
    secret = secrets.token_urlsafe(TOKEN_BYTES)
    raw = f"{TOKEN_PREFIX}{tenant.id.hex}_{secret}"
    key = FlwApiKey.objects.create(
        tenant=tenant,
        user=user,
        label=label,
        # Le prefixe AFFICHABLE ne montre pas la societe — elle n'apprend
        # rien a un exploitant qui regarde ses propres cles — mais les six
        # premiers caracteres du secret, qui sont ce qui les distingue.
        prefix=TOKEN_PREFIX + secret[:VISIBLE_SECRET_CHARS],
        token_hash=fingerprint(raw),
        scopes=list(scopes),
        rate_limit_per_hour=rate_limit_per_hour,
        expires_at=expires_at,
    )
    return key, raw


def authenticate(raw_token: str) -> FlwApiKey | None:
    """Resout un jeton en cle utilisable, ou `None`.

    **Lecture par `objects`, donc SOUS LA SOCIETE ACTIVE.** C'est
    `tenant_id_of` qui l'a posee, depuis le jeton lui-meme et sans toucher
    a la base (cf. sa docstring : sans cela, la Row-Level Security cachait
    la cle a sa propre authentification). Passer par `all_objects` aurait
    ete plus simple a ecrire et strictement plus faible : la policy
    PostgreSQL devient ici une seconde verification, pas un obstacle a
    contourner — une cle presentee sous une societe qui n'est pas la sienne
    est invisible, donc refusee.

    `None` pour toutes les causes de refus — jeton inconnu, revoque,
    expire, archive — et jamais un motif different par cas : dire a un
    appelant que sa cle « existe mais est expiree » lui apprend qu'elle
    existe."""
    if not raw_token:
        return None
    key = (
        FlwApiKey.objects.select_related("user", "tenant")
        .filter(token_hash=fingerprint(raw_token))
        .first()
    )
    if key is None or not key.is_usable():
        return None
    return key


def touch(key: FlwApiKey) -> None:
    """Horodate l'usage, sans toucher `updated_at`.

    `update()` plutot que `save()` : passer par `save()` declencherait les
    signaux d'audit a chaque appel d'API, ce qui ferait du journal d'audit
    un journal d'acces — deux objets differents, avec deux durees de
    conservation differentes."""
    FlwApiKey.all_objects.filter(pk=key.pk).update(last_used_at=timezone.now())


def revoke(key: FlwApiKey, *, reason: str = "") -> FlwApiKey:
    """Revoque une cle. Idempotent : une cle deja revoquee garde SA date.

    Ecraser la date d'une revocation par une seconde revocation effacerait
    le seul element qui permette de dire si un appel etait legitime au
    moment ou il a eu lieu."""
    with transaction.atomic():
        if key.revoked_at is None:
            key.revoked_at = timezone.now()
            key.revoked_reason = reason
            key.save(update_fields=["revoked_at", "revoked_reason", "updated_at"])
    return key


def allows(key: FlwApiKey, operation_code: str) -> bool:
    """La cle porte-t-elle cette operation dans sa portee ?

    Deny-by-default : une portee vide n'autorise RIEN. L'inverse — « vide
    veut dire tout » — est le reglage par defaut le plus dangereux qui
    soit, parce qu'il transforme un oubli de saisie en cle universelle."""
    return operation_code in (key.scopes or [])


__all__ = [
    "TOKEN_PREFIX",
    "tenant_id_of",
    "allows",
    "authenticate",
    "fingerprint",
    "issue_key",
    "revoke",
    "touch",
]
