"""La fenetre de lecture qu'un point d'entree de webhook ouvre pour savoir
QUELLE SOCIETE activer — et rien d'autre.

**Le probleme est de poule et d'oeuf, et il est le meme pour tous les
webhooks.** Un tiers qui appelle `/api/v1/<module>/webhooks/{id}` n'a ni
session, ni jeton applicatif, ni en-tete de societe — lui en faire envoyer
un reviendrait a laisser l'appelant choisir la societe dans laquelle il
ecrit. La ligne designee par l'identifiant EST donc l'unique moyen de
savoir quelle societe activer ; mais toute sous-classe de `BaseModel` est
en `FORCE ROW LEVEL SECURITY`, et sans `app.tenant_id` PostgreSQL ne rend
aucune ligne. `all_objects` n'y change rien : il contourne la RLS
APPLICATIVE de `TenantManager`, jamais celle de la base.

**Pourquoi ce mecanisme vit dans `core` plutot que dans un module.** Il a
d'abord ete construit dans `apps/flows` au lot T5. Le lot T9 a trouve le
meme defaut sur `logistics.carrier_webhook_endpoint` — 404 sur chaque appel
authentique de transporteur — et `logistics` ne declare pas `flows` dans
ses dependances, a juste titre : un module metier n'a pas a dependre du hub
pour ouvrir une transaction. Recopier la fenetre aurait produit deux
mecanismes qui divergent au premier correctif. Elle est donc ici, ou tout
le monde peut la lire, et les deux modules l'appellent.

**Ce que la fenetre ouvre, et ce qu'elle n'ouvre pas.** Chaque table
concernee porte une policy PERMISSIVE supplementaire, `FOR SELECT`
uniquement, conditionnee au reglage ci-dessous. Les ECRITURES restent
gouvernees par la seule policy d'isolation : une ecriture hors societe
reste refusee par PostgreSQL, `FORCE` compris — ce que le critere FLX-7
exige et qu'une derogation `RLS_FORCE_FOR_OWNER = False` aurait detruit.

**Le reglage est remis a zero explicitement, et ce n'est pas une
precaution decorative.** `SET LOCAL` meurt avec la TRANSACTION, pas avec le
bloc `with` : sous `ATOMIC_REQUESTS`, ou dans un test que pytest-django
enveloppe, le bloc atomique ci-dessous n'est qu'un point de sauvegarde et
le reglage survivrait a la sortie — la fenetre resterait ouverte pour tout
le reste de la requete. C'est exactement le piege que
`core/tenant_context.py` documente pour `app.tenant_id`, et il se referme
de la meme facon : a la main, dans un `finally`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from django.db import connection, transaction

#: Le reglage de session qui ouvre la fenetre. Le nom est celui que les
#: policies interrogent ; les deux se lisent ensemble ou pas du tout.
LOOKUP_SETTING = "app.webhook_lookup"
LOOKUP_ON = "on"


@contextmanager
def webhook_lookup_window() -> Iterator[None]:
    """Ouvre la fenetre de lecture anonyme, et la referme quoi qu'il arrive.

    Sur un moteur sans RLS (SQLite), ne fait rien : il n'y a pas de policy
    a contourner, et emettre le reglage echouerait sur une instruction
    inconnue.

    **A n'employer que pour lire l'identifiant de societe.** Tout le reste
    se lit ensuite normalement, sous contexte, par le manager en refus par
    defaut — c'est ce qui borne l'ouverture a la taille du besoin."""
    if connection.vendor != "postgresql":
        yield
        return

    with transaction.atomic():
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"SET LOCAL {LOOKUP_SETTING} = %s", [LOOKUP_ON])
            yield
        finally:
            with connection.cursor() as cursor:
                cursor.execute(f"SET LOCAL {LOOKUP_SETTING} = ''")


__all__ = ["LOOKUP_ON", "LOOKUP_SETTING", "webhook_lookup_window"]
