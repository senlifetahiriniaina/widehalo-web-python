"""L'API PUBLIQUE — surface separee, versionnee, plafonnee a 80 operations.

**Separee de `config.api`, et ce n'est pas une commodite de rangement.** Le
cahier borne les deux surfaces independamment — 1 500 endpoints internes,
80 operations publiques — « parce qu'elle a un cout de retrocompatibilite
que les endpoints internes n'ont pas : une operation publiee ne se retire
plus, elle se deprecie sur plusieurs versions ». Deux consequences
pratiques : le plafond public reste applicable sans dependre du rythme
interne, et un routeur interne ajoute par megarde ici serait un
engagement public pris sans decision.

`tests/architecture/test_phase4_budgets.py` compte les operations de ce
module depuis le sprint S1, avant meme qu'il n'existe : le compteur rendait
zero et le test d'amorcage le disait explicitement plutot que de laisser un
zero passer pour une mesure.

**Pas d'authentification par defaut au niveau de l'instance** : chaque
routeur porte la sienne (`PublicApiKeyAuth`). Poser une authentification
globale ici rendrait invisible le jour ou un routeur oublierait la sienne —
il heriterait silencieusement de celle du parent.
"""

from apps.core.errors import register_exception_handlers
from apps.flows.api_public import router as flows_public_router
from ninja import NinjaAPI

public_api = NinjaAPI(
    title="WideHalo API publique",
    version="public-v1",
    urls_namespace="api-public-v1",
    # `auth=None` explicite : voir la docstring du module.
    auth=None,
    description=(
        "Surface publique de WideHalo. Chaque opération est déclarée, nommée et "
        "portée par une clé ; une opération publiée ne se retire pas, elle se "
        "déprécie. Authentification : `Authorization: Bearer wh_...`."
    ),
)

# Les memes conventions d'erreur que la surface interne (RFC 7807), et les
# memes gestionnaires — dont ceux ajoutes en prealable du bloc B, qui
# transforment un refus de service en 422 et un objet introuvable en 404
# plutot qu'en 500. Un integrateur tiers est precisement celui qui ne
# pardonne pas un 500 sur une entree qu'il a mal formee.
register_exception_handlers(public_api)

public_api.add_router("", flows_public_router)
