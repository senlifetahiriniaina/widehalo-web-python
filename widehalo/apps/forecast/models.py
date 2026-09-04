"""Module Forecast (cahier Phase 2 §13.2) : prévision de ventes,
d'encaissements et de trésorerie dont l'erreur est connue et publiée.

**4 modèles seulement** (budget d'architecture serré, `tests/architecture/
test_budget.py`) — l'historique lui-même n'est JAMAIS dupliqué ici : il
est lu à chaque calcul depuis les faits déjà matérialisés par
`apps.analytics` (`services/history.py`), jamais recopié dans une table
`forecast`. Ce module ne stocke que ce que l'entrepôt ne porte pas déjà :
le calendrier de référence, les points exceptionnels marqués, le
diagnostic/résultat de chaque calcul de série, et les instantanés publiés.

**Distinction avec `apps.sales.SalesForecast` (Phase 1, RG-SAL-7/8)** :
`SalesForecast` est une prévision de DEMANDE (quantité par produit,
méthode explicable, sans rétrotest ni erreur publiée) consommée par le
réapprovisionnement — périmètre et grain différents, jamais remplacée ni
étendue ici. `ForSeriesForecast` est une prévision de VALEUR (ventes/
encaissements en Ariary, à la maille famille/article/client/canal) avec
erreur mesurée par rétrotest glissant (FOR-2) — le cahier les distingue
explicitement (§13.2, "prévision de besoins matière... reportée en
Phase 3" — periste `SalesForecast` reste le seul outil de demande tant
que Phase 3 n'existe pas)."""

from __future__ import annotations

from decimal import Decimal

from apps.core.models.base import BaseModel
from django.db import models


class ForHoliday(BaseModel):
    """Jour férié malgache (FOR-5 : « calendrier applique jours ouvrés/
    fériés malgaches lus en table de référence ; un test vérifie qu'aucune
    date fériée n'est écrite dans le code »). Un jour ouvré = ni samedi/
    dimanche ni ligne `ForHoliday` — pas de table "tous les jours" (économie
    de volume), seules les EXCEPTIONS sont stockées."""

    date = models.DateField()
    name = models.CharField(max_length=120)

    class Meta:
        db_table = "for_holiday"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "date"], name="uniq_for_holiday_date")
        ]
        ordering = ["date"]

    def __str__(self) -> str:
        return f"{self.date.isoformat()} — {self.name}"


class ForExceptionalPoint(BaseModel):
    """Point exceptionnel marqué sur l'historique d'une série (FOR-4 :
    « exclus de l'apprentissage sans disparaître de l'historique affiché »)
    — table creuse, une ligne PAR EXCEPTION marquée (rupture d'appro, promo
    isolée...), jamais une ligne par période historique."""

    DIMENSION_FAMILLE = "famille"
    DIMENSION_ARTICLE = "article"
    DIMENSION_CLIENT = "client"
    DIMENSION_CANAL = "canal"
    DIMENSION_CHOICES = [
        (DIMENSION_FAMILLE, "Famille"),
        (DIMENSION_ARTICLE, "Article"),
        (DIMENSION_CLIENT, "Client"),
        (DIMENSION_CANAL, "Canal"),
    ]

    dimension_type = models.CharField(max_length=16, choices=DIMENSION_CHOICES)
    dimension_value = models.CharField(max_length=64)
    period = models.DateField(help_text="Premier jour de la période (maille mensuelle)")
    reason = models.CharField(max_length=255)

    class Meta:
        db_table = "for_exceptional_point"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "dimension_type", "dimension_value", "period"],
                name="uniq_for_exceptional_point",
            )
        ]
        ordering = ["-period"]

    def __str__(self) -> str:
        return f"{self.dimension_type}:{self.dimension_value} @ {self.period}"


class ForSeriesForecast(BaseModel):
    """Diagnostic + résultat de prévision pour UNE série à UNE période
    (grain = maille de pilotage mensuelle) — cœur du module. Le
    "diagnostic de série" et l'"atelier de prévision" du cahier (§13.2)
    sont deux vues sur les mêmes lignes, jamais deux modèles séparés.

    `adjustment_history` (JSONField) : trace complète et réversible de tout
    ajustement humain (FOR-6) — ``[{"author_id", "at", "before", "after",
    "reason"}, ...]`` — `statistical_value` n'est JAMAIS écrasé par un
    ajustement : `adjusted_value` porte la valeur retenue, `statistical_
    value` reste consultable en parallèle (cahier : "la prévision
    statistique reste consultable en parallèle")."""

    DIMENSION_FAMILLE = ForExceptionalPoint.DIMENSION_FAMILLE
    DIMENSION_ARTICLE = ForExceptionalPoint.DIMENSION_ARTICLE
    DIMENSION_CLIENT = ForExceptionalPoint.DIMENSION_CLIENT
    DIMENSION_CANAL = ForExceptionalPoint.DIMENSION_CANAL
    DIMENSION_CHOICES = ForExceptionalPoint.DIMENSION_CHOICES

    MODEL_NAIVE_SAISONNIER = "naive_saisonnier"
    MODEL_MOYENNE_MOBILE = "moyenne_mobile"
    MODEL_LISSAGE_SIMPLE = "lissage_simple"
    MODEL_LISSAGE_DOUBLE = "lissage_double"
    MODEL_LISSAGE_TRIPLE = "lissage_triple"
    MODEL_REGRESSION_CALENDAIRE = "regression_calendaire"
    MODEL_CHOICES = [
        (MODEL_NAIVE_SAISONNIER, "Référence naïve saisonnière"),
        (MODEL_MOYENNE_MOBILE, "Moyenne mobile"),
        (MODEL_LISSAGE_SIMPLE, "Lissage exponentiel simple"),
        (MODEL_LISSAGE_DOUBLE, "Lissage exponentiel double"),
        (MODEL_LISSAGE_TRIPLE, "Lissage exponentiel triple"),
        (MODEL_REGRESSION_CALENDAIRE, "Régression calendaire"),
    ]

    dimension_type = models.CharField(max_length=16, choices=DIMENSION_CHOICES)
    dimension_value = models.CharField(max_length=64)
    period = models.DateField(help_text="Premier jour de la période prévue")

    # FOR-1 : toujours calculée, quel que soit le modèle finalement retenu.
    reference_naive_value = models.DecimalField(max_digits=18, decimal_places=4)
    reference_naive_beats_selected = models.BooleanField(default=False)

    # FOR-3 : sélection reproductible et auditée.
    selected_model = models.CharField(max_length=24, choices=MODEL_CHOICES)
    selected_model_score = models.DecimalField(max_digits=9, decimal_places=4)
    rejected_models = models.JSONField(default=list, blank=True)
    test_window_start = models.DateField()
    test_window_end = models.DateField()
    insufficient_history_for_seasonality = models.BooleanField(default=False)

    # FOR-2 : erreur mesurée par rétrotest glissant (jamais sur l'historique
    # complet, cf. docstring de `services/engine.py`).
    error_mae_pct = models.DecimalField(max_digits=9, decimal_places=4, null=True, blank=True)
    error_weighted_pct = models.DecimalField(max_digits=9, decimal_places=4, null=True, blank=True)
    error_bias_pct = models.DecimalField(max_digits=9, decimal_places=4, null=True, blank=True)

    statistical_value = models.DecimalField(max_digits=18, decimal_places=4)
    adjusted_value = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    adjustment_history = models.JSONField(default=list, blank=True)

    # FOR-7 : mesuré une fois la période échue (l'actuel est alors connu).
    adjustment_error_pct = models.DecimalField(
        max_digits=9, decimal_places=4, null=True, blank=True
    )
    statistical_error_pct = models.DecimalField(
        max_digits=9, decimal_places=4, null=True, blank=True
    )

    computed_at = models.DateTimeField()

    class Meta:
        db_table = "for_series_forecast"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "dimension_type", "dimension_value", "period"],
                name="uniq_for_series_forecast",
            )
        ]
        ordering = ["dimension_type", "dimension_value", "period"]

    def __str__(self) -> str:
        return f"{self.dimension_type}:{self.dimension_value} @ {self.period}"

    @property
    def final_value(self) -> Decimal:
        return self.adjusted_value if self.adjusted_value is not None else self.statistical_value


class ForPublication(BaseModel):
    """Instantané publié (FOR-10 : « disponible comme scénario de
    référence dans la simulation financière, avec version et date »).
    Immuable une fois créé (même discipline que `SimBaseline`) — un
    nouvel appel de `services/publication.py::publish` crée toujours une
    NOUVELLE ligne, jamais une modification en place."""

    version = models.PositiveIntegerField()
    published_at = models.DateTimeField()
    published_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    period_start = models.DateField()
    period_end = models.DateField()
    # Liste des `ForSeriesForecast.final_value` au moment de la publication
    # — [{"dimension_type", "dimension_value", "period", "value"}, ...].
    snapshot = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "for_publication"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "version"], name="uniq_for_publication_version"
            )
        ]
        ordering = ["-version"]

    def __str__(self) -> str:
        return f"Publication v{self.version} ({self.published_at:%Y-%m-%d})"
