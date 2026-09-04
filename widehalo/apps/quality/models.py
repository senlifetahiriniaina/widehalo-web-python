"""Modeles de `apps.quality` (Qualite/HACCP, cahier Phase 3 §3.5, decision
D2 — application dediee plutot qu'une fusion dans `apps.stocks`, cf. l'ADR
`docs/planning/2026-09-adr-qualite-haccp-app-dediee.md`).

Bloc D, D1 (QUA-1/2/3) : domaine HACCP minimal — plan de controle, point
critique (limites), mesure reelle, non-conformite bloquante. Quatre
modeles reels (pas un JSONField sur un seul modele, contrairement aux
simplifications budgetaires pratiquees ailleurs dans ce depot) : un
domaine de conformite/audit a besoin de lignes interrogeables
individuellement (ex. "derniere mesure par lot" pour l'alerte de controle
du a D3, "toute non-conformite ouverte pour ce lot" pour le blocage de
liberation) — decision budgetaire actee explicitement avec l'utilisateur
(cf. `config/settings/base.py::BUDGET_MAX_MODELS`, releve 290->310).

**Rattachement generique, jamais une FK directe** : `QltMeasurement`/
`QltNonConformity` portent un `content_type`/`object_id` (GenericForeignKey
standard, meme patron que `core.models.risk.RiskItem`/
`core.models.quality.QltInspection`) vers le DOCUMENT SOURCE (une ligne de
reception, un ordre de fabrication...) — purement informatif/tracabilite,
jamais dereference par la logique de ce module pour un appel cross-app.
L'identite du LOT a bloquer/liberer est portee separement par
`lot_variant_id`/`lot_name` (UUID + nom, jamais un `StkLot` importe) — meme
convention exacte que `stocks.services.public.lot_genealogy_tree(*, tenant,
variant_id, name)`, seule facon dont `stocks` expose l'identite d'un lot a
un appelant cross-app."""

from __future__ import annotations

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.models.base import BaseModel, ReferenceMixin


class QltControlPlan(BaseModel):
    """Plan de controle HACCP — rattachement optionnel (choix assume, meme
    raisonnement que `RiskItem` : un plan generique sans document precis a
    designer reste un cas d'usage reel)."""

    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=64, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")

    name = models.CharField(max_length=150)
    # QUA-9 (D3) : frequence attendue entre deux controles reels sur un
    # lot rattache a ce plan. 0 = aucune alerte periodique attendue.
    frequency_days = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "qlt_control_plan"

    def __str__(self) -> str:
        return self.name


class QltCriticalPoint(BaseModel):
    """Point critique (CCP) — limites critiques d'un parametre mesure,
    rattache a un plan de controle."""

    control_plan = models.ForeignKey(
        QltControlPlan, on_delete=models.CASCADE, related_name="critical_points"
    )
    name = models.CharField(max_length=150)
    unit = models.CharField(max_length=16, blank=True)
    # Bornes optionnelles independamment l'une de l'autre (une limite
    # haute seule, ex. temperature max, est un cas d'usage aussi reel
    # qu'une fourchette complete).
    limit_min = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    limit_max = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    sequence = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "qlt_critical_point"
        ordering = ["sequence"]

    def __str__(self) -> str:
        return f"{self.control_plan} — {self.name}"


class QltMeasurement(BaseModel):
    """Mesure reelle prise contre un point critique. `is_within_limits`
    est DERIVE — jamais assigne directement par un appelant (meme
    discipline que `RiskItem.score`) : recalcule par
    `services/measurements.py::record_measurement`, jamais dans
    `Model.save()`."""

    critical_point = models.ForeignKey(
        QltCriticalPoint, on_delete=models.PROTECT, related_name="measurements"
    )
    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=64, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")

    lot_variant_id = models.UUIDField(null=True, blank=True)
    lot_name = models.CharField(max_length=64, blank=True)

    value = models.DecimalField(max_digits=18, decimal_places=4)
    is_within_limits = models.BooleanField(default=True, editable=False)

    measured_by = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="qlt_measurements"
    )
    measured_at = models.DateTimeField()

    class Meta:
        db_table = "qlt_measurement"
        indexes = [models.Index(fields=["lot_variant_id", "lot_name"])]

    def __str__(self) -> str:
        return f"{self.critical_point} = {self.value}"


class QltNonConformity(BaseModel, ReferenceMixin):
    """Non-conformite HACCP — ouverte automatiquement par une mesure hors
    limites (`measurement` renseigne), ou manuellement (`measurement`
    vide). Tant qu'une non-conformite `state=STATE_OPEN` existe pour un
    lot, `apps.quality.services.public.release_lot_hold` refuse de le
    liberer (QUA-1/2/3)."""

    STATE_OPEN = "open"
    STATE_CLOSED = "closed"
    STATE_CHOICES = [
        (STATE_OPEN, "Ouverte"),
        (STATE_CLOSED, "Clôturée"),
    ]

    measurement = models.ForeignKey(
        QltMeasurement,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="non_conformities",
    )
    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=64, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")

    lot_variant_id = models.UUIDField(null=True, blank=True)
    lot_name = models.CharField(max_length=64, blank=True)

    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_OPEN)
    # Motif obligatoire (jamais blank en pratique — impose par le service,
    # pas par une contrainte de champ, meme discipline que
    # `cancel_order(..., reason=...)` ailleurs dans ce depot).
    description = models.TextField()
    opened_by = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="qlt_opened_non_conformities"
    )
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_by = models.ForeignKey(
        "core.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="qlt_closed_non_conformities",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closing_reason = models.TextField(blank=True)

    class Meta:
        db_table = "qlt_non_conformity"
        verbose_name_plural = "Qlt non conformities"
        indexes = [models.Index(fields=["lot_variant_id", "lot_name", "state"])]

    def __str__(self) -> str:
        return self.reference or f"NC {self.id}"


class QltRecallDossier(BaseModel, ReferenceMixin):
    """Dossier de rappel HACCP (Bloc D, D4, QUA-4 à QUA-7) — déclenche la
    mise en quarantaine du lot d'origine ET de tous ses descendants
    (`stocks.services.public.set_quality_state`, réutilisé tel quel,
    jamais un second mécanisme de blocage), snapshotte le résultat de
    `stocks.services.public.lot_genealogy_tree` au moment de la
    déclaration (`genealogy_snapshot`/`impacted_lots`, JAMAIS recalculés
    a posteriori — un dossier de rappel est une preuve de "ce qui était
    su et déclaré à cet instant", même discipline documentée que
    `stocks.StkRecall`, dont ce modèle est délibérément distinct : le
    sort de `StkRecall` (migration/retrait) est différé au sprint D5 par
    l'ADR de P6, pas tranché ici).

    **Immuable dès sa création** (QUA-6/7) — trigger Postgres
    (`apps/quality/migrations/0003_recall_dossier_immutability.py`),
    même patron que le trigger `AccMove`/`StkMove` : seuls
    `state`/`closed_by`/`closed_at`/`closing_reason` restent modifiables
    pour la clôture, DELETE toujours refusé (ajout-seul)."""

    STATE_OPEN = "open"
    STATE_CLOSED = "closed"
    STATE_CHOICES = [
        (STATE_OPEN, "Ouvert"),
        (STATE_CLOSED, "Clôturé"),
    ]

    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=64, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")

    lot_variant_id = models.UUIDField(null=True, blank=True)
    lot_name = models.CharField(max_length=64, blank=True)

    reason = models.TextField()
    # Perimetre FIGE au moment de la generation, jamais recalcule a
    # posteriori — {"lot_id","lot_name","variant_id","ancestors",
    # "descendants"} avec UUID/Decimal deja convertis en str (JSONField
    # standard, pas de DjangoJSONEncoder — meme idiome que
    # stocks.services.recall.declare_recall).
    genealogy_snapshot = models.JSONField(default=dict, blank=True)
    # Liste a plat, dedupliquee, des lots mis en quarantaine —
    # [{"lot_variant_id": "...", "lot_name": "..."}, ...].
    impacted_lots = models.JSONField(default=list, blank=True)

    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_OPEN)
    initiated_by = models.ForeignKey(
        "core.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="qlt_recalls_initiated",
    )
    initiated_at = models.DateTimeField(auto_now_add=True)
    closed_by = models.ForeignKey(
        "core.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="qlt_recalls_closed",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closing_reason = models.TextField(blank=True)

    class Meta:
        db_table = "qlt_recall_dossier"
        verbose_name_plural = "Qlt recall dossiers"

    def __str__(self) -> str:
        return self.reference or f"Rappel {self.id}"
