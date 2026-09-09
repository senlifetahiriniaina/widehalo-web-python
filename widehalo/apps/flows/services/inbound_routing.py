"""T5 — la seule lecture du hub qui ait lieu SANS societe active, et elle
ne rend qu'une chose : quelle societe activer.

**Le probleme, et il est de poule et d'oeuf.** Un operateur qui appelle
`/api/v1/flows/webhooks/{link_id}` n'a ni session, ni jeton applicatif, ni
en-tete de societe — lui en faire envoyer un reviendrait a laisser
l'appelant choisir la societe dans laquelle il ecrit. La liaison EST donc
l'unique moyen de savoir quelle societe activer ; mais `flw_link` est en
`FORCE ROW LEVEL SECURITY`, et sans `app.tenant_id` PostgreSQL ne rend
aucune ligne. `all_objects` n'y change rien : il contourne la RLS
APPLICATIVE de `TenantManager`, jamais celle de la base.

**Ce qui est ouvert, et ce qui ne l'est pas.** La migration `flows/0009`
pose une seconde policy `webhook_lookup_policy`, `FOR SELECT` uniquement,
conditionnee au reglage de session que ce module — et lui seul — sait
poser. Les ECRITURES restent gouvernees par la seule policy d'isolation :
une ecriture hors societe reste refusee par PostgreSQL (FLX-7).

**La fenetre ne rend qu'un identifiant de societe**, jamais l'objet. Deux
raisons, et la seconde n'est pas theorique :

1. Moindre exposition. L'appelant n'a besoin que de savoir quelle societe
   activer ; tout le reste se lit ensuite normalement, sous contexte,
   par le manager en refus par defaut.
2. Un `select_related("connector")` dans cette fenetre ne rendrait RIEN.
   `flw_connector` est aussi en `FORCE`, sans policy de lecture anonyme :
   la jointure ramenerait zero ligne, et le point d'entree rendrait 404
   sur un appel parfaitement valide — le defaut d'origine, deplace d'un
   cran.

**Le reglage est remis a zero explicitement.** `SET LOCAL` meurt avec la
TRANSACTION, pas avec le bloc `with` : sous `ATOMIC_REQUESTS`, ou dans un
test que pytest-django enveloppe, le bloc atomique ci-dessous n'est qu'un
point de sauvegarde et le reglage survivrait a la sortie — la fenetre
resterait ouverte pour tout le reste de la requete. C'est exactement le
piege que `core/tenant_context.py` documente pour `app.tenant_id`, et il
se referme de la meme facon : a la main, dans un `finally`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError

from apps.core.db.webhook_lookup import LOOKUP_ON, LOOKUP_SETTING, webhook_lookup_window
from apps.core.identifiers import parse_uuid
from apps.flows.models import FlwLink

if TYPE_CHECKING:
    from uuid import UUID

#: Reexportes depuis `core.db.webhook_lookup`, ou la fenetre vit depuis que
#: le lot T9 a trouve le meme defaut sur le webhook transporteur de
#: `logistics` — qui ne declare pas `flows` dans ses dependances, a juste
#: titre. Un module metier n'a pas a dependre du hub pour ouvrir une
#: transaction ; recopier la fenetre aurait produit deux mecanismes qui
#: divergent au premier correctif.
__all_settings__ = (LOOKUP_SETTING, LOOKUP_ON)


def resolve_tenant_for_inbound_call(link_id: Any) -> UUID | None:
    """La societe a activer pour traiter un appel entrant sur cette liaison.

    Rend `None` si la liaison n'existe pas — ce que l'appelant traduit en
    404, sans distinguer « identifiant inconnu » de « identifiant mal
    forme » : l'un et l'autre n'apprennent rien a qui essaie.

    **Aucune authentification n'a encore eu lieu a ce stade**, et c'est
    normal : le secret de webhook se lit SUR la liaison, donc sous la
    societe de la liaison. Cette fonction ne fait donc que du routage, et
    ne doit jamais servir a autre chose — c'est pour cela qu'elle ne rend
    pas l'objet."""
    try:
        identifiant = parse_uuid(str(link_id), champ="liaison")
    except ValidationError:
        # Un identifiant illisible ne vaut pas mieux qu'un identifiant
        # inconnu : les deux rendent 404. Laisser la conversion remonter
        # rendrait 500 sur une URL malformee — le defaut que T4bis a ferme
        # partout ailleurs, et une surface publique NON AUTHENTIFIEE est le
        # dernier endroit ou on veut le voir revenir.
        return None

    with webhook_lookup_window():
        return _read_tenant_id(identifiant)


def _read_tenant_id(link_id: Any) -> UUID | None:
    """UNE ligne, UNE colonne, designee par son identifiant.

    `all_objects` parce que `TenantManager` est en refus par defaut et
    qu'aucune societe n'est active — c'est le seul appelant du depot pour
    lequel cette absence est normale plutot qu'un oubli.

    **`.order_by()` n'est pas une coquetterie : sans lui, cette fonction
    rend TOUJOURS `None`.** `FlwLink.Meta.ordering` vaut
    `["connector", "name"]`, et Django, quand on trie par une cle
    etrangere, ne trie pas par la colonne locale : il applique l'ordre du
    modele LIE, donc ajoute une jointure sur `flw_connector`. Or cette
    table-la reste en `FORCE ROW LEVEL SECURITY` sans policy de lecture
    anonyme — la jointure ne ramene rien, et la requete rend zero ligne
    alors que la ligne existe et que la policy la laisse passer.

    Mesure faite au diagnostic : `SELECT count(*) FROM flw_link WHERE
    id = ...` rendait 1 dans la meme transaction ou l'ORM rendait `[]`.
    C'est l'ordre implicite, jamais la policy, qui coupait — et aucune
    lecture du code des policies ne l'aurait montre.

    Vider l'ordre est aussi ce qu'il faut ici sur le fond : une lecture par
    cle primaire rend au plus une ligne, un tri n'a rien a ordonner."""
    return (
        FlwLink.all_objects.filter(id=link_id)
        .order_by()
        .values_list("tenant_id", flat=True)
        .first()
    )


__all__ = ["LOOKUP_ON", "LOOKUP_SETTING", "resolve_tenant_for_inbound_call"]
