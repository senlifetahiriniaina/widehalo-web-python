"""Module Simulation financière temps réel (cahier des charges WideHalo v3,
Phase 1, §13.6). Écart confirmé par l'audit (docs/audit/2026-09-cahier-des-charges-v3-audit.md,
SIM-1 à SIM-9) : ce module était entièrement absent du dépôt.

**Simplification assumée et disclosée** : 2 modèles seulement, contrairement
à l'estimation indicative du cahier (§10.1, "~4 pour la simulation (socle,
scénario, levier, comparaison)") — même discipline que `apps.pos.models`
(qui a lui aussi livré moins de modèles que l'estimation du §10.1). Le
"catalogue de leviers" est un jeu de données STATIQUE non éditable par
tenant (bornes, unités, familles) — un modèle n'ajouterait qu'une table de
configuration jamais modifiée en pratique, cf. `apps.simulation.levers`. La
"comparaison" (SIM-6) n'est jamais qu'une sélection ad hoc de 2 à 4
scénarios déjà persistés, comparée à la volée — aucun état à persister au-
delà des scénarios eux-mêmes.

Règle de couplage n°1 (identique à `sales`/`stocks`/`pos`) : `simulation` ne
fait jamais de FK Django vers `apps.sales`/`apps.accounting` — ces données
sont lues via `services.public` de chaque app puis agrégées dans le champ
`data` (JSON) de `SimBaseline`, jamais référencées par clé étrangère."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models.base import BaseModel


class SimBaseline(BaseModel):
    """Le « socle de simulation » (cahier : « un modèle compact et agrégé...
    chargé en un seul appel »). Construit par `services.baseline.build_
    baseline` — jamais modifié après création (une nouvelle demande de
    rafraîchissement crée un NOUVEAU `SimBaseline`, les anciens restent en
    base pour que les scénarios déjà créés conservent leur traçabilité
    d'origine, SIM-3).

    `data` porte l'intégralité du modèle agrégé : chiffres de référence
    (chiffre d'affaires, achats consommés, charges de personnel, charges
    financières, TVA...) ET la liste — plafonnée, cf. `services.baseline.
    MAX_OPEN_ITEMS` — des lignes recevables/payables ouvertes, brutes
    (montant + échéance), pour permettre au moteur (`services.engine`) de
    redécouper localement la projection de trésorerie à 13 semaines selon
    les leviers de délai de règlement (SIM-1, SIM-7)."""

    extracted_at = models.DateTimeField(auto_now_add=True)
    # Fenêtre de référence (chiffre d'affaires/marge/charges annualisés) —
    # par défaut les 12 derniers mois glissants avant `as_of_date`.
    period_start = models.DateField()
    period_end = models.DateField()
    # Date de référence des balances âgées/du prévisionnel de trésorerie
    # (SIM-7) — généralement la date de construction, distincte de
    # `period_end` (qui borne la fenêtre CA/marge, pas l'échéancier).
    as_of_date = models.DateField()
    # {"tva.taux_normal": 3, ...} — version de CHAQUE parametre
    # réglementaire utilisé, cf. `apps.core.services.regulatory.get_
    # parameter_with_version` (SIM-3).
    regulatory_param_version = models.JSONField(default=dict, blank=True)
    data = models.JSONField(default=dict, blank=True)
    # Nombre total de lignes ouvertes recevables/payables trouvées, avant
    # troncature au budget `MAX_OPEN_ITEMS` — permet à l'écran de signaler
    # explicitement une projection partielle (cf. cahier §7.6, "budget de
    # charge du socle de simulation... plafonné et vérifié en CI").
    open_items_total_count = models.PositiveIntegerField(default=0)
    open_items_included_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "sim_baseline"
        ordering = ["-extracted_at"]

    def __str__(self) -> str:
        return f"Socle {self.extracted_at:%Y-%m-%d %H:%M}"


class SimScenario(BaseModel):
    """Un scénario nommé de l'« atelier de scénarios » (cahier §13.6). Les
    leviers (`levers`, JSON `{code: valeur}` — codes du catalogue statique
    `apps.simulation.levers.LEVER_CATALOG`) et les indicateurs recalculés
    (`computed_indicators`) sont TOUJOURS le résultat du moteur déterministe
    serveur (`services.engine.compute_indicators`), jamais une valeur
    saisie ou proposée telle quelle par un utilisateur ou par l'IA
    (garde-fou cahier : « toute valeur affichée provient du moteur, jamais
    du modèle de langage »).

    `baseline_*` duplique (dénormalise) l'état du `SimBaseline` au moment
    de la création — SIM-3 : « un scénario enregistré conserve la date
    d'extraction du socle, le périmètre et la version des paramètres
    réglementaires appliqués », qui ne doit JAMAIS changer rétroactivement
    si un nouveau socle est construit plus tard (`baseline` reste une FK
    de traçabilité, `on_delete=PROTECT` — un socle référencé par un
    scénario ne peut pas être supprimé — mais les champs dénormalisés sont
    la source de vérité affichée)."""

    baseline = models.ForeignKey(SimBaseline, on_delete=models.PROTECT, related_name="scenarios")
    baseline_extracted_at = models.DateTimeField()
    baseline_period_start = models.DateField()
    baseline_period_end = models.DateField()
    baseline_as_of_date = models.DateField()
    baseline_regulatory_param_version = models.JSONField(default=dict, blank=True)

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    # Cahier §13.6, écran « Bibliothèque de scénarios » : « personnels ou
    # partagés » — `is_shared=True` rend le scénario visible aux autres
    # utilisateurs autorisés du tenant (`services.scenarios.list_
    # scenarios`), jamais modifiable par eux (seul `owner`/admin/direction
    # peut modifier ou archiver, cf. `services.scoping`).
    is_shared = models.BooleanField(default=False)

    levers = models.JSONField(default=dict, blank=True)
    computed_indicators = models.JSONField(default=dict, blank=True)

    # SIM-8 : « un scénario proposé par le copilote est exécuté par le
    # moteur déterministe » — un scénario n'est JAMAIS créé automatiquement
    # par l'appel de l'outil IA (`services.ai_data_query_registration`, qui
    # reste un calcul en lecture seule, cf. sa docstring) ; ces deux champs
    # ne sont renseignés que si un UTILISATEUR choisit explicitement
    # d'enregistrer une proposition du copilote via `services.scenarios.
    # apply_ai_proposed_levers`, action authentifiée et permissionnée
    # comme toute autre création de scénario.
    ai_generated = models.BooleanField(default=False)
    ai_request_text = models.TextField(blank=True, default="")

    class Meta:
        db_table = "sim_scenario"
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.name
