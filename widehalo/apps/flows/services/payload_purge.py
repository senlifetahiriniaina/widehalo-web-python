"""S6, FLX-5 — la purge de la charge utile.

Le critere : « la purge de la charge utile d'un echange laisse l'echange,
son empreinte, son horodatage et son verdict intacts et interrogeables ».

**Ce qui manquait, dit sans embellir.** `FlwPayload.retain_until` etait
declare depuis le sprint S1 et n'avait ni lecteur ni ecrivain : deux
occurrences dans tout le depot, le modele et sa migration. La colonne
disait qu'une politique de retention existait ; rien ne la faisait vivre.
Le cahier nomme d'ailleurs le risque exactement — « fenetre de purge
depassee » (§, tableau des volumes) — et une purge qui ne s'execute jamais
est precisement une fenetre depassee, tous les jours.

**Quatre pieces, parce qu'une purge non planifiee ne s'execute pas.** Ce
depot a deja paye deux fois la lecon (file WhatsApp, puis file de flux) :
un service, une commande, une DECLARATION dans le registre de
planification, et un index. Il en manque une seule et le mecanisme est un
bouton.

**`retain_until` nul signifie « politique par defaut », jamais « a garder
pour toujours ».** L'arbitrage compte et il n'allait pas de soi. Nul =
jamais purgeable aurait rendu la purge inerte des aujourd'hui — personne
n'ecrit ce champ — et aurait fait d'un oubli de saisie une conservation
perpetuelle de donnees personnelles. C'est l'inverse de ce a quoi sert une
politique de retention. Une date EXPLICITE l'emporte donc toujours sur le
defaut, dans les deux sens : une soumission fiscale se conserve plus
longtemps, un catalogue publie moins.

**La purge n'ecrit AUCUN drapeau sur l'echange, et c'est deliberé.** Le
modele le pose depuis S1 : « l'absence de ligne suffit, et ajouter un
drapeau qui pourrait contredire la realite de la table serait une seconde
source de verite ». Restait la question que ce drapeau devait resoudre :
comment distinguer « charge utile purgee » de « charge utile jamais
ecrite » ? La reponse etait deja dans le schema — `payload_fingerprint`
n'est pose qu'a la creation, et seulement quand un corps existait. Une
empreinte SANS ligne de charge utile est donc une purge ; pas d'empreinte
est un echange qui n'a jamais rien porte. C'est une DERIVATION, pas une
seconde source : elle ne peut pas contredire la table, elle la lit.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.conf import settings
from django.utils import timezone

from apps.flows.models import FlwPayload

logger = logging.getLogger(__name__)


def default_retention_cutoff(today: dt.date | None = None) -> dt.date:
    """La date avant laquelle une charge utile SANS `retain_until` est
    purgeable.

    Lue dans les reglages plutot que figee : la duree de conservation
    relève de la gouvernance du client, pas du code. Le defaut d'un an
    suit « archivage par exercice », que le cahier nomme dans la meme
    ligne que la retention propre de la charge utile."""
    jour = today or timezone.localdate()
    return jour - dt.timedelta(days=settings.FLOWS_PAYLOAD_RETENTION_DAYS)


def purge_expired_payloads(*, today: dt.date | None = None) -> int:
    """Supprime les charges utiles echues. Renvoie le nombre supprime.

    **Boucle par societe, obligatoirement.** La RLS PostgreSQL s'applique
    aussi a `all_objects` — seul le filtrage cote Django y echappe — et une
    requete globale ne verrait donc rien du tout. Meme patron que
    `reporting.purge_expired_jobs` et `core.sandbox.purge_expired_
    sandboxes`, avec la meme isolation par societe : une societe en echec
    ne prive pas les suivantes de leur purge.

    **Une SUPPRESSION franche, jamais une anonymisation.** Vider `body` en
    laissant la ligne ferait survivre `byte_size` et `content_type`, qui
    decrivent un contenu qui n'existe plus, et laisserait la table croitre
    exactement comme le cahier redoute. La preuve, elle, ne bouge pas :
    elle est dans l'echange."""
    from apps.core.models.tenant import Tenant
    from apps.core.tenant_context import activate_tenant

    jour = today or timezone.localdate()
    defaut = default_retention_cutoff(jour)
    total = 0
    for tenant_id in Tenant.objects.values_list("id", flat=True):
        try:
            with activate_tenant(tenant_id):
                echues = FlwPayload.objects.filter(retain_until__lte=jour)
                sans_date = FlwPayload.objects.filter(
                    retain_until__isnull=True, created_at__date__lte=defaut
                )
                total += echues.count() + sans_date.count()
                echues.delete()
                sans_date.delete()
        except Exception:  # noqa: BLE001 — une société en échec ne prive pas les suivantes de leur purge, même décision que `reporting.purge_expired_jobs`.
            logger.exception("Purge des charges utiles en échec pour la société %s", tenant_id)
    return total


__all__ = ["default_retention_cutoff", "purge_expired_payloads"]
