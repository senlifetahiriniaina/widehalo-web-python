"""Module Business Intelligence (cahier Phase 2 §13.1) : catalogue de
rapports self-service adossés au dictionnaire d'indicateurs gouverné
(`apps.analytics.AnMetricDefinition`), tableaux de bord composables par
rôle, diffusion planifiée journalisée.

**3 modèles seulement** (budget d'architecture serré, `tests/architecture/
test_budget.py`) — deux mécanismes explicitement décrits par le cahier
sont délibérément absents ici, RÉUTILISÉS plutôt que reconstruits :
- l'export asynchrone (BI-8) réutilise intégralement `apps.reporting`
  (`RptJob`/`generate_report`, cf. `services/export.py` et le nouveau gap
  `reporting.services.public.enqueue_report_generation`) — aucun modèle de
  job ici ;
- le versionnage d'indicateur (BI-9) vit sur `AnMetricDefinition` lui-même
  (`apps.analytics`, corrigé par ce même chantier pour préserver
  l'historique) — aucun modèle de version ici.

**Simplification assumée et disclosée (agrégats matérialisés, BI-5)** :
la performance "< 3 s sur profil réseau dégradé, trois exercices
d'historique" que le cahier impose est explicitement rattachée par le
texte à des "agrégats matérialisés, pas à l'optimisation de requêtes à la
volée". Ce chantier calcule chaque tuile/rapport EN DIRECT sur les faits
déjà matérialisés par `apps.analytics` (eux-mêmes au grain ligne, donc pas
pré-agrégés) plutôt que de construire une seconde couche de cache
matérialisé dédiée à `bi` — un choix délibéré pour rester dans le budget
de modèles de ce chantier. La condition "< 3 s en réseau dégradé" n'est
PAS vérifiable empiriquement dans ce bac à sable (aucun harnais de
limitation réseau, aucun volume de données à l'échelle de trois exercices
réels) ; ce gap de vérification est disclosé plutôt que tu."""

from __future__ import annotations

from django.db import models

from apps.core.models.base import BaseModel


class BiReport(BaseModel):
    """Un rapport self-service (BI-2 : "le constructeur n'accepte que des
    mesures et dimensions déclarées") — `definition` référence exclusivement
    des codes d'indicateur du dictionnaire gouverné et des codes d'axe
    abstraits (jamais un nom de champ ORM ni un fragment SQL, cf.
    `services/metric_computers.py`).

    `definition` (JSONField) :
    ``{"metric_codes": [str, ...], "dimensions": [str, ...],
    "filters": [{"dimension": str, "op": "eq"|"gte"|"lte"|"in",
    "value": ...}], "chart_type": "table"|"bar"|"line"|"pie"}``

    Champs de diffusion planifiée (BI-7) portés directement par le rapport
    plutôt qu'un modèle `Schedule` séparé — un rapport n'a, dans cette
    première itération, JAMAIS plus d'une planification active à la fois
    (simplification assumée et disclosée, économise un modèle)."""

    FREQUENCY_DAILY = "daily"
    FREQUENCY_WEEKLY = "weekly"
    FREQUENCY_MONTHLY = "monthly"
    FREQUENCY_CHOICES = [
        (FREQUENCY_DAILY, "Quotidienne"),
        (FREQUENCY_WEEKLY, "Hebdomadaire"),
        (FREQUENCY_MONTHLY, "Mensuelle"),
    ]

    code = models.SlugField(max_length=64)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    # Miroir de `AnMetricDefinition.module_source` du premier indicateur
    # utilisé — regroupement du catalogue par domaine (écran "Catalogue de
    # rapports", cf. docstring de module), purement indicatif.
    domaine = models.CharField(max_length=32, blank=True)
    owner = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    definition = models.JSONField(default=dict, blank=True)
    is_published = models.BooleanField(default=False)

    # Diffusion planifiée (BI-7) — cf. docstring ci-dessus.
    diffusion_enabled = models.BooleanField(default=False)
    diffusion_frequency = models.CharField(max_length=16, choices=FREQUENCY_CHOICES, blank=True)
    diffusion_recipients = models.JSONField(default=list, blank=True)
    diffusion_channel = models.CharField(max_length=16, default="email")
    diffusion_next_run_at = models.DateTimeField(null=True, blank=True)
    diffusion_last_run_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bi_report"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_bi_report_code")
        ]
        ordering = ["domaine", "name"]

    def __str__(self) -> str:
        return self.name


class BiDashboard(BaseModel):
    """Tableau de bord composable par rôle (§13.1, écran "Tableau de bord
    par rôle"). `tiles` (JSONField) : liste dénormalisée de références à
    des `BiReport` plutôt qu'une table de jointure dédiée (simplification
    assumée et disclosée — un tableau de bord n'a, dans cette première
    itération, ni ordre de tri par glisser-déposer persistant par
    utilisateur ni redimensionnement fin, seulement une position/une
    taille déclarées à la création) :
    ``[{"report_id": str(uuid), "position": int, "size": "sm"|"md"|"lg"}, ...]``"""

    name = models.CharField(max_length=200)
    owner = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Non vide = tableau de bord PAR DÉFAUT pour ce rôle (admin compose,
    # cf. docstring de module) ; vide = tableau de bord personnel d'un
    # utilisateur (`owner` alors obligatoire côté service).
    role_code = models.CharField(max_length=32, blank=True)
    tiles = models.JSONField(default=list, blank=True)
    is_shared = models.BooleanField(default=False)

    class Meta:
        db_table = "bi_dashboard"
        ordering = ["role_code", "name"]

    def __str__(self) -> str:
        return self.name


class BiDiffusionLog(BaseModel):
    """Journal de diffusion (BI-7 : "journalisée avec son destinataire,
    son périmètre, son canal et son statut") — une ligne PAR envoi, jamais
    modifiée après coup (même discipline que `AnRefreshRun`)."""

    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_SENT, "Envoyé"),
        (STATUS_FAILED, "Échec"),
    ]

    report = models.ForeignKey(BiReport, on_delete=models.CASCADE, related_name="diffusion_logs")
    recipient = models.CharField(max_length=200)
    channel = models.CharField(max_length=16, default="email")
    # Résumé du périmètre RÉELLEMENT appliqué pour ce destinataire (rôle,
    # nombre de lignes, dimensions masquées le cas échéant) — texte libre
    # à visée d'audit humain, jamais réinterprété par du code (même
    # discipline que `AnMetricDefinition.formule`).
    scope_summary = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    sent_at = models.DateTimeField()
    error_message = models.TextField(blank=True)

    class Meta:
        db_table = "bi_diffusion_log"
        ordering = ["-sent_at"]

    def __str__(self) -> str:
        return f"{self.report.code} -> {self.recipient} ({self.status})"
