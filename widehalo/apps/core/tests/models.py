"""Modele de test dedie, herite de BaseModel, utilise uniquement par les
tests du socle (isolation tenant, RLS, workflow...). N'est jamais expose en
API ni en ecran — ne compte pas dans le budget fonctionnel V1."""

from django.db import models

from apps.core.models.base import BaseModel


class SampleTenantScopedRecord(BaseModel):
    label = models.CharField(max_length=100)

    class Meta:
        app_label = "core"
        db_table = "core_test_sample_record"
