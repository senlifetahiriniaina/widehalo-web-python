"""§5.11 Rapports. `RptDefinition` est un MIROIR persiste, par tenant, du
registre en memoire `apps.core.services.reports_registry` — pas une
redefinition : le code/module/permission/formats viennent tous du
`register_report()` appele par chaque module metier, `sync_report_
definitions()` (services/public.py) se contente de creer/mettre a jour les
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
