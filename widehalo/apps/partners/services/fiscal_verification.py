"""T3 (OP8, §4.1) — faire vérifier un identifiant fiscal, sans jamais en
dépendre.

**Le critère, mot pour mot** : « Interroger un référentiel | Sortant,
lecture | Synchrone | Vérifier un identifiant fiscal […] | **Mise en cache
avec durée de validité, dégradation en valeur saisie si le tiers ne répond
pas** » (§4.1, OP8).

**Ce que « dégradation en valeur saisie » veut dire ici, et ce que ça ne
veut pas dire.** Le référentiel ne fait jamais autorité contre le
comptable : il ANNOTE. Une valeur confirmée porte sa date, une valeur
introuvable porte ce constat — et dans les deux cas la valeur saisie reste
celle du tiers. Le produit ne réécrit pas un identifiant sur la foi d'un
service tiers, et ne bloque pas une saisie parce qu'un service est
injoignable.

**Pourquoi le module `partners` appelle le hub, et jamais l'inverse.** La
docstring de `flows.services.public` pose la règle : « le hub ne rappelle
jamais un module métier — il rend un résultat, et l'appelant en fait ce
qu'il veut ». C'est donc ce module qui demande la vérification, et c'est
lui qui va lire le verdict quand il arrive.

**La durée de validité n'est pas décorative.** Une confirmation de 2024 ne
dit rien de 2026 : un tiers radié reste « confirmé » pour toujours si
personne ne fait expirer la réponse. `verification_is_stale` porte cette
péremption, et c'est elle qui fait de `fiscal_verified_at` autre chose
qu'un horodatage d'archive.
"""

from __future__ import annotations

import datetime as dt
import json

from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.flows.services.public import list_exchanges_for_document, request_reference_lookup
from apps.partners.models import Partner

#: Le type de pièce sous lequel le hub range ces échanges — même
#: convention que `workflow.transitioned` (`app_label.NomDeModele`), pour
#: que la console de flux retrouve la fiche du tiers en un clic (CON-1).
DOCUMENT_TYPE = "partners.Partner"

#: Le code du connecteur de référentiel fiscal. Une liaison inactive ou
#: absente n'est pas une erreur : la vérification est simplement sautée.
CONNECTOR_CODE = "referentiel_fiscal"

#: La durée de validité d'une confirmation, en jours. Un an : c'est le pas
#: auquel une entreprise change de situation fiscale (radiation, changement
#: de régime), et c'est aussi le rythme des déclarations annuelles. Valeur
#: assumée et modifiable ; l'important est qu'une confirmation EXPIRE.
VALIDITY_DAYS = 365

#: Les états d'échange qui portent un verdict, et ce qu'ils disent de
#: l'identifiant. Table explicite plutôt que suite de `if` : un état
#: d'échange neuf doit obliger à décider ce qu'il signifie ici, pas glisser
#: dans un `else` qui le traiterait comme une confirmation.
VERDICT_PAR_ETAT: dict[str, str] = {
    "accepte": Partner.VERIFICATION_CONFIRME,
    "rejete": Partner.VERIFICATION_INTROUVABLE,
    "en_echec": Partner.VERIFICATION_INDISPONIBLE,
}


def request_verification(partner: Partner) -> dict[str, object] | None:
    """Demande au hub d'interroger le référentiel pour ce tiers.

    Rend `None` — sans lever — quand aucun référentiel n'est branché, ou
    quand le tiers n'a aucun identifiant à vérifier. Les deux sont des
    états normaux : la majorité des installations n'auront jamais de
    liaison vers un référentiel fiscal, et un prospect saisi en trente
    secondes n'a pas encore de NIF."""
    if not partner.nif and not partner.stat:
        return None
    corps = json.dumps(
        {"nif": partner.nif, "stat": partner.stat, "name": partner.name},
        sort_keys=True,
        ensure_ascii=False,
    )
    return request_reference_lookup(
        partner.tenant,
        connector_code=CONNECTOR_CODE,
        document_type=DOCUMENT_TYPE,
        document_id=partner.id,
        body=corps,
    )


def refresh_verification(partner: Partner) -> Partner:
    """Relit le dernier verdict connu et l'inscrit sur la fiche.

    **Ne rend jamais un tiers « non vérifié » qu'il ne l'était pas déjà** :
    un échange encore en file ou en cours laisse l'état précédent en place.
    Écraser une confirmation datée par un « non vérifié » parce qu'une
    nouvelle demande est partie ferait perdre l'information au moment
    exact où on en a besoin."""
    echanges = list_exchanges_for_document(
        partner.tenant, document_type=DOCUMENT_TYPE, document_id=partner.id, limit=5
    )
    for echange in echanges:
        verdict = VERDICT_PAR_ETAT.get(str(echange.get("state", "")))
        if verdict is None:
            continue
        if _verdict_apporte_du_neuf(partner, verdict, echange.get("settled_at")):
            partner.fiscal_verification_state = verdict
            partner.fiscal_verified_at = timezone.now()
            partner.save(update_fields=["fiscal_verification_state", "fiscal_verified_at"])
        return partner
    return partner


def _verdict_apporte_du_neuf(
    partner: Partner, verdict: str, settled_at: dt.datetime | None
) -> bool:
    """Un verdict RECONDUIT est une information, pas une redite.

    Comparer le seul état laissait un trou dont la conséquence est
    silencieuse : une confirmation périmée reste « confirmée le 3 mars
    2025 » puisque l'état ne change pas, la commande périodique la voit
    donc encore périmée, et elle en redemande la vérification chaque nuit
    — indéfiniment, sans que la fiche ne bouge jamais. C'est la date, pas
    l'état, qui porte l'information ici.

    D'où la troisième condition : un échange tranché APRÈS le dernier
    horodatage connu re-date la fiche, même à verdict identique."""
    if partner.fiscal_verification_state != verdict:
        return True
    if partner.fiscal_verified_at is None:
        return True
    if settled_at is None:
        return False
    return bool(settled_at > partner.fiscal_verified_at)


def verification_is_stale(partner: Partner, *, now: dt.datetime | None = None) -> bool:
    """Une confirmation périmée n'en est plus une.

    Un tiers jamais vérifié n'est pas « périmé » — il est non vérifié, ce
    qui est un autre état et se lit autrement. Confondre les deux ferait
    afficher « à revérifier » à toute une base qui n'a jamais été
    vérifiée."""
    if partner.fiscal_verification_state != Partner.VERIFICATION_CONFIRME:
        return False
    if partner.fiscal_verified_at is None:
        return True
    maintenant = now or timezone.now()
    return (maintenant - partner.fiscal_verified_at).days > VALIDITY_DAYS


#: Les états qui ne portent AUCUN verdict, et qui reviennent donc dans la
#: file. `INDISPONIBLE` en fait partie et ce n'est pas un détail : il dit
#: que le référentiel n'a pas répondu, donc que rien n'a été conclu — le
#: laisser dehors gèlerait définitivement un tiers sur une panne passagère,
#: ce qui est l'inverse de ce que FLX-2 demande.
#:
#: `INTROUVABLE` n'y figure pas : c'est un verdict, et redemander chaque
#: nuit à une administration un tiers qu'elle dit ne pas connaître est du
#: bruit. Ce qui rouvre la question, c'est la correction de l'identifiant
#: lui-même — `Partner.save()` remet alors l'état à « non vérifié », un
#: verdict ne survivant pas à la valeur sur laquelle il portait.
ETATS_SANS_VERDICT: frozenset[str] = frozenset(
    {Partner.VERIFICATION_NON_VERIFIE, Partner.VERIFICATION_INDISPONIBLE}
)


def partners_needing_verification(tenant: Tenant) -> list[Partner]:
    """Les tiers qui portent un identifiant et dont la vérification manque
    ou a expiré — c'est la file de travail de la commande périodique."""
    candidats = Partner.objects.filter(tenant=tenant, is_placeholder=False).exclude(nif="", stat="")
    return [
        partner
        for partner in candidats
        if partner.fiscal_verification_state in ETATS_SANS_VERDICT or verification_is_stale(partner)
    ]
