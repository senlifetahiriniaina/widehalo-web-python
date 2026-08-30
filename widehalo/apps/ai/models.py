"""Module `ai` (AI1, socle) — cf. plan section « Module `ai` (Intelligence
artificielle transversale) ». `AiUsageLimit`/`AiRequest` portent le budget
de tokens par tenant et le journal d'audit des appels IA — ni l'un ni
l'autre n'est un document numerote (`ReferenceMixin` non applique, meme
raisonnement que `PrjTaskDependency`/`PrjBudgetLine` du chantier
`projects`)."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models.base import BaseModel

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
