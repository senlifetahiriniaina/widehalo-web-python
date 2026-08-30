"""Module `ai` (AI1, socle) — cf. plan section « Module `ai` (Intelligence
artificielle transversale) ». `AiUsageLimit`/`AiRequest` portent le budget
de tokens par tenant et le journal d'audit des appels IA — ni l'un ni
l'autre n'est un document numerote (`ReferenceMixin` non applique, meme
raisonnement que `PrjTaskDependency`/`PrjBudgetLine` du chantier
`projects`)."""

from __future__ import annotations

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models.base import BaseModel
from apps.core.services.anomaly_registry import SEVERITY_HIGH, SEVERITY_LOW, SEVERITY_MEDIUM

DEFAULT_MONTHLY_TOKEN_BUDGET = 100_000
DEFAULT_ALERT_THRESHOLD_PCT = 80


class AiUsageLimit(BaseModel):
    """Configuration du budget de tokens IA d'un tenant — **une seule ligne
    par tenant** (`UniqueConstraint`), creee a la demande via `apps.ai.
    services.usage_budget.get_or_create_usage_limit()` avec des valeurs par
    defaut raisonnables plutot que d'exiger une configuration manuelle
    prealable (coherent avec la discipline « fallback-first » de ce
    chantier : l'absence de configuration ne doit jamais bloquer, ni non
    plus autoriser une consommation illimitee)."""

    monthly_token_budget = models.PositiveIntegerField(default=DEFAULT_MONTHLY_TOKEN_BUDGET)
    alert_threshold_pct = models.PositiveSmallIntegerField(default=DEFAULT_ALERT_THRESHOLD_PCT)
    # Au-dela du budget : `True` (defaut) bascule silencieusement sur
    # `StubAIProvider` (jamais un appel reseau facture en plus) ; `False`
    # continue d'autoriser les appels reels au-dela du seuil (simple alerte
    # informative) — un tenant qui accepte explicitement de depasser son
    # budget prevu, jamais le comportement par defaut.
    hard_stop = models.BooleanField(default=True)

    class Meta:
        db_table = "ai_usage_limit"
        constraints = [
            models.UniqueConstraint(fields=["tenant"], name="uniq_ai_usage_limit_per_tenant"),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id} — {self.monthly_token_budget} tokens/mois"


class AiRequest(BaseModel):
    """Journal d'audit d'un appel a une fonctionnalite IA — alimente le
    calcul de consommation mensuelle (`current_month_token_usage`) et la
    tracabilite du fournisseur reellement utilise (`provider_backend`,
    ex. `"deepseek"`/`"kimi"`/`"local-ollama"`/`"stub"`)."""

    FEATURE_ASSIST = "assist"
    FEATURE_ANOMALY_NARRATIVE = "anomaly_narrative"
    FEATURE_SEARCH = "search"
    FEATURE_INSIGHT = "insight"
    FEATURE_RECOMMENDATION = "recommendation"
    FEATURE_CHOICES = [
        (FEATURE_ASSIST, _("Assistant contextuel")),
        (FEATURE_ANOMALY_NARRATIVE, _("Narrative d'anomalie")),
        (FEATURE_SEARCH, _("Recherche en langage naturel")),
        (FEATURE_INSIGHT, _("Insight proactif")),
        (FEATURE_RECOMMENDATION, _("Recommandation d'action")),
    ]

    feature = models.CharField(max_length=32, choices=FEATURE_CHOICES)
    # Approximation grossiere (nombre de mots x facteur, cf. services/
    # usage_budget.py::estimate_tokens) — aucun tokenizer exact du
    # fournisseur cible n'est disponible sans dependance supplementaire,
    # disclosed comme non-exacte, suffisante pour un suivi de budget
    # indicatif plutot qu'une facturation au centime pres.
    prompt_tokens_estimate = models.PositiveIntegerField(default=0)
    completion_tokens_estimate = models.PositiveIntegerField(default=0)
    provider_backend = models.CharField(max_length=32, default="stub")
    succeeded = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "ai_request"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.feature} ({self.provider_backend})"

    @property
    def total_tokens_estimate(self) -> int:
        return self.prompt_tokens_estimate + self.completion_tokens_estimate


class AiAnomaly(BaseModel):
    """AI3 (detection d'anomalies cross-modules) — persistance d'un
    `AnomalyCandidate` (cf. `apps.core.services.anomaly_registry`) DEJA
    detecte deterministiquement par un module metier, jamais un objet cree
    ou evalue par un LLM. Pas de `ReferenceMixin` : c'est un enregistrement
    d'audit/de suivi (comme `AiRequest`), pas un document numerote que
    l'utilisateur cree lui-meme.

    **Rattachement generique** (`content_type`/`object_id`/
    `content_object`) : meme patron exact que `apps.core.models.risk.
    RiskItem` — une anomalie peut concerner N'IMPORTE QUELLE entite de
    N'IMPORTE QUEL module (`AccBudgetLine`, `StkQuant`, `PrjTask`,
    `SalesForecast`...) sans que `apps.ai` ait jamais besoin d'importer le
    modele concret d'un autre module (regle de couplage n5 : seul
    `content_type_label`, une chaine "app_label.modelname", traverse la
    frontiere, cf. `apps.ai.services.anomaly_detection`). Nullable pour la
    meme raison que `RiskItem` : un futur check purement agrege/tenant-wide
    sans entite precise a designer ne doit pas etre exclu par une
    contrainte NOT NULL non demandee ici.

    `check_code` est un texte libre (ex. "accounting.budget_variance"),
    PAS une cle etrangere vers le registre : celui-ci est un dict en
    memoire (`anomaly_registry._REGISTRY`), jamais une table — un code
    orphelin (module ayant retire son check) reste lisible dans
    l'historique plutot que de faire echouer une contrainte FK."""

    STATUS_OPEN = "ouverte"
    STATUS_HANDLED = "traitee"
    STATUS_IGNORED = "ignoree"
    STATUS_CHOICES = [
        (STATUS_OPEN, _("Ouverte")),
        (STATUS_HANDLED, _("Traitee")),
        (STATUS_IGNORED, _("Ignoree")),
    ]

    SEVERITY_CHOICES = [
        (SEVERITY_LOW, _("Faible")),
        (SEVERITY_MEDIUM, _("Moyenne")),
        (SEVERITY_HIGH, _("Haute")),
    ]

    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=64, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")

    check_code = models.CharField(max_length=64)
    severity = models.CharField(max_length=8, choices=SEVERITY_CHOICES)
    # Description DETERMINISTE fournie par la fonction de verification du
    # module metier — jamais generee par un LLM (cf. docstring de module
    # `anomaly_registry`).
    description = models.TextField()
    # Narrative optionnelle en prose (resume humain-lisible), generee par
    # IA UNIQUEMENT si un fournisseur reel est configure et disponible —
    # vide sinon, jamais un texte de substitution invente ici (cf.
    # `apps.ai.services.anomaly_detection`).
    ai_narrative = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_OPEN)

    class Meta:
        db_table = "ai_anomaly"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self) -> str:
        return f"{self.check_code} ({self.severity})"


class AiInsight(BaseModel):
    """AI5 (insights proactifs automatises) — persistance d'un
    `InsightCandidate` (cf. `apps.core.services.insight_source_registry`)
    DEJA calcule deterministiquement par un module metier a partir de
    donnees deja existantes, jamais une observation inventee par un LLM.
    Pas de `ReferenceMixin` : meme raisonnement exact que `AiRequest`/
    `AiAnomaly` — un enregistrement d'audit/de suivi, pas un document
    numerote que l'utilisateur cree lui-meme.

    `category` est un texte libre (ex. "ventes"/"rh"/"tresorerie"/
    "synthese"), volontairement PAS une liste `choices` figee : les
    categories d'insight vont croitre organiquement au fil des modules qui
    s'enregistrent (meme raisonnement que `check_code` sur `AiAnomaly` —
    un code/une categorie orpheline reste lisible dans l'historique plutot
    que de faire echouer une contrainte).

    `title`/`body` : texte libre SANS `gettext_lazy`, meme raisonnement
    exact que `AiAnomaly.description`/`ai_narrative` — un contenu
    potentiellement genere (par un module metier en langue du tenant, ou
    par un LLM pour l'insight de synthese) n'est jamais une chaine
    d'interface a traduire au sens i18n de ce depot.

    `source_modules` (`JSONField`, liste de labels d'app, ex.
    `["sales", "presence"]`) : quel(s) module(s) metier ont fourni la
    donnee source de cet insight — le plus souvent un seul, plus d'un
    uniquement pour un insight de synthese cross-module (cf. `apps.ai.
    services.automated_insights`).

    `is_ai_generated` : `False` pour un insight purement deterministe issu
    d'un adaptateur de module metier (le cas courant), `True` uniquement
    pour l'insight de synthese cross-module optionnel enrichi par un LLM
    — meme distinction exacte que `AiAnomaly.ai_narrative` (vide/rempli)
    et `AssistResponse.is_ai_generated`."""

    category = models.CharField(max_length=32)
    title = models.CharField(max_length=200)
    body = models.TextField()
    source_modules = models.JSONField(default=list, blank=True)
    is_ai_generated = models.BooleanField(default=False)

    class Meta:
        db_table = "ai_insight"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.category} — {self.title}"


class AiRecommendation(BaseModel):
    """AI7 (advisor d'actions, next-best-action) — persistance d'une
    `RecommendationCandidate` (cf. `apps.core.services.advisor_rule_
    registry`) DEJA decidee deterministiquement par une regle d'un module
    metier, OU d'un rapprochement direct avec `core.services.automation_
    registry` (une action deja automatisable pour ce module est une
    candidate naturelle de suggestion, cf. `apps.ai.services.
    action_advisor`) — jamais une decision prise par un LLM (meme
    discipline « explicabilite d'abord » que `AiAnomaly`/`AiInsight`).

    Pas de `ReferenceMixin` : meme raisonnement exact que `AiRequest`/
    `AiAnomaly`/`AiInsight` — un enregistrement d'audit/de suivi, pas un
    document numerote que l'utilisateur cree lui-meme. Pas de
    `content_type`/`object_id` generique non plus (contrairement a
    `AiAnomaly`) : une recommandation est intrinsequement scopee au
    CONTEXTE module/action/role de l'ecran en cours, jamais rattachee a
    une entite individuelle precise.

    **`label` EST enveloppe en `gettext` au moment de la creation
    (deviation disclosed par rapport a `AiAnomaly.description`/`AiInsight.
    body`, qui restent volontairement du texte libre non traduit)** : ces
    deux precedents interpolent des donnees runtime dans une phrase
    construite a la volee par l'appelant (jamais un texte fixe), alors
    qu'un `label` de recommandation est choisi parmi un petit ensemble de
    chaines COURTES et FIXES, authored une fois pour toutes par la regle
    qui l'enregistre — la meme forme que les libelles de `RegisteredAction.
    label`/`AiRequest.FEATURE_CHOICES`, un cas authentique de "copie
    d'interface", pas de "contenu genere". La chaine est resolue et
    stockee DEJA traduite (`django.utils.translation.gettext`, actif via
    `LocaleMiddleware` sur la requete courante) au moment de l'appel a
    `suggest()` plutot que `gettext_lazy` : la signature de plan
    `suggest(module, action, *, tenant, role_code)` ne transporte pas de
    parametre `locale` explicite (contrairement a `contextual_assistant.
    assist`), donc s'appuyer sur la langue active de la requete en cours
    est le mecanisme d'i18n le plus simple qui n'impose pas d'elargir
    cette signature actee par le plan.

    `target_module`/`target_action_code` : reference textuelle (jamais une
    FK) vers une action potentiellement enregistree dans `core.services.
    automation_registry` — meme discipline generique-par-code que
    `AiAnomaly.check_code` (un code orphelin, ex. action retiree depuis,
    reste lisible dans l'historique plutot que de faire echouer une
    contrainte). `target_action_code` reste vide quand la recommandation
    n'a pas de contrepartie automatisable connue (simple conseil, pas
    d'action a un clic)."""

    context_module = models.CharField(max_length=64)
    context_action = models.CharField(max_length=64)
    role_code = models.CharField(max_length=32)
    label = models.CharField(max_length=255)
    target_module = models.CharField(max_length=64, blank=True, default="")
    target_action_code = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        db_table = "ai_recommendation"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["context_module", "context_action", "role_code"])]

    def __str__(self) -> str:
        return f"{self.context_module}.{self.context_action} ({self.role_code}) — {self.label}"
