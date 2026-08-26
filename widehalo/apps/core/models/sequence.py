from __future__ import annotations

from django.db import models

from apps.core.db.uuid7 import uuid7


class Sequence(models.Model):
    """Compteur de numerotation metier, verrouille en transaction pour
    generer des references sans collision (cf. services/sequences.py)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tenant = models.ForeignKey("core.Tenant", on_delete=models.CASCADE)
    code = models.CharField(max_length=64)
    fiscal_year = models.PositiveIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "core_sequence"
        unique_together = ("tenant", "code", "fiscal_year")

    def __str__(self) -> str:
        return f"{self.code}/{self.fiscal_year} @ {self.tenant_id} = {self.last_number}"
