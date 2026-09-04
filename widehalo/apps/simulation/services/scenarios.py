"""Cycle de vie d'un `SimScenario` (cahier §13.6) — création/mise à jour
avec garde-fou de tolérance SIM-4, liste/comparaison scopées SIM-9,
archivage, et intégration d'une proposition du copilote IA (SIM-8).

Toute écriture passe par le moteur déterministe `services.engine.compute_
indicators` : le serveur recalcule TOUJOURS, ne fait JAMAIS confiance à un
`computed_indicators` fourni tel quel par l'appelant — un
`client_computed_indicators` optionnel n'est utilisé QUE comme vérification
de parité (SIM-4), jamais comme source de vérité."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.core.services.audit import log_action
from apps.simulation import levers as lever_catalog
from apps.simulation.models import SimBaseline, SimScenario
from apps.simulation.services import scoping
from apps.simulation.services.baseline import deserialize_baseline_data
from apps.simulation.services.engine import compute_indicators

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User

_TOLERANCE = 0.01


def _to_json_safe(value: Any) -> Any:
    """Meme discipline que `apps.core.services.audit._json_safe`, en
    version RECURSIVE (le `computed_indicators` d'un scenario contient des
    `Decimal` imbriques dans des dicts/listes — `treasury.buckets[...]`)."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _to_json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_to_json_safe(val) for val in value]
    return value


def _to_comparable(value: Any) -> Any:
    """Convertit un `Decimal` en `float` pour comparaison tolérante avec un
    payload JSON envoyé par le client (JS ne connaît que des `number`)."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _to_comparable(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_to_comparable(val) for val in value]
    return value


def _find_mismatches(server: Any, client: Any, path: str = "indicators") -> list[str]:
    if isinstance(server, dict):
        if not isinstance(client, dict):
            return [f"{path} : type serveur=objet, client={type(client).__name__}"]
        mismatches: list[str] = []
        for key, server_value in server.items():
            mismatches.extend(_find_mismatches(server_value, client.get(key), f"{path}.{key}"))
        return mismatches
    if isinstance(server, list):
        if not isinstance(client, list) or len(client) != len(server):
            return [f"{path} : longueur de liste differente"]
        mismatches = []
        for index, (server_item, client_item) in enumerate(zip(server, client, strict=True)):
            mismatches.extend(_find_mismatches(server_item, client_item, f"{path}[{index}]"))
        return mismatches
    if server is None or client is None:
        return [] if server == client else [f"{path} : serveur={server!r} client={client!r}"]
    if isinstance(server, int | float):
        try:
            client_num = float(client)
        except (TypeError, ValueError):
            return [f"{path} : valeur client non numerique ({client!r})"]
        if abs(server - client_num) > _TOLERANCE:
            return [f"{path} : serveur={server} client={client}"]
        return []
    return [] if server == client else [f"{path} : serveur={server!r} client={client!r}"]


def _assert_client_matches_server(
    server_indicators: dict[str, Any], client_computed_indicators: dict[str, Any] | None
) -> None:
    """SIM-4 : « toute divergence bloque l'enregistrement et est
    signalée » — comparaison tolérante à 0.01 (arrondis MGA/pourcentage
    déjà appliqués des deux côtés, cf. docstring de `services.engine`)."""
    if client_computed_indicators is None:
        return
    mismatches = _find_mismatches(_to_comparable(server_indicators), client_computed_indicators)
    if mismatches:
        raise ValidationError(
            "Le calcul local divergeait du calcul serveur — enregistrement refusé (SIM-4) : "
            + "; ".join(mismatches[:5])
        )


def create_scenario(
    tenant: Tenant,
    *,
    baseline: SimBaseline,
    name: str,
    levers: dict[str, Any],
    owner: User,
    description: str = "",
    is_shared: bool = False,
    ai_generated: bool = False,
    ai_request_text: str = "",
    client_computed_indicators: dict[str, Any] | None = None,
    user: User | None = None,
) -> SimScenario:
    clamped = lever_catalog.clamp_levers(levers)
    baseline_data = deserialize_baseline_data(baseline)
    server_indicators = compute_indicators(baseline_data, clamped)
    _assert_client_matches_server(server_indicators, client_computed_indicators)

    return SimScenario.objects.create(
        tenant=tenant,
        baseline=baseline,
        baseline_extracted_at=baseline.extracted_at,
        baseline_period_start=baseline.period_start,
        baseline_period_end=baseline.period_end,
        baseline_as_of_date=baseline.as_of_date,
        baseline_regulatory_param_version=baseline.regulatory_param_version,
        name=name,
        description=description,
        owner=owner,
        is_shared=is_shared,
        levers=_to_json_safe(clamped),
        computed_indicators=_to_json_safe(server_indicators),
        ai_generated=ai_generated,
        ai_request_text=ai_request_text,
        created_by=user or owner,
    )


def update_scenario(
    scenario: SimScenario,
    *,
    levers: dict[str, Any],
    user: User,
    name: str | None = None,
    description: str | None = None,
    is_shared: bool | None = None,
    client_computed_indicators: dict[str, Any] | None = None,
) -> SimScenario:
    scoping.assert_can_manage_scenario(scenario, user)
    clamped = lever_catalog.clamp_levers(levers)
    baseline_data = deserialize_baseline_data(scenario.baseline)
    server_indicators = compute_indicators(baseline_data, clamped)
    _assert_client_matches_server(server_indicators, client_computed_indicators)

    scenario.levers = _to_json_safe(clamped)
    scenario.computed_indicators = _to_json_safe(server_indicators)
    update_fields = ["levers", "computed_indicators", "updated_by", "updated_at"]
    if name is not None:
        scenario.name = name
        update_fields.append("name")
    if description is not None:
        scenario.description = description
        update_fields.append("description")
    if is_shared is not None:
        scenario.is_shared = is_shared
        update_fields.append("is_shared")
    scenario.updated_by = user
    scenario.save(update_fields=update_fields)
    return scenario


def archive_scenario(scenario: SimScenario, *, user: User) -> None:
    scoping.assert_can_manage_scenario(scenario, user)
    scenario.soft_delete(by=user)


def list_scenarios(tenant: Tenant, user: User) -> QuerySet[SimScenario]:
    del tenant  # TenantManager deja actif sur `SimScenario.objects` (RLS)
    queryset = SimScenario.objects.filter(is_active=True).select_related("owner", "baseline")
    return scoping.visible_scenarios(queryset, user)


def compare_scenarios(user: User, scenario_ids: list[Any]) -> list[dict[str, Any]]:
    """SIM-6 : « deux à quatre scénarios sont comparables côte à côte ».
    Compare les indicateurs déjà persistés (`computed_indicators`, calculés
    et validés — SIM-4 — au moment de l'enregistrement de chaque scénario),
    jamais un recalcul ad hoc à la volée."""
    ids = [str(sid) for sid in scenario_ids]
    if not (2 <= len(ids) <= 4):
        raise ValidationError(_("Un comparateur nécessite entre 2 et 4 scénarios (SIM-6)."))

    queryset = scoping.visible_scenarios(
        SimScenario.objects.filter(id__in=ids, is_active=True).select_related("owner"), user
    )
    by_id = {str(scenario.id): scenario for scenario in queryset}
    missing = [sid for sid in ids if sid not in by_id]
    if missing:
        raise ValidationError(
            f"Scénario(s) introuvable(s) ou non accessible(s) : {', '.join(missing)}."
        )
    return [
        {
            "id": sid,
            "name": by_id[sid].name,
            "owner_id": str(by_id[sid].owner_id),
            "is_shared": by_id[sid].is_shared,
            "levers": by_id[sid].levers,
            "indicators": by_id[sid].computed_indicators,
        }
        for sid in ids
    ]


def apply_ai_proposed_levers(
    tenant: Tenant,
    *,
    baseline: SimBaseline,
    nl_request: str,
    proposed_levers: dict[str, Any],
    owner: User,
    user: User | None = None,
) -> SimScenario:
    """SIM-8 : enregistre, comme un scénario ordinaire (même chemin
    d'écriture que `create_scenario`, même recalcul serveur autoritaire),
    une proposition de leviers qu'un utilisateur a choisi de CONSERVER
    depuis le copilote — jamais appelé directement par le tool IA
    lui-même, cf. `services.ai_data_query_registration` (qui reste un
    calcul en lecture seule, sans écriture). Journalise explicitement le
    lien demande en langage naturel -> leviers effectivement appliqués, en
    plus de l'audit automatique générique de création (`apps.core.
    audit_signals`, qui capture déjà le diff de champs mais pas le texte
    de la demande dans un événement dédié et facilement filtrable)."""
    clamped = lever_catalog.clamp_levers(proposed_levers)
    scenario = create_scenario(
        tenant,
        baseline=baseline,
        name=f"IA — {nl_request[:80]}",
        levers=clamped,
        owner=owner,
        ai_generated=True,
        ai_request_text=nl_request,
        user=user,
    )
    log_action(
        "simulation.ai_scenario_applied",
        actor=user or owner,
        obj=scenario,
        metadata={"nl_request": nl_request, "levers_applied": _to_json_safe(clamped)},
    )
    return scenario
