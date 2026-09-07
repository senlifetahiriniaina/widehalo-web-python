"""S7 — l'authentification de l'API publique, son debit, et sa premiere
operation.

Trois criteres : API-1 (aucune elevation), API-6 (revocation immediate),
API-7 (debit par cle, reponse normalisee avec delai d'attente).

**Pourquoi une surface SEPAREE et pas un routeur de plus sur `config.api`.**
Le cahier borne les deux surfaces separement — 1 500 endpoints internes,
80 operations publiques — « parce qu'elle a un cout de retrocompatibilite
que les endpoints internes n'ont pas : une operation publiee ne se retire
plus ». Les melanger rendrait le plafond public inapplicable, et surtout
ferait qu'un endpoint interne ajoute par megarde au mauvais routeur
deviendrait public sans que personne ne l'ait decide.

**La cle designe sa societe.** Un client public n'envoie pas de
`X-Tenant-Id` : il n'a pas a connaitre nos identifiants internes, et le
laisser en choisir un reviendrait a lui laisser choisir la societe dans
laquelle on cherche sa cle. C'est le resolveur declare a
`core.services.tenant_resolvers` qui pose la societe, avant la vue, par le
meme chemin que le middleware utilise depuis la Phase 1 — donc avec
`SET LOCAL app.tenant_id`, donc avec la RLS.
"""

from __future__ import annotations

import functools
from typing import Any

from django.core.cache import cache
from django.utils.translation import gettext as _
from ninja import Router
from ninja.security import HttpBearer

from apps.core.errors import ProblemDetailResponse
from apps.flows.public_operations import (
    PublicOperation,
    get_public_operation,
    register_public_operation,
)
from apps.flows.services import api_keys

#: Fenetre du compteur de debit, en secondes. Une heure, comme
#: `core.throttling.WINDOW_SECONDS` — le cahier parle d'un « debit maximal »
#: sans fixer la fenetre, et deux fenetres differentes dans le meme produit
#: rendraient les deux plafonds incomparables.
RATE_WINDOW_SECONDS = 3600


class PublicApiKeyAuth(HttpBearer):
    """`Authorization: Bearer wh_...`.

    **Resout la cle a CHAQUE appel, sans cache**, et c'est la lecture
    stricte d'API-6 : « la revocation est effective immediatement, y
    compris pour les appels en cours d'authentification ». Un cache d'une
    seconde suffirait a laisser passer l'appel qu'on cherche justement a
    arreter.

    Rend l'UTILISATEUR porte par la cle, jamais la cle : tout le contrat
    interne du produit — `require_permission`, `request.auth.has_perm`, le
    filtrage par societe — attend un utilisateur, et le lui donner est ce
    qui tient API-1 sans recopier la matrice de droits dans un second
    mecanisme."""

    def authenticate(self, request: Any, token: str) -> Any:
        key = api_keys.authenticate(token)
        if key is None:
            return None
        # Pose sur la requete pour que la vue puisse verifier la PORTEE et
        # le DEBIT sans re-resoudre la cle. Ce n'est pas un cache entre
        # requetes — c'est le passage du resultat a l'interieur d'une seule.
        request.api_key = key
        api_keys.touch(key)
        return key.user


def resolve_tenant_from_api_key(request: Any) -> str | None:
    """Resolveur declare a `core.services.tenant_resolvers`.

    S'execute dans le middleware, AVANT l'authentification de django-ninja :
    la societe doit etre active quand la vue lit la base, et
    `authenticate()` est appele trop tard pour cela.

    Ne regarde que les chemins de l'API publique. Un jeton `wh_` presente
    sur la surface interne ne doit rien ouvrir — c'est le sens meme de deux
    surfaces separees.

    **Ne touche PAS a la base**, et c'est la seule facon que ce resolveur
    puisse fonctionner : la cle vit sous Row-Level Security, donc invisible
    tant qu'aucune societe n'est active — c'est-a-dire exactement ici. La
    societe est donc LUE DANS LE JETON (cf. `api_keys.tenant_id_of`). La
    verifier n'est pas le role de cette fonction : c'est
    `PublicApiKeyAuth.authenticate` qui cherchera l'empreinte SOUS cette
    societe, et une societe usurpee y cachera la cle plutot que de
    l'exposer."""
    chemin = getattr(request, "path", "") or ""
    if not chemin.startswith("/api/public/"):
        return None
    entete = request.headers.get("Authorization", "")
    if not entete.startswith("Bearer "):
        return None
    return api_keys.tenant_id_of(entete.removeprefix("Bearer ").strip())


def _rate_limited(request: Any) -> ProblemDetailResponse | None:
    """API-7 : le debit, PAR CLE.

    « N'affecte ni les autres cles du tenant ni les autres tenants » : le
    compteur est donc indexe sur l'identifiant de la CLE, jamais sur celui
    du tenant ni sur celui de l'utilisateur — deux cles d'un meme
    integrateur, l'une pour son bac a sable et l'autre pour sa production,
    ne doivent pas se penaliser.

    « Une reponse normalisee avec DELAI D'ATTENTE INDIQUE » : d'ou le
    `Retry-After`, que la limitation generique du produit
    (`core.throttling`) ne pose pas. Sans lui, un client bien eleve n'a
    d'autre choix que de reessayer au hasard, ce qui aggrave exactement la
    situation qu'on borne."""
    key = getattr(request, "api_key", None)
    if key is None:
        return None
    clef_compteur = f"public-api-rate:{key.id}"
    compte = cache.get(clef_compteur, 0)
    if compte >= key.rate_limit_per_hour:
        reste = cache.ttl(clef_compteur) if hasattr(cache, "ttl") else RATE_WINDOW_SECONDS
        attente = int(reste or RATE_WINDOW_SECONDS)
        reponse = ProblemDetailResponse(
            status=429,
            title=_("Trop de requêtes"),
            detail=_(
                "Débit maximal de cette clé atteint (%(limite)s par heure). "
                "Réessayez dans %(attente)s seconde(s)."
            )
            % {"limite": key.rate_limit_per_hour, "attente": attente},
            instance=request.path,
            retry_after=attente,
        )
        reponse["Retry-After"] = str(attente)
        return reponse
    if compte == 0:
        cache.set(clef_compteur, 1, timeout=RATE_WINDOW_SECONDS)
    else:
        cache.incr(clef_compteur)
    return None


def _refused(request: Any, operation_code: str) -> ProblemDetailResponse | None:
    """DEUX controles, et il en manquait un.

    **La portee** (API-2, cote jeton) : la cle nomme-t-elle cette
    operation ? Le message NOMME ce qui manque — le client connait la liste
    des operations publiques, elle est publiee, et ne pas la nommer
    obligerait un integrateur a deviner laquelle de ses vingt portees est
    absente.

    **Le DROIT du porteur** (API-1) : l'utilisateur que porte la cle
    detient-il la permission declaree par l'operation ? Ce second controle
    manquait au premier jet, et son absence rendait `PublicOperation.
    permission` decoratif — un champ declare, documente, et lu par
    personne, c'est-a-dire exactement le defaut que ce chantier corrige
    partout ailleurs. Il a ete trouve par le test qui recopie le critere
    mot pour mot : « un jeton de portee commerciale interrogeant des
    donnees comptables ». Sans lui, une portee ELEVAIT les droits de son
    porteur — l'inverse exact de ce qu'API-1 exige.

    L'ordre compte : la portee d'abord. Un integrateur dont la cle ne porte
    pas l'operation doit s'entendre dire cela, et non qu'il lui manque un
    droit qu'il ne saurait pas comment obtenir."""
    key = getattr(request, "api_key", None)
    if key is None:
        return None
    if not api_keys.allows(key, operation_code):
        return ProblemDetailResponse(
            status=403,
            title=_("Portée insuffisante"),
            detail=_("Cette clé ne porte pas l'opération « %(operation)s ».")
            % {"operation": operation_code},
            instance=request.path,
        )
    operation = get_public_operation(operation_code)
    if operation is not None and not key.user.has_perm(operation.permission):
        return ProblemDetailResponse(
            status=403,
            title=_("Droit insuffisant"),
            detail=_(
                "Le compte porté par cette clé n'a pas le droit de consulter « %(operation)s »."
            )
            % {"operation": operation.label},
            instance=request.path,
        )
    return None


def _with_deprecation_headers(reponse: Any, operation_code: str) -> Any:
    """Pose `Deprecation` et `Sunset` (RFC 8594) sur toute reponse d'une
    operation depreciee.

    **Sur la reponse, et pas seulement dans la documentation.** Un
    integrateur ne relit pas la documentation d'une operation qui marche ;
    il lit ses en-tetes s'il a un outil qui les lui montre, et il les
    ignore sinon. Les poser coute une ligne et rend la politique de
    depreciation opposable a ceux qui savent les lire — les autres restent
    prevenus par l'OpenAPI, ou l'operation est marquee.

    Une reponse qui n'est pas un objet HTTP (un dict rendu par ninja) passe
    inchangee : ninja construira sa reponse plus tard, et l'en-tete se
    perdrait. C'est une LIMITE assumee de cette version, ecrite plutot que
    tue : aujourd'hui aucune operation n'est depreciee, et le jour ou l'une
    le sera, elle rendra une reponse explicite."""
    operation = get_public_operation(operation_code)
    if operation is None or not operation.is_deprecated:
        return reponse
    if not hasattr(reponse, "__setitem__"):
        return reponse
    reponse["Deprecation"] = operation.deprecated_since
    reponse["Sunset"] = operation.sunset_on
    return reponse


class _PublicOperationView:
    """Le garde d'une operation publique : portee, droit, debit.

    **Un objet appelable plutot qu'une fermeture**, et le motif est deja
    ecrit dans ce depot, au prix d'un defaut trouve empiriquement
    (`core.services.permissions._PermissionGuardedView`) : django-ninja
    reconstruit le type des parametres annotes par une chaine via
    `getattr(call, "__globals__", {})`, SANS remonter la chaine
    `__wrapped__`. Une fermeture a un `__globals__` fige sur le module ou
    elle est definie — ici `apps.flows.api_public` — et tout endpoint dont
    le corps est un `Schema` serait alors mal classifie, donc casse pour
    tout appelant. Un objet delegue `__globals__` a la vue d'origine.

    **Pourquoi un decorateur et pas trois appels dans chaque vue.** C'est ce
    qui rend API-2 STRUCTUREL plutot que memorise : « aucune operation non
    declaree n'est atteignable par un jeton client ». Avec des appels a la
    main, une vue publique ajoutee sans eux serait ouverte a toute cle, en
    silence. Avec le decorateur, la garde d'architecture peut EXIGER que
    chaque route publique en porte un — et le lien route/operation devient
    inspectable, ce qu'il n'etait pas."""

    def __init__(self, func: Any, code: str) -> None:
        functools.update_wrapper(self, func)
        self._func = func
        self.public_operation_code = code

    def __call__(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        refus = _refused(request, self.public_operation_code) or _rate_limited(request)
        if refus is not None:
            return _with_deprecation_headers(refus, self.public_operation_code)
        return _with_deprecation_headers(
            self._func(request, *args, **kwargs), self.public_operation_code
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._func, name)


def public_operation(code: str) -> Any:
    """Decore une vue publique par le CODE de l'operation qu'elle sert.

    L'ordre des decorateurs n'est pas indifferent, et c'est la meme regle
    que pour `require_permission` : `@router.get(...)` reste le decorateur
    EXTERNE et celui-ci l'INTERNE, juste au-dessus du `def`. `Router.
    api_operation` enregistre la fonction qu'on lui passe puis la retourne
    inchangee ; place a l'exterieur, ce garde n'intercepterait plus jamais
    aucune requete."""

    def decorator(func: Any) -> Any:
        return _PublicOperationView(func, code)

    return decorator


#: La premiere operation publique, et elle n'est pas choisie au hasard : le
#: cahier la nomme dans le contenu du bloc B — « journal d'appel consultable
#: par le client » (§14.2). C'est aussi la seule que l'integrateur peut
#: utiliser sans rien connaitre du metier, donc la bonne pour eprouver la
#: chaine complete : cle, portee, societe, debit, droits.
OPERATION_EXCHANGES_READ = "exchanges.read"


def register_operations() -> None:
    register_public_operation(
        PublicOperation(
            code=OPERATION_EXCHANGES_READ,
            label="Journal des échanges",
            permission="flows.view_flwexchange",
            description=(
                "Les échanges de la société, du plus récent au plus ancien. "
                "Le « journal d'appel consultable par le client » du cahier (§14.2)."
            ),
        )
    )


router = Router(tags=["public"], auth=PublicApiKeyAuth())


@router.get("/exchanges")
@public_operation(OPERATION_EXCHANGES_READ)
def list_exchanges(request: Any, limit: int = 50) -> Any:
    """Le journal d'echange du client, borne et filtre par sa societe.

    Aucune charge utile n'est rendue, et ce n'est pas un oubli : le journal
    prouve QU'un echange a eu lieu et ce qu'il est devenu. Rendre le contenu
    ferait de cette operation un canal d'exfiltration de pieces metier, avec
    une portee qui n'annonce qu'un journal."""
    from apps.flows.models import FlwExchange

    plafond = max(1, min(int(limit), 200))
    echanges = FlwExchange.objects.select_related("link").order_by("-created_at")[:plafond]
    return {
        "results": [
            {
                "id": str(echange.id),
                "direction": echange.direction,
                "operation": echange.operation,
                "state": echange.state,
                "attempt": echange.attempt,
                "result_code": echange.result_code,
                "payload_fingerprint": echange.payload_fingerprint,
                "created_at": echange.created_at,
                "settled_at": echange.settled_at,
            }
            for echange in echanges
        ]
    }


__all__ = [
    "OPERATION_EXCHANGES_READ",
    "public_operation",
    "PublicApiKeyAuth",
    "register_operations",
    "resolve_tenant_from_api_key",
    "router",
]
