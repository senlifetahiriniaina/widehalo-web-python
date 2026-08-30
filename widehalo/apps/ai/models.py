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
