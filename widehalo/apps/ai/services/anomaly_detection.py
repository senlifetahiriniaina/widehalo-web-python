"""AI3 — Detection d'anomalies cross-modules (cf. plan section « Module
`ai` (Intelligence artificielle transversale) »). Point d'entree unique :
`run_all_checks(tenant)`.

**Discipline non negociable (cf. docstring de `apps.core.services.
anomaly_registry`) : la detection elle-meme est TOUJOURS deterministe.**
Cette fonction ne fait qu'executer les fonctions DEJA enregistrees par
chaque module metier (`register_anomaly_check`, appele depuis leur propre
`apps.py::ready()`) et persister les `AnomalyCandidate` qu'elles ont deja
detectes — jamais un appel LLM pour DECIDER si quelque chose est une
anomalie. Seule la narrative optionnelle (`AiAnomaly.ai_narrative`) peut
etre generee par IA, et uniquement pour resumer en prose une anomalie deja
detectee, jamais pour la detecter.

**Isolation des echecs** : une exception levee par LA FONCTION d'un module
(bug dans son propre adaptateur) est journalisee et n'interrompt QUE ce
check — les autres modules enregistres continuent d'etre executes
normalement (cf. docstring de tete de fichier `anomaly_registry` : "une
erreur d'un module ne doit jamais bloquer les autres"). De meme, un
`content_type_label` invalide/inconnu sur UN candidat individuel fait
seulement ignorer CE candidat (logue), jamais tout le check.

**Publication d'evenement, HIGH uniquement (choix disclosed)** : seules
les anomalies de severite `SEVERITY_HIGH` publient `"ai.anomaly_detected"`
(cf. `apps.core.events.PUBLISHED_EVENT_TYPES`) — meme raisonnement que
`apps.core.services.risk._maybe_publish_flagged` (seuil "eleve"
uniquement) : un flot d'evenements pour CHAQUE anomalie faible/moyenne
degraderait la valeur de signal du Studio de workflow visuel (`apps.
automation`) sans benefice, une severite faible/moyenne restant
consultable dans l'ecran de liste sans declencher d'automatisation.

**Narrative IA, HIGH uniquement (choix disclosed, bornage du cout)** :
meme raisonnement — un appel LLM par anomalie detectee, quelle que soit sa
severite, ferait consommer le budget de tokens du tenant sur des
anomalies faibles/moyennes dont la description deterministe (deja
lisible) suffit largement. Seule une anomalie `SEVERITY_HIGH` justifie le
cout (potentiel) d'un resume en prose. Meme discipline "fallback-first"
que `apps.ai.services.contextual_assistant.assist` : provider stub (non
configure OU budget epuise) -> `ai_narrative` reste vide, jamais un texte
de substitution invente ici ; `AIProviderError` -> idem, jamais une
exception qui remonterait a l'appelant."""

from __future__ import annotations

import logging

from django.contrib.contenttypes.models import ContentType

from apps.ai.models import AiAnomaly, AiRequest
from apps.ai.services.usage_budget import estimate_tokens, get_budget_gated_provider, record_request
from apps.core.events import publish_event
from apps.core.models.tenant import Tenant
from apps.core.services.ai_assistant import AIProviderError, StubAIProvider
from apps.core.services.anomaly_registry import (
    SEVERITY_HIGH,
    AnomalyCandidate,
    list_anomaly_checks,
)

logger = logging.getLogger(__name__)

_NARRATIVE_MAX_TOKENS = 150


def _resolve_content_type(content_type_label: str) -> ContentType | None:
    """`"app_label.modelname"` -> `ContentType`, ou `None` si le label est
    mal forme ou ne designe aucun modele reel installe — jamais une
    exception qui ferait echouer tout le run pour l'erreur d'UN module."""
    parts = content_type_label.split(".", 1)
    if len(parts) != 2:
        return None
    app_label, model = parts
    try:
        return ContentType.objects.get_by_natural_key(app_label, model)
    except ContentType.DoesNotExist:
        return None


def _generate_narrative(tenant: Tenant, anomaly: AiAnomaly) -> str:
    """Resume en prose optionnel d'une anomalie DEJA detectee — jamais
    utilise pour la detection elle-meme (cf. docstring de module).
    Renvoie une chaine vide sur tout chemin de repli (provider stub,
    `AIProviderError`) plutot que de bloquer la creation de l'anomalie."""
    provider = get_budget_gated_provider(tenant)
    if isinstance(provider, StubAIProvider):
        return ""

    prompt = (
        "Resume en 1 a 2 phrases claires, pour un utilisateur non "
        "technique, l'anomalie suivante deja detectee par un controle "
        f"automatique (verification : {anomaly.check_code}, severite : "
        f"{anomaly.severity}) : {anomaly.description}"
    )
    try:
        completion = provider.complete(prompt, max_tokens=_NARRATIVE_MAX_TOKENS)
    except AIProviderError:
        record_request(
            tenant,
            feature=AiRequest.FEATURE_ANOMALY_NARRATIVE,
            prompt_tokens_estimate=estimate_tokens(prompt),
            completion_tokens_estimate=0,
            provider=provider,
            succeeded=False,
        )
        return ""

    record_request(
        tenant,
        feature=AiRequest.FEATURE_ANOMALY_NARRATIVE,
        prompt_tokens_estimate=estimate_tokens(prompt),
        completion_tokens_estimate=estimate_tokens(completion),
        provider=provider,
        succeeded=True,
    )
    return completion


def _content_type_label(anomaly: AiAnomaly) -> str | None:
    content_type = anomaly.content_type
    if content_type is None:
        return None
    return f"{content_type.app_label}.{content_type.model}"


def _publish_anomaly_detected(tenant: Tenant, anomaly: AiAnomaly) -> None:
    publish_event(
        "ai.anomaly_detected",
        {
            "anomaly_id": str(anomaly.id),
            "check_code": anomaly.check_code,
            "severity": anomaly.severity,
            "content_type_label": _content_type_label(anomaly),
            "object_id": anomaly.object_id,
        },
        tenant_id=str(tenant.id),
    )


def _persist_candidate(
    tenant: Tenant, check_code: str, candidate: AnomalyCandidate
) -> AiAnomaly | None:
    content_type = _resolve_content_type(candidate.content_type_label)
    if content_type is None:
        logger.warning(
            "Anomalie ignoree (check=%s) : content_type_label invalide/inconnu %r",
            check_code,
            candidate.content_type_label,
        )
        return None

    anomaly = AiAnomaly.objects.create(
        tenant=tenant,
        content_type=content_type,
        object_id=candidate.object_id,
        check_code=check_code,
        severity=candidate.severity,
        description=candidate.description,
    )

    if anomaly.severity == SEVERITY_HIGH:
        anomaly.ai_narrative = _generate_narrative(tenant, anomaly)
        if anomaly.ai_narrative:
            anomaly.save(update_fields=["ai_narrative"])
        _publish_anomaly_detected(tenant, anomaly)

    return anomaly


def run_all_checks(tenant: Tenant) -> list[AiAnomaly]:
    """Execute TOUTES les fonctions de verification enregistrees dans
    `core.services.anomaly_registry` pour `tenant`, persiste chaque
    `AnomalyCandidate` renvoye en `AiAnomaly`, et publie
    `"ai.anomaly_detected"` pour chaque anomalie de severite haute. Ne
    leve jamais l'exception d'un check individuel — celle-ci est
    journalisee et le check suivant continue normalement (cf. docstring de
    module)."""
    created: list[AiAnomaly] = []
    for registered in list_anomaly_checks():
        try:
            candidates = registered.function(str(tenant.id))
        except Exception:
            logger.exception(
                "Echec de la verification d'anomalie '%s' (module %s) pour le tenant %s — "
                "ignoree, les autres verifications continuent.",
                registered.code,
                registered.module,
                tenant.id,
            )
            continue

        for candidate in candidates:
            anomaly = _persist_candidate(tenant, registered.code, candidate)
            if anomaly is not None:
                created.append(anomaly)

    return created


__all__ = ["run_all_checks"]
