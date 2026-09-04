"""AI4 — Recherche en langage naturel (cf. plan section « Module `ai`
(Intelligence artificielle transversale) »). Point d'entree unique :
`search(query, tenant=..., user=..., locale=...)`.

**Decision structurante, deliberee et deja approuvee (ne pas remettre en
cause)** : l'ancienne specification Laravel decrivait un `NlToSqlService`
generant du SQL parametre a partir d'une question en langage naturel. Ce
depot a explicitement REFUSE de reproduire cette approche — executer du
SQL genere par un LLM cote serveur entre en conflit direct avec la
discipline de securite stricte de ce depot (RBAC/RLS applique partout,
aucune requete construite dynamiquement puis executee a partir d'une
entree non fiable/LLM, nulle part dans le code). A la place, cette
fonction route TOUJOURS a travers le moteur de recherche globale DEJA
SUR, DEJA tenant-scope et RBAC-filtre par resultat construit en Lot 1
etape 11 (`apps.core.services.search.global_search`) — jamais de SQL brut
(`.raw()`/`.extra()`/`cursor.execute()`), jamais de requete construite a
partir d'une valeur extraite par le LLM.

**Extraction de filtres structures, optionnelle, en surcouche** : SI un
fournisseur IA reel est disponible (`get_budget_gated_provider(tenant)` ne
renvoie pas `StubAIProvider`) ET le budget du tenant le permet, cette
fonction tente d'extraire un sous-ensemble de filtres structures
(`module`, `date_from`, `date_to`, `amount_threshold`) a partir de la
question. **Chaque champ extrait est valide contre une liste blanche
explicite/un type strict avant tout usage** (`module` doit appartenir a
`_ALLOWED_MODULES`, `date_from`/`date_to` doivent parser avec
`date.fromisoformat`, `amount_threshold` doit parser comme `Decimal`) — un
champ qui echoue sa validation est SILENCIEUSEMENT ecarte (logue en debug),
jamais propage. Si l'extraction elle-meme echoue completement (JSON
illisible, `AIProviderError`, provider stub, budget epuise), la fonction
degrade vers la recherche brute SANS lever d'exception cote appelant —
meme discipline "fallback-first" que `contextual_assistant.assist` et
`anomaly_detection.run_all_checks`.

**Application vs. simple exposition des filtres (MVP disclosed)** : seul
`module`, une fois valide, est REELEMENT applique — en filtrant en Python
la liste de resultats DEJA recuperee et DEJA securisee par
`global_search()` (jamais une seconde requete construite a partir de la
valeur extraite). `date_from`/`date_to`/`amount_threshold` sont valides et
renvoyes tels quels dans `extracted_filters` pour transparence/debug, mais
NE SONT PAS ENCORE cables a un narrowing reel des resultats dans ce MVP —
`SearchDocument`/`SearchResult` (cf. `apps.core.services.search`) ne
portent aujourd'hui aucune date ni aucun montant structure sur lesquels
filtrer sans reconstruire une requete par module metier, hors perimetre de
cette etape. Documente ici plutot que suppose."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, TypedDict

from django.contrib.contenttypes.models import ContentType

from apps.ai.models import AiRequest
from apps.ai.services.usage_budget import estimate_tokens, get_budget_gated_provider, record_request
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.ai_assistant import AIProviderError, StubAIProvider
from apps.core.services.search import global_search

logger = logging.getLogger(__name__)

# Liste blanche des modules metier de ce depot pouvant etre proposes comme
# filtre `module` — jamais une valeur renvoyee par le LLM acceptee telle
# quelle. Tenue a jour manuellement (meme raisonnement que toute liste
# blanche de ce chantier) : `core`/`ai`/`automation`/`chat` en sont
# volontairement exclus, ce ne sont pas des modules "metier" au sens ou
# une question en langage naturel ("factures", "commandes"...) les
# designerait. `payroll` egalement exclu DELIBEREMENT (Bloc E, E2/decision
# D6, cf. docs/planning/2026-09-cahier-des-charges-v3-phase3-plan.md §2) :
# meme si le narrowing par `module` ne fait que filtrer en Python des
# resultats DEJA RBAC-filtres par `global_search()` (jamais une requete
# additionnelle), retirer `payroll` de cette liste blanche est l'option la
# plus simple et la plus sure pour ne jamais laisser le LLM cibler
# explicitement des donnees de paie (PII) via cette extraction de filtres
# — plutot qu'une garde CI additionnelle plus complexe a maintenir.
_ALLOWED_MODULES: frozenset[str] = frozenset(
    {
        "accounting",
        "crm",
        "mrp",
        "patronage",
        "sales",
        "purchase",
        "logistics",
        "stocks",
        "presence",
        "reporting",
        "strategy",
        "financing",
        "feasibility",
        "projects",
        "catalog",
        "partners",
    }
)

_EXTRACTION_MAX_TOKENS = 200


class ExtractedFilters(TypedDict, total=False):
    module: str
    date_from: str
    date_to: str
    amount_threshold: str


class NlSearchResponse(TypedDict):
    query: str
    results: list[dict[str, str]]
    extracted_filters: ExtractedFilters | None
    is_ai_enhanced: bool


def _build_extraction_prompt(query: str) -> str:
    allowed = ", ".join(sorted(_ALLOWED_MODULES))
    return (
        "Analyse la question suivante d'un utilisateur d'un ERP et extrait, "
        "si presents, les filtres structures qu'elle exprime. Reponds "
        "UNIQUEMENT avec un objet JSON strict, sans texte autour, avec au "
        'plus ces cles optionnelles : "module" (une valeur EXACTE parmi : '
        f'{allowed} — omets la cle si aucune ne correspond), "date_from" '
        '(date ISO "AAAA-MM-JJ"), "date_to" (date ISO "AAAA-MM-JJ"), '
        '"amount_threshold" (nombre, sans devise ni separateur de '
        f"milliers). Question : {query!r}"
    )


def _parse_llm_json(completion: str) -> dict[str, Any] | None:
    """Analyse defensive de la reponse du LLM — jamais d'exception
    propagee : une reponse qui n'est pas un objet JSON valide degrade
    simplement vers "aucun filtre extrait", pas vers une erreur."""
    try:
        parsed = json.loads(completion.strip())
    except (json.JSONDecodeError, ValueError):
        logger.debug("Extraction de filtres NL : reponse LLM non-JSON, ignoree.")
        return None
    if not isinstance(parsed, dict):
        logger.debug("Extraction de filtres NL : reponse JSON n'est pas un objet, ignoree.")
        return None
    return parsed


def _validate_module(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    if candidate not in _ALLOWED_MODULES:
        logger.debug("Extraction de filtres NL : module hors liste blanche %r, ignore.", value)
        return None
    return candidate


def _validate_iso_date(value: Any, *, field_name: str) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed_date = date.fromisoformat(value.strip())
    except ValueError:
        logger.debug("Extraction de filtres NL : %s invalide %r, ignore.", field_name, value)
        return None
    return parsed_date.isoformat()


def _validate_amount_threshold(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (str, int, float)):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        logger.debug("Extraction de filtres NL : amount_threshold invalide %r, ignore.", value)
        return None
    return str(amount)


def _extract_filters(parsed: dict[str, Any]) -> ExtractedFilters:
    """Valide CHAQUE champ individuellement contre sa liste blanche/son
    type strict — un champ qui echoue est ecarte silencieusement, jamais
    propage, jamais l'echec d'un champ ne fait echouer les autres."""
    filters: ExtractedFilters = {}

    module = _validate_module(parsed.get("module"))
    if module is not None:
        filters["module"] = module

    date_from = _validate_iso_date(parsed.get("date_from"), field_name="date_from")
    if date_from is not None:
        filters["date_from"] = date_from

    date_to = _validate_iso_date(parsed.get("date_to"), field_name="date_to")
    if date_to is not None:
        filters["date_to"] = date_to

    amount_threshold = _validate_amount_threshold(parsed.get("amount_threshold"))
    if amount_threshold is not None:
        filters["amount_threshold"] = amount_threshold

    return filters


def _try_extract_filters(query: str, *, tenant: Tenant, user: User) -> ExtractedFilters | None:
    """Tente une extraction IA de filtres structures — renvoie `None` sur
    TOUT chemin de repli (provider stub/budget epuise, `AIProviderError`,
    reponse non parsable) plutot que de bloquer la recherche brute qui a
    deja ete lancee en parallele par l'appelant."""
    provider = get_budget_gated_provider(tenant)
    if isinstance(provider, StubAIProvider):
        return None

    prompt = _build_extraction_prompt(query)
    try:
        completion = provider.complete(prompt, max_tokens=_EXTRACTION_MAX_TOKENS)
    except AIProviderError:
        record_request(
            tenant,
            feature=AiRequest.FEATURE_SEARCH,
            prompt_tokens_estimate=estimate_tokens(prompt),
            completion_tokens_estimate=0,
            provider=provider,
            succeeded=False,
            created_by=user,
        )
        return None

    record_request(
        tenant,
        feature=AiRequest.FEATURE_SEARCH,
        prompt_tokens_estimate=estimate_tokens(prompt),
        completion_tokens_estimate=estimate_tokens(completion),
        provider=provider,
        succeeded=True,
        created_by=user,
    )

    parsed = _parse_llm_json(completion)
    if parsed is None:
        return None
    return _extract_filters(parsed)


def search(query: str, *, tenant: Tenant, user: User, locale: str = "fr") -> NlSearchResponse:
    """Point d'entree unique AI4. Route TOUJOURS la question brute a
    travers le moteur de recherche globale deja sur (`global_search`),
    puis tente EN SURCOUCHE une extraction de filtres structures — jamais
    l'inverse. `locale` n'influence aucune traduction ici (aucun texte
    genere par ce chemin n'est expose a l'utilisateur autrement que via
    les resultats de recherche eux-memes) ; conserve pour rester coherent
    avec la signature des autres points d'entree IA de ce chantier
    (`contextual_assistant.assist`)."""
    del locale  # cf. docstring : reserve pour coherence de signature, non utilise ici.

    raw_results = global_search(query, user=user, tenant_id=str(tenant.id))

    extracted_filters = _try_extract_filters(query, tenant=tenant, user=user)

    results = raw_results
    is_ai_enhanced = extracted_filters is not None and bool(extracted_filters)

    module_filter = extracted_filters.get("module") if extracted_filters else None
    if module_filter is not None:
        # `SearchResult.content_type` (cf. `apps.core.services.search`) ne
        # porte que le nom de MODELE (`doc.content_type.model`), pas
        # l'app_label — on resout donc, via l'ORM standard (jamais de SQL
        # brut), l'ensemble des noms de modeles appartenant a l'app_label
        # `module_filter` (deja valide contre la liste blanche), puis on
        # filtre en Python la liste de resultats DEJA recuperee/securisee
        # par `global_search()` — jamais une seconde requete construite a
        # partir d'une valeur extraite par le LLM.
        module_model_names = set(
            ContentType.objects.filter(app_label=module_filter).values_list("model", flat=True)
        )
        results = [r for r in raw_results if r.content_type in module_model_names]

    return NlSearchResponse(
        query=query,
        results=[asdict(r) for r in results],
        extracted_filters=extracted_filters if extracted_filters else None,
        is_ai_enhanced=is_ai_enhanced,
    )


__all__ = ["ExtractedFilters", "NlSearchResponse", "search"]
