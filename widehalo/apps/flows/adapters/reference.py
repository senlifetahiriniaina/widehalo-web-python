"""L'adaptateur de REFERENCE — banc d'essai permanent, jamais un bouchon.

**Ce qu'il est.** Une implementation complete du contrat d'adaptateur qui
exerce les huit operations canoniques (§4.1) et les six familles d'erreur
(§10.3) sans jamais toucher au reseau. Il est livre, enregistre et
draine comme les vrais : c'est LUI qui rend opposables les gardes du
sprint S6, parce qu'une garde qu'aucun code reel ne traverse ne garde
rien.

**Ce qu'il n'est pas.** Un bouchon de test qu'on remplacera. Le cahier
prevoit explicitement un « repli activable par parametre » pour les deux
blocs suspendus a une habilitation externe (e-facture §12.3, encaissement
mobile) : cet adaptateur EST ce repli, et il restera apres l'arrivee des
vrais. Le supprimer le jour ou une plateforme reelle repond ferait
disparaitre le seul chemin de bout en bout que l'integration continue
puisse parcourir sans tiers.

**Comment il decide.** Il lit un SCENARIO dans `FlwLink.settings`, la
seule chose que le cahier laisse a l'adaptateur (« le `settings` reste
pour ce qui appartient a l'adaptateur, jamais pour ce que le cahier a
nomme »). Aucun aleatoire : un adaptateur de reference qui echouerait une
fois sur dix rendrait toute la suite de tests intermittente, et une suite
intermittente finit par etre ignoree.

**Les deux operations entrantes ne passent PAS par le contrat `Sender`,
et c'est structurel.** OP6 et OP7 sont entrantes : le tiers appelle, nous
repondons. Un `Sender` — « un echange, un budget, un verdict » — decrit un
appel que NOUS emettons. Les faire passer par lui serait emettre une
notification qu'on est cense recevoir. Elles ont donc leurs deux fonctions
propres ci-dessous, qui ecrivent un echange ENTRANT dans le registre, et
que le point d'entree de webhook du bloc B (API-6, S7-S9) appellera. Ce
sont bien les huit qui sont couvertes, par les deux chemins que le cahier
distingue lui-meme.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils.translation import gettext as _

from apps.flows.models import FlwExchange, FlwIncident
from apps.flows.operations import (
    OP_DROP_FILE,
    OP_INGEST_BATCH,
    OP_INITIATE_PAYMENT,
    OP_PUBLISH_DATASET,
    OP_PUSH_DOCUMENT,
    OP_QUERY_REFERENCE,
    OP_RECEIVE_EVENT,
    OP_SUBMIT_FOR_VERDICT,
)
from apps.flows.services.exchange import prepare_exchange, transition_exchange
from apps.flows.services.queue import CallOutcome

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.flows.models import FlwLink

#: Le code de connecteur auquel cet adaptateur repond. Une constante et
#: non une chaine recopiee : le registre, la declaration d'`apps.py` et
#: les tests la lisent tous les trois, et trois recopies divergent.
CONNECTOR_CODE = "reference"

#: La clef sous laquelle l'adaptateur lit son scenario dans
#: `FlwLink.settings`. Prefixee par le code du connecteur pour qu'un
#: second adaptateur ne vienne jamais ecraser les reglages du premier sur
#: une liaison qui en porterait deux.
SETTINGS_KEY = CONNECTOR_CODE

#: Scenario nominal : le tiers accepte.
SCENARIO_SUCCESS = "succes"
#: Le tiers a PRIS la soumission et tranchera plus tard. Distinct du
#: succes, et c'est tout l'objet de `awaiting_verdict` : confondre les deux
#: ferait d'une facture en cours d'instruction une facture validee.
SCENARIO_AWAITING = "attente_verdict"

#: Un scenario par famille d'erreur du cahier. Le dictionnaire est
#: construit a partir de `FlwIncident.FAMILY_CHOICES` plutot que recopie :
#: une septieme famille ajoutee au modele sans scenario correspondant fait
#: rougir `test_s6_reference_adapter.py`, ce qu'une recopie ne ferait pas.
FAILURE_SCENARIOS = {f"echec_{family}": family for family, _label in FlwIncident.FAMILY_CHOICES}

#: Ce que l'adaptateur rend pour chaque operation sortante, en clair. Les
#: valeurs ne sont pas decoratives : le bloc C (e-facture) et le bloc D
#: (encaissement) les liront comme la forme attendue d'un accuse.
_OUTBOUND_RESULT_CODES = {
    OP_PUSH_DOCUMENT: "accuse_technique",
    OP_PUBLISH_DATASET: "jeu_publie",
    OP_DROP_FILE: "emplacement",
    OP_SUBMIT_FOR_VERDICT: "soumission_prise",
    OP_INITIATE_PAYMENT: "intention_creee",
    OP_QUERY_REFERENCE: "valeur_lue",
}


def _scenario_of(link: FlwLink) -> tuple[str, str]:
    """Le scenario regle sur la liaison, et son message.

    Defaut : le succes. Une liaison de reference sans reglage doit
    fonctionner — l'inverse ferait de l'absence de configuration une
    panne, et le premier a s'en apercevoir serait celui qui essaie le
    produit pour la premiere fois."""
    reglages = (link.settings or {}).get(SETTINGS_KEY) or {}
    return (
        str(reglages.get("scenario") or SCENARIO_SUCCESS),
        str(reglages.get("message") or ""),
    )


def send(exchange: FlwExchange, budget: float) -> CallOutcome:
    """Le contrat `Sender` : un echange, le nombre de secondes qui reste,
    un verdict.

    **`budget` est lu et respecte, pas ignore.** Cet adaptateur ne dort
    jamais, il n'a donc rien a raccourcir ; mais un budget nul ou negatif
    signifie que la passe n'a plus de temps, et rendre un succes dans ce
    cas ferait croire a un envoi qui n'a pas eu lieu. Il rend alors un
    echec de famille « tiers indisponible », qui est exactement ce que le
    vrai adaptateur rendrait sur un delai epuise."""
    if budget <= 0:
        return CallOutcome(
            ok=False,
            result_code="delai_epuise",
            result_message=_("Aucun temps restant sur la passe : rien n'a été émis."),
            family=FlwIncident.FAMILY_UNAVAILABLE,
        )

    operation = exchange.operation
    if operation in (OP_INGEST_BATCH, OP_RECEIVE_EVENT):
        # Une operation ENTRANTE confiee au chemin sortant. C'est un defaut
        # de l'editeur, pas du tiers, et la famille du cahier existe pour
        # exactement ca. `prepare_exchange` le refuse deja a la creation
        # (S6) : ce garde-fou-ci couvre les lignes ecrites AVANT lui.
        return CallOutcome(
            ok=False,
            result_code="operation_entrante_sur_chemin_sortant",
            result_message=_(
                "%(operation)s est entrante : elle s'écrit par `ingest_batch` ou "
                "`receive_event`, jamais par un appel sortant."
            )
            % {"operation": operation},
            family=FlwIncident.FAMILY_EDITOR,
        )

    scenario, message = _scenario_of(exchange.link)

    if scenario in FAILURE_SCENARIOS:
        return CallOutcome(
            ok=False,
            result_code=scenario,
            result_message=message
            or _("Scénario de référence « %(scenario)s ».") % {"scenario": scenario},
            family=FAILURE_SCENARIOS[scenario],
        )

    if scenario == SCENARIO_AWAITING or operation in (
        OP_SUBMIT_FOR_VERDICT,
        OP_INITIATE_PAYMENT,
    ):
        # OP4 et OP5 sont A VERDICT DIFFERE par definition (§4.1 : « avec
        # verdict », « confirmation differee »). Les rendre acceptees
        # d'emblee ferait mentir le banc d'essai sur la seule chose que le
        # bloc C et le bloc D auront a gerer.
        return CallOutcome(
            ok=True,
            result_code=_OUTBOUND_RESULT_CODES.get(operation, "pris_en_compte"),
            result_message=message,
            awaiting_verdict=True,
        )

    return CallOutcome(
        ok=True,
        result_code=_OUTBOUND_RESULT_CODES.get(operation, "accuse_technique"),
        result_message=message,
    )


# --- Les deux operations ENTRANTES --------------------------------------------


def _record_inbound(tenant: Tenant, link: FlwLink, *, operation: str, body: str) -> FlwExchange:
    """Ecrit un echange ENTRANT dans le registre, et le mene a son terme.

    « Un adaptateur qui n'ecrit pas dans le registre n'est pas un
    connecteur, c'est une fuite » (decision structurante n°1). Recevoir
    sans tracer serait exactement cette fuite, et elle est plus facile a
    commettre du cote entrant : rien ne la rend visible, puisque personne
    n'attend de reponse.

    L'echange passe par `en_file` avant `emis` parce que la machine a
    etats de S2 ne connait pas d'autre chemin. C'est deliberé : un etat
    special « recu » aurait double le graphe pour dire la meme chose, et
    l'invariant qui compte — un echange traverse `emis` avant d'etre
    tranche — vaut dans les deux sens."""
    exchange = prepare_exchange(
        tenant,
        link,
        operation=operation,
        direction=FlwExchange.DIRECTION_INBOUND,
        body=body,
    )
    transition_exchange(exchange, to_state=FlwExchange.STATE_QUEUED)
    transition_exchange(exchange, to_state=FlwExchange.STATE_SENT)
    return exchange


def ingest_batch(tenant: Tenant, link: FlwLink, *, body: str) -> FlwExchange:
    """OP6 — ingerer un lot. Le lot est TRACE, jamais traite ici.

    Le traitement metier (detection de doublon, ligne en anomalie isolee,
    rapport de chargement) appartient au module qui possede la piece —
    releve bancaire au bloc E, catalogue au bloc G. L'adaptateur ecrit ce
    qui est arrive et son empreinte ; il ne decide pas de ce que ca
    signifie."""
    return _record_inbound(tenant, link, operation=OP_INGEST_BATCH, body=body)


def receive_event(tenant: Tenant, link: FlwLink, *, body: str) -> FlwExchange:
    """OP7 — recevoir un evenement.

    « Reponse rapide puis traitement differe » (§4.2, mode reactif) : cette
    fonction ne fait QUE la partie rapide. L'authentification de l'appelant
    et la protection contre le rejeu sont au point d'entree de webhook du
    bloc B (API-6), pas ici — un adaptateur qui authentifierait lui-meme
    obligerait chaque adaptateur suivant a le refaire."""
    return _record_inbound(tenant, link, operation=OP_RECEIVE_EVENT, body=body)


__all__ = [
    "CONNECTOR_CODE",
    "FAILURE_SCENARIOS",
    "SCENARIO_AWAITING",
    "SCENARIO_SUCCESS",
    "SETTINGS_KEY",
    "ingest_batch",
    "receive_event",
    "send",
]
