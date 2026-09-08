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

**T0 — le filtre cesse d'être une expression libre (axe A1).** Le cahier
est catégorique : « Portée — quels objets partent : filtres sur des champs
déclarés du modèle, **jamais une expression libre**. Un filtre non déclaré
est refusé à l'enregistrement. » Jusqu'à T0, `condition` portait une
chaîne évaluée par `safe_eval` sur la charge de l'événement, et rien ne la
validait à l'enregistrement — ni sa syntaxe, ni les champs qu'elle nommait.
Elle porte désormais des `filters` déclaratifs, dont chaque champ doit
être un champ DÉCLARÉ FILTRABLE de la pièce source
(`apps.core.services.outbound_schemas`), et c'est `save_trigger` qui refuse.

Deux conséquences assumées. D'abord le filtre s'évalue sur la PROJECTION
de la pièce, pas sur la charge de l'événement : « champs déclarés du
modèle » désigne le modèle, et `workflow.transitioned` n'en porte que cinq
clefs d'enveloppe. Ensuite, une condition portant l'ancienne clef
`expression` ne déclenche plus RIEN — deny-by-default, dans le sens qui ne
laisse rien sortir, plutôt qu'une conversion automatique qui élargirait la
portée d'un déclencheur sans que personne ne l'ait décidé.

**Le défaut qui rendait tout cela inerte, et qui a été corrigé par ce même
sprint.** `core/workflows.py` publiait `workflow.transitioned` sans
`tenant_id`. Comme tout `FlwTrigger` appartient à une société, un événement
sans société ne peut en désigner aucun : le déclencheur le plus attendu du
hub — celui branché sur une transition métier — n'aurait jamais pu tirer.
"""

from __future__ import annotations

import json
import logging
import operator
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.core.services.outbound_schemas import get_outbound_document, project_document
from apps.flows.models import FlwMapping
from apps.flows.services.mapping import apply_mapping, read_source

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.flows.models import FlwExchange, FlwLink, FlwTrigger

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
        if not triggers:
            return
        # La projection est celle de la PIÈCE que l'événement désigne, et
        # elle est calculée UNE fois pour tous les déclencheurs de cet
        # événement : dix déclencheurs sur la même facture ne doivent pas
        # relire la facture dix fois.
        document_type, document_id = _document_of(payload)
        document = (
            project_document(document_type, document_id) if document_type and document_id else None
        )
        for trigger in triggers:
            if trigger.document_type and trigger.document_type != document_type:
                # Le déclencheur a déclaré filtrer une pièce que cet
                # événement ne porte pas. Ne rien faire plutôt que filtrer
                # à vide : sans quoi une erreur de configuration ferait
                # partir TOUTES les pièces au lieu d'aucune.
                continue
            if not passes_condition(trigger.condition, document):
                continue
            try:
                fire(trigger, payload, document=document)
            except Exception:  # noqa: BLE001 — FLX-2 : un déclencheur cassé n'en bloque aucun autre, et surtout pas la transition métier déjà validée.
                logger.exception(
                    "Déclencheur de flux en échec (liaison %s, événement %s)",
                    trigger.link_id,
                    event_name,
                )


#: Le jeu FERMÉ d'opérateurs de filtre (axe A1). Même discipline que les
#: six transformations de S5 et les huit opérations de S6, pour la même
#: raison : une énumération qu'on peut allonger sans que rien ne proteste
#: redevient du texte libre en deux sprints. La garde est
#: `tests/architecture/test_outbound_schema_vocabularies_are_closed.py`.
FILTER_EQ = "eq"
FILTER_NE = "ne"
FILTER_IN = "in"
FILTER_NOT_IN = "not_in"
FILTER_GT = "gt"
FILTER_GTE = "gte"
FILTER_LT = "lt"
FILTER_LTE = "lte"


def _cmp(gauche: Any, droite: Any, comparaison: Callable[[Any, Any], bool]) -> bool:
    """Une comparaison d'ordre sur des types incomparables est FAUSSE, pas
    une exception.

    Comparer une date à une chaîne lève `TypeError` en Python. Laisser
    remonter ferait échouer le déclencheur entier — donc, par l'absorption
    de FLX-2, le rendrait silencieusement inerte. Rendre `False` est le
    même deny-by-default que partout ailleurs ici : le filtre ne retient
    pas la pièce, et rien ne part."""
    try:
        return bool(comparaison(gauche, droite))
    except TypeError:
        return False


FILTER_OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    FILTER_EQ: lambda valeur, attendu: valeur == attendu,
    FILTER_NE: lambda valeur, attendu: valeur != attendu,
    FILTER_IN: lambda valeur, attendu: isinstance(attendu, list) and valeur in attendu,
    FILTER_NOT_IN: lambda valeur, attendu: isinstance(attendu, list) and valeur not in attendu,
    FILTER_GT: lambda valeur, attendu: _cmp(valeur, attendu, operator.gt),
    FILTER_GTE: lambda valeur, attendu: _cmp(valeur, attendu, operator.ge),
    FILTER_LT: lambda valeur, attendu: _cmp(valeur, attendu, operator.lt),
    FILTER_LTE: lambda valeur, attendu: _cmp(valeur, attendu, operator.le),
}

KNOWN_FILTER_OPERATORS: frozenset[str] = frozenset(FILTER_OPERATORS)


def declared_filters(condition: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Les filtres d'une condition, ou `None` si la condition est illisible.

    `None` et « aucun filtre » ne sont pas la même chose, et les confondre
    ferait exactement le mauvais choix : une condition illisible doit
    RETENIR la pièce, une condition vide doit la laisser passer."""
    if not condition:
        return []
    inconnues = set(condition) - {"filters"}
    if inconnues:
        # Notamment l'ancienne clef `expression` : cf. la section T0 de la
        # docstring de module. Une condition qu'on ne sait plus lire ne
        # déclenche rien.
        return None
    filtres = condition.get("filters")
    if not isinstance(filtres, list) or not all(isinstance(f, dict) for f in filtres):
        return None
    return list(filtres)


def passes_condition(condition: dict[str, Any], document: dict[str, Any] | None) -> bool:
    """Le filtre déclaratif de l'axe A1, évalué sur la PROJECTION.

    Deny-by-default sur tout ce qui ne se lit pas : une condition qu'on ne
    sait pas évaluer ne déclenche RIEN. L'inverse ferait partir un échange
    vers un tiers sur la foi d'un filtre que personne n'a su lire — même
    décision que `automation.services.dispatch._passes_trigger_filter`,
    reprise et non réinventée.

    Un filtre sur une pièce absente (`document is None`) est refusé pour la
    même raison : on ne sait pas si la pièce l'aurait satisfait."""
    filtres = declared_filters(condition)
    if filtres is None:
        return False
    if not filtres:
        return True
    if document is None:
        return False
    for filtre in filtres:
        operateur = FILTER_OPERATORS.get(str(filtre.get("op", "")))
        chemin = str(filtre.get("field", ""))
        if operateur is None or not chemin:
            return False
        if not operateur(read_source(document, chemin), filtre.get("value")):
            return False
    return True


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


def body_for(trigger: FlwTrigger, document_type: str, source: dict[str, Any]) -> str:
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

    **Sans correspondance, la source telle quelle.** Refuser de partir faute
    de correspondance rendrait le déclencheur inutilisable tant qu'aucune
    n'est saisie, et transformerait une configuration incomplète en
    silence — précisément ce que le sprint S6 corrige ailleurs. La source
    est un contenu réel, daté et empreint ; l'adaptateur la met à la forme
    du tiers.

    **Et `source` est la PROJECTION de la pièce quand elle en a une** (T0) :
    la charge de `workflow.transitioned` ne porte que cinq clefs
    d'enveloppe, si bien qu'avant T0 une correspondance désignant
    `partner_id` lisait `None` et n'émettait rien. La projection est
    élaguée aux seuls champs déclarés émis — la marge et le coût de revient
    n'y sont donc pas, quelle que soit la correspondance saisie.

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
    contenu = apply_mapping(correspondance.field_map, source) if correspondance else source
    return json.dumps(contenu, sort_keys=True, ensure_ascii=False, default=str)


def fire(
    trigger: FlwTrigger, payload: dict[str, Any], *, document: dict[str, Any] | None = None
) -> FlwExchange:
    """Fait naître l'échange d'un déclencheur, et le met en file.

    **Ne rend jamais un échange PARTI**, et c'est le cœur de FLX-2 : mettre
    en file est une écriture locale, appeler un tiers ne l'est pas.

    `document` est la projection déjà calculée par le répartiteur — elle est
    passée plutôt que recalculée pour que dix déclencheurs branchés sur la
    même facture ne la relisent pas dix fois. Un appelant qui ne l'a pas
    (un rejeu, un test) la laisse à `None` et elle est calculée ici."""
    from apps.flows.services.exchange import prepare_exchange
    from apps.flows.services.queue import queue_exchange

    document_type, document_id = _document_of(payload)
    if document is None and document_type and document_id:
        document = project_document(document_type, document_id)
    exchange = prepare_exchange(
        trigger.tenant,
        trigger.link,
        operation=trigger.operation,
        document_type=document_type,
        document_id=document_id,
        body=body_for(trigger, document_type, document if document is not None else payload),
    )
    return queue_exchange(exchange)


def save_trigger(
    tenant: Tenant,
    link: FlwLink,
    *,
    event_name: str,
    operation: str,
    document_type: str = "",
    filters: list[dict[str, Any]] | None = None,
    is_active: bool = True,
) -> FlwTrigger:
    """LE point d'entrée de l'axe A1 : enregistre un déclencheur, ou refuse
    en nommant le champ.

    « Un filtre non déclaré est refusé **à l'enregistrement** » — comme
    FLX-6 pour les correspondances, et pour la même raison : un filtre
    accepté en base et découvert faux au premier événement ne se découvre
    qu'en production, sur la pièce d'un client, longtemps après que
    quelqu'un l'a saisi.

    Cinq refus :

    1. l'événement n'est pas un événement publié — un déclencheur branché
       sur un nom qui n'existe pas ne tirera jamais, et rien ne le dirait ;
    2. la pièce déclarée n'est pas liable — son module n'a pas dit ce
       qu'elle a le droit de laisser sortir ;
    3. un filtre sans pièce déclarée — il n'y aurait rien contre quoi
       vérifier les champs, donc pas de « champ déclaré » du tout ;
    4. un opérateur hors du jeu fermé ;
    5. un champ qui n'est pas déclaré FILTRABLE sur cette pièce."""
    from apps.core.events import PUBLISHED_EVENT_TYPES
    from apps.flows.models import FlwTrigger
    from apps.flows.operations import validate_operation

    validate_operation(operation)
    if event_name not in PUBLISHED_EVENT_TYPES:
        raise ValidationError(
            _(
                "L'événement « %(nom)s » n'est publié par aucun module. Un "
                "déclencheur branché sur un nom qui n'existe pas ne tire jamais, "
                "et rien ne le signale."
            )
            % {"nom": event_name}
        )

    filtres = list(filters or [])
    document = get_outbound_document(document_type) if document_type else None
    if document_type and document is None:
        raise ValidationError(
            _(
                "La pièce « %(code)s » n'est pas déclarée liable par son module : "
                "aucun filtre ne peut porter sur ses champs tant que ce module "
                "n'a pas dit lesquels peuvent sortir."
            )
            % {"code": document_type}
        )
    if filtres and document is None:
        raise ValidationError(
            _(
                "Un filtre suppose une pièce source déclarée : sans elle il n'y "
                "a aucun « champ déclaré » contre quoi le vérifier, et l'axe A1 "
                "redeviendrait une expression libre."
            )
        )

    if document is not None:
        filtrables = set(document.filterable_paths)
        for filtre in filtres:
            operateur = str(filtre.get("op", ""))
            if operateur not in KNOWN_FILTER_OPERATORS:
                raise ValidationError(
                    _("Opérateur de filtre « %(op)s » hors du jeu fermé : %(jeu)s.")
                    % {"op": operateur, "jeu": ", ".join(sorted(KNOWN_FILTER_OPERATORS))}
                )
            chemin = str(filtre.get("field", ""))
            if chemin not in filtrables:
                raise ValidationError(
                    _(
                        "« %(chemin)s » n'est pas un champ filtrable déclaré de "
                        "« %(code)s ». Champs filtrables : %(liste)s."
                    )
                    % {
                        "chemin": chemin,
                        "code": document_type,
                        "liste": ", ".join(sorted(filtrables)) or _("aucun"),
                    }
                )

    trigger, _created = FlwTrigger.objects.update_or_create(
        tenant=tenant,
        link=link,
        event_name=event_name,
        operation=operation,
        defaults={
            "document_type": document_type,
            "condition": {"filters": filtres} if filtres else {},
            "is_active": is_active,
        },
    )
    return trigger
