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
defaut, dans les deux sens.

**La politique par defaut est COURTE, et l'exception est fiscale (§9.3).**
Le cahier ne laisse pas le choix de la duree : « la charge utile est
conservee par defaut sur une duree COURTE, parametrable, suffisante au
diagnostic et au rejeu, puis purgee ». Trente jours, donc, et non l'annee
qu'un premier jet avait posee sans y regarder — un an n'est pas une duree
courte, et le confondre avec la duree de conservation de l'ENREGISTREMENT
(dix ans pour ce qui touche a la facturation) est exactement la faute que
le paragraphe designe : « les confondre serait une faute ».

Deux exceptions, et le cahier dit aussi comment les porter : « le document
normalise soumis a un dispositif fiscal et le verdict recu, dont la
conservation releve d'une duree REGLEMENTAIRE et non d'un confort
d'exploitation », « portees par des PARAMETRES VERSIONNES plutot que par du
code ». D'ou la lecture de `core.RegulatoryParameter` plutot qu'un second
reglage Django.

**Les deux parametres ne sont PAS semes ici, et c'est deliberé.** Une duree
reglementaire se seme avec sa reference legale, par le lot qui l'etablit —
le bloc C, qui livre la soumission fiscale. Les semer maintenant avec une
valeur inventee mettrait une duree legale fausse sous le verrou de
validation OECFM, qui refuserait alors la mise en production pour un
chiffre que personne n'a verifie. Le LECTEUR existe et est teste ; c'est la
VALEUR qui attend son lot.

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
from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import timezone

from apps.core.models.regulatory import RegulatoryParameter
from apps.core.services.regulatory import get_parameter
from apps.flows.models import FlwConnector, FlwPayload

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant

logger = logging.getLogger(__name__)


#: Le parametre versionne qui porte la duree ORDINAIRE, en jours.
PARAMETRE_RETENTION = "flux.retention_charge_utile"

#: Celui qui porte la duree REGLEMENTAIRE des echanges fiscaux — le
#: document soumis et le verdict recu (§9.3). Distinct, parce qu'une duree
#: legale ne se regle pas comme un confort d'exploitation.
PARAMETRE_RETENTION_FISCALE = "flux.retention_charge_utile_fiscale"


def retention_days(*, fiscal: bool, tenant: Tenant | None = None, today: dt.date) -> int:
    """La duree de conservation applicable, en jours.

    Le parametre versionne l'emporte quand il existe ; sinon le reglage
    Django. L'ordre n'est pas indifferent : une duree reglementaire doit
    pouvoir changer par une ligne datee en base, avec sa reference legale
    et sa validation, jamais par un deploiement.

    Un parametre absent n'est PAS une erreur : le bloc C livrera la valeur
    fiscale avec sa reference. Tant qu'elle manque, la duree ordinaire
    s'applique — c'est le repli le plus sur qu'on puisse choisir sans
    inventer une duree legale."""
    code = PARAMETRE_RETENTION_FISCALE if fiscal else PARAMETRE_RETENTION
    try:
        return int(get_parameter(code, today, tenant))
    except (RegulatoryParameter.DoesNotExist, TypeError, ValueError):
        return int(settings.FLOWS_PAYLOAD_RETENTION_DAYS)


def default_retention_cutoff(
    today: dt.date | None = None, *, fiscal: bool = False, tenant: Tenant | None = None
) -> dt.date:
    """La date avant laquelle une charge utile SANS `retain_until` est
    purgeable."""
    jour = today or timezone.localdate()
    return jour - dt.timedelta(days=retention_days(fiscal=fiscal, tenant=tenant, today=jour))


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
    total = 0
    for tenant in Tenant.objects.all():
        try:
            with activate_tenant(tenant.id):
                ordinaire = default_retention_cutoff(jour, tenant=tenant)
                fiscale = default_retention_cutoff(jour, fiscal=True, tenant=tenant)
                echues = FlwPayload.objects.filter(retain_until__lte=jour)
                # Les deux politiques par defaut sont separees par la
                # FAMILLE du connecteur, et non par l'operation : §9.3 nomme
                # « le document normalise soumis a un dispositif fiscal ET
                # le verdict recu », qui sont deux operations differentes —
                # une sortante, une entrante — mais toujours la meme
                # famille de connecteur.
                sans_date = FlwPayload.objects.filter(retain_until__isnull=True)
                fiscaux = sans_date.filter(
                    exchange__link__connector__family=FlwConnector.FAMILY_FISCAL,
                    created_at__date__lte=fiscale,
                )
                autres = sans_date.exclude(
                    exchange__link__connector__family=FlwConnector.FAMILY_FISCAL
                ).filter(created_at__date__lte=ordinaire)
                total += echues.count() + fiscaux.count() + autres.count()
                echues.delete()
                fiscaux.delete()
                autres.delete()
        except Exception:  # noqa: BLE001 — une société en échec ne prive pas les suivantes de leur purge, même décision que `reporting.purge_expired_jobs`.
            logger.exception("Purge des charges utiles en échec pour la société %s", tenant.id)
    return total


__all__ = [
    "PARAMETRE_RETENTION",
    "PARAMETRE_RETENTION_FISCALE",
    "default_retention_cutoff",
    "purge_expired_payloads",
    "retention_days",
]
