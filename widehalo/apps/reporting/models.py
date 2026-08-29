"""§5.11 Rapports. `RptDefinition` est un MIROIR persiste, par tenant, du
registre en memoire `apps.core.services.reports_registry` — pas une
redefinition : le code/module/permission/formats viennent tous du
`register_report()` appele par chaque module metier, `sync_report_
definitions()` (services/catalog.py) se contente de creer/mettre a jour les
lignes correspondantes. Le seul champ que ce miroir ajoute au registre est
`is_enabled`, une bascule PAR TENANT (RPT-5 : un tenant peut desactiver un
rapport de son catalogue sans toucher au code) — raison d'etre de cette
table plutot qu'un simple passage direct par le registre en API."""

from __future__ import annotations

from django.db import models

from apps.core.models.base import BaseModel


class RptDefinition(BaseModel):
    code = models.CharField(max_length=64, db_index=True)
    module = models.CharField(max_length=32)
    label = models.CharField(max_length=200)
    permission = models.CharField(max_length=128)
    supports_pdf = models.BooleanField(default=False)
    supports_rows = models.BooleanField(default=False)
    is_legal_document = models.BooleanField(default=False)
    # Bascule par tenant (RPT-5) — un rapport desactive n'apparait plus au
    # catalogue de ce tenant ni ne peut plus etre genere, sans affecter les
    # autres tenants ni le registre en memoire lui-meme.
    is_enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "rpt_definition"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_rpt_definition_code")
        ]
        ordering = ["module", "code"]

    def __str__(self) -> str:
        return f"{self.code} ({self.module})"


class RptLayout(BaseModel):
    """Gabarit de mise en page (RPT-3) — s'applique aux NOUVEAUX gabarits de
    ce module (catalogue, documents legaux archives via `legal_documents.
    render_and_archive`) uniquement. Les ~15 gabarits PDF deja construits par
    les 9 modules metier precedents ne sont PAS retrofites vers ce gabarit
    commun dans ce chantier (risque de regression visuelle pour un gain
    cosmetique) — dette d'harmonisation disclosed, cf. plan §reporting."""

    code = models.CharField(max_length=64, unique=False, db_index=True)
    name = models.CharField(max_length=200)
    template_path = models.CharField(max_length=255)
    is_default = models.BooleanField(default=False)

    class Meta:
        db_table = "rpt_layout"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_rpt_layout_code")
        ]

    def __str__(self) -> str:
        return self.name


class RptJob(BaseModel):
    """Suivi d'une generation de rapport (RPT-6 asynchronisme, RPT-9
    reproductibilite). Etats geres par simple `CharField` reecrit via
    `.save(update_fields=[...])`, PAS par django-fsm-2 : les transitions
    sont exclusivement pilotees par le systeme lui-meme (jamais une decision
    utilisateur gardee par permission, contrairement a un workflow metier
    FSM) — meme choix deja fait pour `core.EventLog.status` (cf.
    `apps/core/models/event.py`), aucune raison de s'en ecarter ici."""

    STATE_QUEUED = "queued"
    STATE_RUNNING = "running"
    STATE_DONE = "done"
    STATE_FAILED = "failed"
    STATE_CHOICES = [
        (STATE_QUEUED, "En attente"),
        (STATE_RUNNING, "En cours"),
        (STATE_DONE, "Termine"),
        (STATE_FAILED, "Echec"),
    ]

    FORMAT_PDF = "pdf"
    FORMAT_XLSX = "xlsx"
    FORMAT_CSV = "csv"
    FORMAT_JSON = "json"
    FORMAT_CHOICES = [
        (FORMAT_PDF, "PDF"),
        (FORMAT_XLSX, "XLSX"),
        (FORMAT_CSV, "CSV"),
        (FORMAT_JSON, "JSON"),
    ]

    report_code = models.CharField(max_length=64, db_index=True)
    params = models.JSONField(default=dict, blank=True)
    format = models.CharField(max_length=8, choices=FORMAT_CHOICES)
    lang = models.CharField(max_length=5, default="fr")
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_QUEUED)
    requested_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    file = models.FileField(upload_to="reports/jobs/", null=True, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    # RPT-6 : purge a 7 jours (meme patron que `sandbox.purge_expired_
    # sandboxes`) — positionne a la creation, jamais recalcule.
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "rpt_job"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.report_code} ({self.state})"
