"""Modele de test dedie, herite de BaseModel, utilise uniquement par les
tests du socle (isolation tenant, RLS, workflow...). N'est jamais expose en
API ni en ecran — ne compte pas dans le budget fonctionnel V1."""

from django.db import models
from django_fsm import FSMField, transition

from apps.core.models.base import BaseModel


class SampleTenantScopedRecord(BaseModel):
    """Modele de test dedie ; sert aussi de demonstration du moteur de
    workflow generique (3 etats : draft -> submitted -> approved)."""

    STATE_DRAFT = "draft"
    STATE_SUBMITTED = "submitted"
    STATE_APPROVED = "approved"

    label = models.CharField(max_length=100)
    state = FSMField(default=STATE_DRAFT)

    class Meta:
        app_label = "core"
        db_table = "core_test_sample_record"
        permissions = [("approve_sampletenantscopedrecord", "Peut approuver (demo workflow)")]

    @transition(field=state, source=STATE_DRAFT, target=STATE_SUBMITTED)
    def submit(self) -> None:
        pass

    @transition(
        field=state,
        source=STATE_SUBMITTED,
        target=STATE_APPROVED,
        permission="core.approve_sampletenantscopedrecord",
    )
    def approve(self) -> None:
        pass
