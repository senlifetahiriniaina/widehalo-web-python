"""S3 (Phase 4, bloc A) — la file de sortie, le reessai espace, le
disjoncteur.

Ce module tient FLX-3 : « Apres N echecs consecutifs sur une liaison, le
disjoncteur s'ouvre, les echanges suivants restent en file sans appel
reseau, et un incident unique est cree — pas un incident par tentative. »

**La file EST la base.** Il n'y a pas de file en memoire, pas de courtier de
messages : un echange en `en_file` attend, un point c'est tout. Le cahier
tranche ce choix explicitement (§12) — le courtier dedie est « ecarte.
Reexamen si la file de sortie depasse durablement le millier d'echanges en
attente ». Django-Q ne sert donc qu'a DECLENCHER une passe de vidange, il ne
porte jamais les echanges eux-memes. La consequence pratique compte : une
passe tuee, un worker redemarre, un deploiement en plein milieu ne perdent
aucun echange, parce qu'il n'y a rien a perdre en dehors de la base.

**Ce que le disjoncteur protege, et de quoi.** Pas le tiers : nous. Un tiers
lent immobilise un worker sans consommer de ressource, et ce depot n'en a
que DEUX (`Q_CLUSTER["workers"] = 2`). Deux passes de vidange bloquees sur
une plateforme fiscale en difficulte suffisent a arreter toutes les taches
de fond de l'ERP — sauvegardes, relances, rapports. C'est exactement le
scenario que §7.6 decrit, et il est atteignable ici aujourd'hui.

**Trois bornes, et pourquoi trois.** Le disjoncteur arrete d'appeler un
tiers qui echoue ; il ne dit rien d'un tiers qui repond, mais lentement. Le
delai maximal par appel borne un appel unique ; il ne dit rien d'une passe
qui en enchaine mille. Le budget de passe borne la passe ; il ne dit rien
d'une rafale envoyee a un tiers qui limite son debit. Chacune couvre ce que
les deux autres laissent passer, et c'est pourquoi le cahier les nomme
toutes les trois (§11).

**Ce que ce module NE fait PAS, et il faut le lire.** Il n'interrompt pas un
appel qui depasse son delai. On ne peut pas avorter un appel bloquant
arbitraire en Python sans le tuer lui-meme, et pretendre le contraire serait
un mensonge de docstring. Le delai maximal est donc un CONTRAT passe a
l'adaptateur — qui le repercute sur son `timeout` reseau, comme les trois
appels sortants deja ecrits dans ce depot le font — et une MESURE faite
apres coup, qui ouvre un incident « anomalie a signaler a l'editeur » quand
l'adaptateur l'a ignore. Le budget de passe, lui, est reellement opposable :
il arrete la boucle entre deux appels.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.services.redaction import redact_secrets
from apps.flows.models import FlwExchange, FlwIncident, FlwLink
from apps.flows.services.exchange import transition_exchange
from apps.flows.services.incidents import record_failure

if TYPE_CHECKING:
    from collections.abc import Callable

    from apps.core.models.tenant import Tenant

    #: Ce que l'executeur attend d'un adaptateur : un echange et le nombre
    #: de secondes qu'il lui reste, un verdict en retour. L'adaptateur ne
    #: CHOISIT pas son delai, il le RECOIT — sans quoi « delai maximal par
    #: appel » serait un reglage que chaque adaptateur pourrait ignorer.
    Sender = Callable[[FlwExchange, float], "CallOutcome"]

#: Etats depuis lesquels la vidange peut partir. `en_file` est l'attente
#: nominale ; `a_reessayer` est l'attente APRES un echec, avec son echeance.
#: Les deux sont draines par la meme passe : separer les deux boucles ferait
#: passer un reessai du et un premier envoi dans un ordre qui depend du code
#: plutot que de l'anciennete.
DRAINABLE_STATES = (FlwExchange.STATE_QUEUED, FlwExchange.STATE_TO_RETRY)


@dataclass(frozen=True)
class CallOutcome:
    """Ce qu'un adaptateur rapporte de son appel.

    `family` est OBLIGATOIRE quand l'appel echoue, et c'est le point :
    §10.3 impose que l'adaptateur traduise l'erreur du tiers dans le jeu
    ferme de six familles. Un echec sans famille serait une erreur brute
    remontee telle quelle — precisement ce que le cahier interdit — et il
    est donc refuse ici plutot que stocke.

    `awaiting_verdict` distingue « le tiers a pris la soumission et
    tranchera plus tard » de « le tiers a accepte ». Les confondre ferait
    d'une soumission fiscale en cours d'instruction une facture validee."""

    ok: bool
    result_code: str = ""
    result_message: str = ""
    family: str = ""
    awaiting_verdict: bool = False

    def __post_init__(self) -> None:
        if not self.ok and self.family not in dict(FlwIncident.FAMILY_CHOICES):
            raise ValueError(
                "Un échec doit porter une des six familles d'erreur du cahier (§10.3) : "
                f"{self.family!r} n'en est pas une."
            )


# --- Le disjoncteur ------------------------------------------------------------


def breaker_allows(link: FlwLink, *, now: dt.datetime | None = None) -> bool:
    """Le disjoncteur laisse-t-il passer un appel sur cette liaison ?

    Ferme : oui. Ouvert : non, jusqu'a la fin de la periode d'essai. Le
    glossaire du cahier definit le disjoncteur comme se refermant « apres
    une periode d'essai » : sans ce retour, un disjoncteur qui s'ouvre une
    nuit couperait la liaison jusqu'a ce qu'un humain la rouvre — une panne
    de plus, pas une protection.

    **Cette fonction ECRIT.** Le passage ouvert -> demi-ouvert est une
    transition, pas une lecture, et la faire ici plutot que dans un
    balayage separe evite une classe entiere de defauts : un disjoncteur
    dont la refermeture dependrait d'une tache planifiee resterait ouvert
    aussi longtemps que cette tache serait en panne, c'est-a-dire
    exactement quand tout le reste l'est aussi."""
    moment = now or timezone.now()
    if link.breaker_state == FlwLink.BREAKER_CLOSED:
        return True
    if link.breaker_state == FlwLink.BREAKER_HALF_OPEN:
        # Un seul appel d'essai a la fois : il vient d'etre autorise et son
        # resultat refermera ou rouvrira le disjoncteur.
        return True
    if link.breaker_opened_at is None:  # pragma: no cover - ouvert implique une date
        return False
    elapsed = (moment - link.breaker_opened_at).total_seconds()
    if elapsed < link.breaker_cooldown_seconds:
        return False
    link.breaker_state = FlwLink.BREAKER_HALF_OPEN
    link.save(update_fields=["breaker_state", "updated_at"])
    return True


def record_call_success(link: FlwLink) -> None:
    """Un appel a reussi : le compteur d'echecs CONSECUTIFS repart de zero.

    C'est la lecture litterale de FLX-3 (« N echecs consecutifs ») et elle
    n'est pas cosmetique : un compteur cumulatif finirait par ouvrir le
    disjoncteur d'une liaison qui fonctionne, apres assez de mois et assez
    d'incidents isoles."""
    if link.consecutive_failures == 0 and link.breaker_state == FlwLink.BREAKER_CLOSED:
        return
    link.consecutive_failures = 0
    link.breaker_state = FlwLink.BREAKER_CLOSED
    link.breaker_opened_at = None
    link.save(
        update_fields=["consecutive_failures", "breaker_state", "breaker_opened_at", "updated_at"]
    )


def record_call_failure(
    link: FlwLink,
    *,
    family: str,
    result_code: str = "",
    result_message: str = "",
    now: dt.datetime | None = None,
) -> FlwIncident:
    """Un appel a echoue : incident, compteur, et disjoncteur s'il faut.

    **L'incident s'ouvre des le PREMIER echec, et le disjoncteur au
    Nieme.** Le cahier admet deux lectures — le dictionnaire parle
    d'« echecs repetes », le critere ne cree l'incident qu'a l'ouverture du
    disjoncteur — et il faut donc trancher. Deux raisons pour celle-ci.
    D'abord, « pas un incident par tentative » ne veut rien dire si
    l'incident nait a la derniere tentative : la phrase suppose un incident
    qui traverse plusieurs tentatives, donc qui existe avant la derniere.
    Ensuite, le produit : avec un seuil de 5 et un espacement croissant, un
    incident cree au seuil arriverait des heures apres le debut d'une
    panne, et le support decouvrirait par le client ce que la console
    aurait pu lui dire tout de suite. Le bruit redoute est traite par
    `occurrence_count` — un incident a 1 et un incident a 200 ne se lisent
    pas pareil — pas par le silence.

    **Un demi-ouvert qui echoue se rouvre immediatement**, sans attendre le
    seuil : l'appel d'essai existe pour poser une question, et sa reponse
    est non.

    **Le compteur s'incremente en base, pas en memoire.** Le meme argument
    que pour `occurrence_count` dans `services.incidents`, et il vaut mot
    pour mot ici : deux vidanges concurrentes qui echouent sur la meme
    liaison liraient toutes deux `consecutive_failures = 3` et ecriraient
    toutes deux `4`. Un echec perdu a chaque collision, et un compteur qui
    sous-estime d'autant plus que la panne est massive — c'est-a-dire au
    moment precis ou il decide d'ouvrir le disjoncteur. Ecrire ce
    raisonnement pour l'incident et laisser le defaut sur le compteur qui
    porte le critere aurait ete incoherent.

    La relecture qui suit l'increment n'est pas une precaution de style :
    c'est la valeur REELLE, collisions comprises, qui doit etre comparee au
    seuil. La comparer a la valeur qu'on croyait avoir ecrite reintroduirait
    exactement la perte qu'on vient d'eviter."""
    moment = now or timezone.now()
    incident = record_failure(
        link,
        family=family,
        result_code=result_code,
        result_message=result_message,
        now=moment,
    )

    was_open = link.breaker_state == FlwLink.BREAKER_OPEN
    FlwLink.objects.filter(pk=link.pk).update(
        consecutive_failures=F("consecutive_failures") + 1, updated_at=moment
    )
    link.refresh_from_db(fields=["consecutive_failures"])

    # Un demi-ouvert qui echoue se rouvre sans consulter le seuil ; sinon,
    # c'est le seuil de la liaison — jamais une constante — qui decide.
    if link.breaker_state == FlwLink.BREAKER_HALF_OPEN or (
        link.consecutive_failures >= link.breaker_threshold
    ):
        link.breaker_state = FlwLink.BREAKER_OPEN
        link.breaker_opened_at = moment
        link.save(update_fields=["breaker_state", "breaker_opened_at", "updated_at"])

    if link.breaker_state == FlwLink.BREAKER_OPEN and not was_open:
        _alert_breaker_opened(link, incident)
    return incident


def _alert_breaker_opened(link: FlwLink, incident: FlwIncident) -> None:
    """« Une alerte sur l'ouverture d'un disjoncteur » (§7.6), adressee au
    destinataire regle sur l'axe A5.

    Sans destinataire configure, rien n'est emis — et c'est volontaire :
    envoyer l'alerte a un role par defaut ferait recevoir a quelqu'un une
    alerte qu'il n'a pas demandee, sur une liaison qu'il ne connait pas.
    L'incident reste ouvert et lisible dans tous les cas ; l'alerte est le
    supplement, pas la trace.

    L'echec de la notification n'echoue JAMAIS la vidange : le disjoncteur
    vient de s'ouvrir parce que quelque chose ne va pas, et ce n'est pas le
    moment de perdre en plus la passe en cours."""
    recipient = link.alert_recipient
    if recipient is None:
        return
    from apps.core.services.notifications import dispatch_notification
    from apps.flows.services.incidents import recovery_action

    try:
        dispatch_notification(
            recipient,
            "flows.breaker_opened",
            {
                "link": link.name,
                "connector": link.connector.code,
                "family": incident.get_family_display(),
                "occurrences": incident.occurrence_count,
                "action": recovery_action(incident.family),
            },
            tenant_id=str(link.tenant_id),
        )
    except Exception:  # noqa: BLE001 - une alerte perdue ne doit pas coûter la passe
        import logging

        logging.getLogger(__name__).exception(
            "Alerte d'ouverture de disjoncteur non délivrée pour la liaison %s", link.id
        )


# --- Le reessai espace ---------------------------------------------------------


def next_attempt_delay_seconds(link: FlwLink, attempt: int) -> int:
    """L'espacement avant la tentative suivante, croissant.

    Croissance geometrique de raison 3 a partir de l'espacement de base
    regle sur la liaison : 5 min, 15 min, 45 min avec le defaut. Le cahier
    demande « un reessai avec espacement croissant » sans fixer la loi ; le
    depot connait deja deux tables figees — `(1, 4, 16)` dans
    `core.events`, `5 min / 30 min / 2 h` dans WhatsApp — et aucune n'est
    reglable. Une loi calculee a partir d'UN reglage client est ce qui rend
    l'axe A5 saisissable : un comptable regle « 5 minutes », pas une suite.

    Le premier reessai porte `attempt = 1` : l'exposant part donc de zero,
    et le premier espacement est exactement celui qui a ete regle. Un
    exposant qui partirait de 1 triplerait le reglage a l'insu de celui qui
    l'a saisi."""
    exponent = max(attempt - 1, 0)
    return int(link.retry_backoff_seconds * (3**exponent))


def due_exchanges(
    tenant: Tenant, *, now: dt.datetime | None = None, limit: int = 200
) -> list[FlwExchange]:
    """Les echanges qu'une passe DOIT considerer, les plus anciens d'abord.

    `en_file` sans echeance et `a_reessayer` dont l'echeance est passee. Un
    `a_reessayer` sans echeance est volontairement EXCLU : c'est la mise en
    attente de l'axe A5, un echange dont les tentatives sont epuisees et qui
    attend une decision humaine. L'inclure reviendrait a reessayer
    indefiniment ce que le client a demande d'arreter.

    L'ordre est l'anciennete de creation, pas l'echeance : un echange qui
    attend depuis ce matin passe avant un reessai programme il y a une
    minute, quel que soit l'etat des deux.

    **Seules les liaisons ACTIVES sont drainees (defaut trouve au sprint
    S6).** Le declencheur evenementiel et le repartiteur planifie
    refusaient deja une liaison en brouillon ou suspendue — chacun avec son
    test — mais la vidange, elle, ne regardait pas. Une liaison suspendue
    en pleine incidence continuait donc a appeler le tiers pour tout ce qui
    etait DEJA en file, ce qui vide « suspendre » de son sens : on suspend
    justement parce que les envois en cours posent probleme. Les echanges
    restent en file, sans appel et sans echec — comme pour un connecteur
    sans adaptateur, et pour la meme raison : l'etat de la liaison peut
    changer, l'echange n'a pas a mourir avec.
    """
    moment = now or timezone.now()
    queryset = FlwExchange.objects.filter(
        tenant=tenant,
        state__in=DRAINABLE_STATES,
        direction=FlwExchange.DIRECTION_OUTBOUND,
        link__state=FlwLink.STATE_ACTIVE,
    ).exclude(state=FlwExchange.STATE_TO_RETRY, next_attempt_at__isnull=True)
    queryset = queryset.exclude(
        state=FlwExchange.STATE_TO_RETRY, next_attempt_at__gt=moment
    ).select_related("link", "link__connector")
    return list(queryset.order_by("created_at")[:limit])


# --- La vidange ----------------------------------------------------------------


def drain_outbound_queue(
    tenant: Tenant,
    *,
    sender: Sender,
    now: dt.datetime | None = None,
    max_pass_seconds: float | None = None,
    max_call_seconds: float | None = None,
    can_send: Any = None,
    clock: Any = time.monotonic,
) -> dict[str, int]:
    """Une passe de vidange, bornee sur les trois axes du cahier.

    Renvoie un decompte — meme forme que `whatsapp.process_outbound_queue`,
    pour qu'une commande periodique s'ecrive pareil des deux cotes.

    `clock` est injectable et repose sur `time.monotonic` : mesurer une
    duree avec l'horloge murale donne des negatifs a chaque changement
    d'heure, et Madagascar n'en a pas, mais un serveur resynchronise par
    NTP si.

    **L'ordre des trois bornes n'est pas indifferent.** Le budget de passe
    est teste AVANT de choisir un echange, le disjoncteur AVANT l'appel, le
    plafond de rafale AVANT les deux : chacune doit ecarter le travail sans
    le commencer, sinon elle ne borne rien."""
    moment = now or timezone.now()
    pass_budget = (
        max_pass_seconds if max_pass_seconds is not None else settings.FLOWS_MAX_PASS_SECONDS
    )
    call_budget = (
        max_call_seconds if max_call_seconds is not None else settings.FLOWS_MAX_CALL_SECONDS
    )
    started = clock()
    counts = {
        "sent": 0,
        "failed": 0,
        "skipped_breaker": 0,
        "skipped_cap": 0,
        "skipped_no_adapter": 0,
        "budget_exhausted": 0,
    }
    calls_by_connector: dict[Any, int] = {}
    links: dict[Any, FlwLink] = {}

    for exchange in due_exchanges(tenant, now=moment):
        if clock() - started >= pass_budget:
            # Le reste attend la passe suivante. Les echanges n'ont pas
            # bouge : c'est le sens meme d'une file persistante.
            counts["budget_exhausted"] += 1
            break

        link = links.setdefault(exchange.link_id, exchange.link)
        connector = link.connector
        if can_send is not None and not can_send(connector.code):
            # Aucun adaptateur livre pour ce connecteur. L'echange RESTE EN
            # FILE, sans appel et sans echec : le marquer en echec ferait
            # d'un deploiement partiel une perte de donnees.
            counts["skipped_no_adapter"] += 1
            continue

        if calls_by_connector.get(connector.id, 0) >= connector.max_in_flight:
            counts["skipped_cap"] += 1
            continue

        if not breaker_allows(link, now=moment):
            # FLX-3, seconde clause : « les echanges suivants restent en
            # file SANS APPEL RESEAU ». Aucune transition, aucun appel —
            # l'echange est exactement ou il etait.
            counts["skipped_breaker"] += 1
            continue

        outcome, elapsed = _call_adapter(sender, exchange, call_budget, clock)
        calls_by_connector[connector.id] = calls_by_connector.get(connector.id, 0) + 1

        if elapsed > call_budget:
            # L'adaptateur a ignore le delai qu'on lui a passe. L'echange,
            # lui, a le sort que le tiers lui a donne — le corriger serait
            # mentir sur ce qui s'est passe. C'est l'EDITEUR qui est en
            # cause, et le cahier a une famille pour exactement ca.
            record_failure(
                link,
                family=FlwIncident.FAMILY_EDITOR,
                result_code="delai_depasse",
                result_message=_(
                    "L'adaptateur %(code)s a rendu la main après %(elapsed).1f s "
                    "pour un délai maximal de %(budget).1f s."
                )
                % {"code": connector.code, "elapsed": elapsed, "budget": call_budget},
                now=moment,
            )

        if outcome.ok:
            _settle_success(exchange, outcome, now=moment)
            record_call_success(link)
            counts["sent"] += 1
        else:
            _settle_failure(exchange, link, outcome, now=moment)
            record_call_failure(
                link,
                family=outcome.family,
                result_code=outcome.result_code,
                result_message=outcome.result_message,
                now=moment,
            )
            counts["failed"] += 1

    return counts


def _call_adapter(
    sender: Sender, exchange: FlwExchange, budget: float, clock: Any
) -> tuple[CallOutcome, float]:
    """Appelle l'adaptateur et MESURE, hors de toute transaction.

    Hors transaction, deliberement : tenir une transaction ouverte pendant
    un appel reseau fait durer un verrou de ligne aussi longtemps que le
    tiers met a repondre — c'est-a-dire indefiniment quand le tiers est
    justement en difficulte.

    Une exception de l'adaptateur devient un echec de famille « anomalie a
    signaler a l'editeur » : un adaptateur qui leve au lieu de rapporter
    n'a pas traduit l'erreur du tiers, ce qui est SON defaut, pas celui du
    tiers. La faire remonter tuerait la passe et tous les echanges qui la
    suivent."""
    before = clock()
    try:
        outcome = sender(exchange, budget)
    except Exception as exc:  # noqa: BLE001 - un adaptateur qui lève ne doit pas tuer la passe
        outcome = CallOutcome(
            ok=False,
            result_code="exception_adaptateur",
            # Rediger PUIS tronquer : l'inverse couperait un motif en deux
            # et le laisserait passer a moitie — une moitie de secret reste
            # un secret pour qui connait l'autre.
            result_message=redact_secrets(str(exc))[:2000],
            family=FlwIncident.FAMILY_EDITOR,
        )
    return outcome, clock() - before


def queue_exchange(exchange: FlwExchange, *, occurrence: str = "") -> FlwExchange:
    """Met un echange en file, en lui posant ses deux clefs au passage.

    **C'est ICI que la clef d'idempotence est calculee, et pas a la
    preparation** (S4). Un echange prepare puis abandonne sans jamais
    partir ne doit pas consommer de clef : la contrainte d'unicite la
    retiendrait pour toujours, et une seconde tentative sur la meme piece
    serait refusee par la base pour un envoi qui n'a jamais eu lieu.

    C'est le point d'entree que les declencheurs de S5 appelleront. Il
    existe des maintenant parce que sans lui, chaque appelant devrait se
    souvenir de poser les clefs — et le premier qui l'oublierait
    transmettrait au tiers un echange sans protection contre le doublon,
    sans que rien ne proteste.

    `occurrence` distingue deux PASSAGES d'une meme planification (S5) —
    sans lui, un releve quotidien sans piece porterait chaque jour la meme
    clef et la contrainte d'unicite tuerait la planification au deuxieme
    jour. Vide pour tout envoi rattache a une piece metier."""
    from apps.flows.services.idempotency import assign_keys

    assign_keys(exchange, occurrence=occurrence)
    return transition_exchange(exchange, to_state=FlwExchange.STATE_QUEUED)


def _requeue_if_retrying(exchange: FlwExchange) -> None:
    """Un reessai du repasse par `en_file` avant d'etre emis.

    Ce n'est pas une formalite : le graphe de S2 n'autorise pas
    `a_reessayer -> emis`, et il a raison. « A reessayer » decrit un
    echange qui ATTEND son echeance ; une fois l'echeance atteinte, il
    reprend sa place dans la file comme n'importe quel autre, et c'est ce
    passage qui rend la file lisible — un journal ou un reessai sauterait
    de l'attente a l'emission ne dirait jamais combien d'echanges sont
    prets a partir a un instant donne.

    Le defaut a ete trouve par le graphe lui-meme, qui a refuse la
    transition, et non par relecture."""
    if exchange.state == FlwExchange.STATE_TO_RETRY:
        transition_exchange(exchange, to_state=FlwExchange.STATE_QUEUED)


def _settle_success(exchange: FlwExchange, outcome: CallOutcome, *, now: dt.datetime) -> None:
    """Un envoi reussi : `emis`, puis le verdict s'il est immediat.

    Deux transitions et non une : `emis` est ce qui incremente `attempt` et
    horodate `sent_at`, et le registre doit garder la trace qu'un envoi a eu
    lieu meme quand le verdict arrive dans la milliseconde suivante."""
    with transaction.atomic():
        _requeue_if_retrying(exchange)
        transition_exchange(
            exchange,
            to_state=FlwExchange.STATE_SENT,
            result_code=outcome.result_code,
            result_message=outcome.result_message,
        )
        if outcome.awaiting_verdict:
            transition_exchange(
                exchange,
                to_state=FlwExchange.STATE_AWAITING_VERDICT,
                next_action_at=now,
            )
        else:
            transition_exchange(exchange, to_state=FlwExchange.STATE_ACCEPTED)


def _settle_failure(
    exchange: FlwExchange, link: FlwLink, outcome: CallOutcome, *, now: dt.datetime
) -> None:
    """Un envoi echoue : `emis`, puis reessai, mise en attente ou abandon.

    On passe quand meme par `emis` : une tentative a bien eu lieu, elle
    compte, et `attempt` est ce sur quoi `max_attempts` se prononce. Sauter
    cette transition ferait qu'un echange en echec permanent n'epuiserait
    jamais ses tentatives.

    Au-dela de `max_attempts`, l'axe A5 offre deux comportements et le
    client choisit : la MISE EN ATTENTE laisse l'echange en `a_reessayer`
    sans echeance — visible, repris par un rejeu supervise (S4), jamais
    repris tout seul — tandis que l'ABANDON TRACE le pousse en `en_echec`,
    qui est un puits. Une soumission fiscale obligatoire doit attendre que
    la plateforme revienne ; une notification de confort n'a plus d'objet
    trois jours plus tard."""
    with transaction.atomic():
        _requeue_if_retrying(exchange)
        transition_exchange(
            exchange,
            to_state=FlwExchange.STATE_SENT,
            result_code=outcome.result_code,
            result_message=outcome.result_message,
        )
        if exchange.attempt >= link.max_attempts:
            if link.on_attempts_exhausted == FlwLink.EXHAUSTED_ABANDON:
                transition_exchange(exchange, to_state=FlwExchange.STATE_FAILED)
            else:
                transition_exchange(
                    exchange, to_state=FlwExchange.STATE_TO_RETRY, next_action_at=None
                )
            return
        delay = next_attempt_delay_seconds(link, exchange.attempt)
        transition_exchange(
            exchange,
            to_state=FlwExchange.STATE_TO_RETRY,
            next_action_at=now + dt.timedelta(seconds=delay),
        )


# --- Supervision (§7.6) --------------------------------------------------------


def process_outbound_queue(tenant: Tenant, *, now: dt.datetime | None = None) -> dict[str, int]:
    """Le point d'entree unique de la commande periodique.

    Resout l'adaptateur de chaque connecteur au moment de l'appel, plutot
    qu'une fois pour toutes : un registre lu au demarrage figerait la liste
    des adaptateurs pour la duree du processus, et un module charge plus
    tard ne serait jamais vu.

    Meme forme de retour que `whatsapp.process_outbound_queue`
    (`dict[str, int]`), pour que les deux commandes periodiques s'ecrivent
    pareil et se lisent pareil dans les journaux d'exploitation."""
    from apps.flows.services.adapter_registry import get_adapter, has_adapter

    def dispatch(exchange: FlwExchange, budget: float) -> CallOutcome:
        adapter = get_adapter(exchange.link.connector.code)
        if adapter is None:  # pragma: no cover - `can_send` l'a deja ecarte
            raise LookupError(f"Aucun adaptateur pour {exchange.link.connector.code!r}.")
        return adapter(exchange, budget)

    return drain_outbound_queue(tenant, sender=dispatch, now=now, can_send=has_adapter)


def outbound_queue_depth(tenant: Tenant, *, now: dt.datetime | None = None) -> dict[str, int]:
    """« Une supervision de la profondeur de la file de sortie » (§7.6).

    Trois nombres, parce qu'un seul mentirait. `waiting` compte ce qui
    partira ; `due` ce qui aurait deja du partir — c'est LUI qui monte quand
    la file se vide moins vite qu'elle ne se remplit ; `held` ce qui
    n'attend plus rien d'automatique et dort jusqu'a une decision humaine.
    Une profondeur totale melangeant les trois resterait elevee apres la
    reparation d'une panne et ne redescendrait jamais."""
    moment = now or timezone.now()
    base = FlwExchange.objects.filter(tenant=tenant, direction=FlwExchange.DIRECTION_OUTBOUND)
    return {
        "waiting": base.filter(state=FlwExchange.STATE_QUEUED).count(),
        "due": len(due_exchanges(tenant, now=moment, limit=10_000)),
        "held": base.filter(state=FlwExchange.STATE_TO_RETRY, next_attempt_at__isnull=True).count(),
    }


def open_breakers(tenant: Tenant) -> list[FlwLink]:
    """Les liaisons dont le disjoncteur n'est pas ferme.

    Demi-ouvert compte : une liaison en periode d'essai n'est pas une
    liaison saine, et la masquer ferait disparaitre de la supervision une
    panne qui dure precisement pendant qu'on teste si elle est finie."""
    return list(
        FlwLink.objects.filter(tenant=tenant)
        .exclude(breaker_state=FlwLink.BREAKER_CLOSED)
        .select_related("connector")
        .order_by("breaker_opened_at")
    )


__all__ = [
    "DRAINABLE_STATES",
    "CallOutcome",
    "breaker_allows",
    "drain_outbound_queue",
    "due_exchanges",
    "next_attempt_delay_seconds",
    "open_breakers",
    "outbound_queue_depth",
    "process_outbound_queue",
    "queue_exchange",
    "record_call_failure",
    "record_call_success",
]
