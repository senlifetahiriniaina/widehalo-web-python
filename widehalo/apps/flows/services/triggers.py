"""S5 (Phase 4, bloc A) — déclencheurs sur transition, et l'invariant FLX-2.

**Le critère.** FLX-2 : « Un échec de tiers sur un déclencheur événementiel
n'empêche pas la transition métier : la facture est validée, l'échange est
en file, et l'utilisateur voit l'état réel. »

**Ce qui rend l'invariant STRUCTUREL et non promis.** Trois propriétés se
composent, et aucune n'est nouvelle — elles existaient toutes, séparément :

1. `core.events.publish_event` persiste l'événement dans la transaction du
   fait métier, puis programme sa distribution **sur `on_commit`**. La
   transaction métier est donc déjà validée quand ce module s'exécute.
   Rien de ce qu'il fait ne peut la défaire.
2. Ce module **n'appelle aucun tiers**. Il prépare un échange et le met en
   file ; c'est `process_outbound_queue` (S3) qui émet, avec le disjoncteur
   et l'espacement de réessai. Un déclencheur qui appellerait le tiers
   lui-même contournerait les deux et rendrait la durée d'une validation de
   facture dépendante de la latence de l'administration fiscale.
3. Une exception ici est absorbée **par liaison** : un déclencheur cassé
   n'empêche pas les autres déclencheurs du même événement de partir.

**Les trois sont REDONDANTES, et c'est mesuré, pas supposé.** La
falsification l'a établi : retirer le `try/except` de ce module ne fait pas
rougir le test FLX-2, parce que `dispatch_event` attrape déjà tout ;
rendre la distribution synchrone ne le fait pas rougir non plus, pour la
même raison. Il a fallu retirer les TROIS ensemble pour que la transition
métier soit défaite. La redondance est donc réelle, et elle est une bonne
nouvelle — mais elle a un prix qu'il faut connaître : **aucune mutation
isolée de ces trois couches ne sera signalée par un test**. C'est écrit
dans `test_s5_triggers.py`, au-dessus du test concerné, plutôt que
découvert par le prochain qui en supprimera une.

La troisième couche est la seule qui protège quelque chose que les deux
autres ne protègent pas : un déclencheur cassé n'empêche pas les AUTRES
déclencheurs du même événement de partir. Celle-là, une seule mutation la
fait rougir.

**Le défaut qui rendait tout cela inerte, et qui a été corrigé par ce même
sprint.** `core/workflows.py` publiait `workflow.transitioned` sans
`tenant_id`. Comme tout `FlwTrigger` appartient à une société, un événement
sans société ne peut en désigner aucun : le déclencheur le plus attendu du
hub — celui branché sur une transition métier — n'aurait jamais pu tirer.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from apps.core.services.expr import RestrictedExpressionError, safe_eval
from apps.flows.models import FlwMapping
from apps.flows.services.mapping import apply_mapping

if TYPE_CHECKING:
    from apps.flows.models import FlwExchange, FlwTrigger

logger = logging.getLogger(__name__)


def dispatch_event_to_triggers(event: dict[str, Any]) -> None:
    """Abonné GÉNÉRIQUE du bus d'événements, enregistré une seule fois
    depuis `apps.py::ready()`.

    Exécuté par Django-Q2, hors requête HTTP : aucun `TenantMiddleware`
    pour poser la session Postgres, donc toute lecture passe par
    `activate_tenant` — même contrainte que
    `automation.services.dispatch`, et pour la même raison (`FlwTrigger`
    hérite de `BaseModel`, donc protégé par RLS)."""
    from apps.core.tenant_context import activate_tenant
    from apps.flows.models import FlwLink, FlwTrigger

    tenant_id = event.get("tenant_id")
    if not tenant_id:
        # Tout déclencheur appartient à une société. Un événement sans
        # société ne peut en désigner aucun — et depuis ce sprint, tous les
        # publieurs de production en portent une
        # (`tests/architecture/test_event_tenant_scope.py`).
        return

    event_name = event["type"]
    payload = event["payload"]

    with activate_tenant(tenant_id):
        triggers = list(
            FlwTrigger.objects.filter(
                event_name=event_name, is_active=True, link__state=FlwLink.STATE_ACTIVE
            ).select_related("link")
        )
        for trigger in triggers:
            if not passes_condition(trigger.condition, payload):
                continue
            try:
                fire(trigger, payload)
            except Exception:  # noqa: BLE001 — FLX-2 : un déclencheur cassé n'en bloque aucun autre, et surtout pas la transition métier déjà validée.
                logger.exception(
                    "Déclencheur de flux en échec (liaison %s, événement %s)",
                    trigger.link_id,
                    event_name,
                )


def passes_condition(condition: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Condition déclarative, jamais du code.

    Deny-by-default sur expression invalide : une condition qu'on ne sait
    pas évaluer ne déclenche RIEN. L'inverse ferait partir un échange vers
    un tiers sur la foi d'une expression que personne n'a su lire — même
    décision que `automation.services.dispatch._passes_trigger_filter`,
    reprise et non réinventée."""
    expression = (condition or {}).get("expression")
    if not expression:
        return True
    try:
        return bool(safe_eval(expression, {"payload": payload}))
    except RestrictedExpressionError:
        return False


def _document_of(payload: dict[str, Any]) -> tuple[str, UUID | None]:
    """La pièce métier désignée par l'événement, quand il en désigne une.

    `workflow.transitioned` porte `model` et `object_id` ; d'autres
    événements portent autre chose, ou rien. On ne DEVINE pas : ce qui
    n'est pas reconnu donne un échange sans pièce, ce qui est un état
    parfaitement valide (un relevé global n'a pas de pièce non plus)."""
    document_type = str(payload.get("model") or "")
    brut = payload.get("object_id")
    if not brut:
        return document_type, None
    try:
        return document_type, UUID(str(brut))
    except ValueError:
        # Une clef primaire qui n'est pas un UUID (un modèle à entier)
        # reste utile comme TYPE, pas comme identifiant : la stocker de
        # travers casserait `list_exchanges_for_document`.
        return document_type, None


def body_for(trigger: FlwTrigger, document_type: str, payload: dict[str, Any]) -> str:
    """Le corps que l'échange transportera, en JSON canonique.

    **Ce qui manquait, et il faut le dire.** Jusqu'au sprint S6, `fire`
    appelait `prepare_exchange` SANS corps : chaque échange né d'un
    déclencheur portait une empreinte vide, ce que FLX-1 interdit
    expressément (« ou si un échange est écrit sans empreinte de
    contenu »). Et l'éditeur de correspondance livré au sprint S5 —
    `services/mapping.py`, six transformations, sa garde et ses tests —
    n'avait AUCUN appelant de production. Deux défauts qui se
    réparent l'un l'autre : le corps est la charge de l'événement passée
    dans la correspondance de la liaison.

    **Sans correspondance, la charge brute.** Refuser de partir faute de
    correspondance rendrait le déclencheur inutilisable tant qu'aucune
    n'est saisie, et transformerait une configuration incomplète en
    silence — précisément ce que ce sprint corrige ailleurs. La charge
    brute est un contenu réel, daté et empreint ; l'adaptateur la met à la
    forme du tiers.

    **JSON canonique** (`sort_keys`) : deux charges identiques doivent
    donner la MÊME empreinte, sinon « prouver ce qui est parti » dépend de
    l'ordre dans lequel un dictionnaire s'est trouvé construit."""
    correspondance = (
        FlwMapping.objects.filter(
            link=trigger.link, document_type=document_type, is_active=True
        ).first()
        if document_type
        else None
    )
    contenu = apply_mapping(correspondance.field_map, payload) if correspondance else payload
    return json.dumps(contenu, sort_keys=True, ensure_ascii=False, default=str)


def fire(trigger: FlwTrigger, payload: dict[str, Any]) -> FlwExchange:
    """Fait naître l'échange d'un déclencheur, et le met en file.

    **Ne rend jamais un échange PARTI**, et c'est le cœur de FLX-2 : mettre
    en file est une écriture locale, appeler un tiers ne l'est pas."""
    from apps.flows.services.exchange import prepare_exchange
    from apps.flows.services.queue import queue_exchange

    document_type, document_id = _document_of(payload)
    exchange = prepare_exchange(
        trigger.tenant,
        trigger.link,
        operation=trigger.operation,
        document_type=document_type,
        document_id=document_id,
        body=body_for(trigger, document_type, payload),
    )
    return queue_exchange(exchange)
