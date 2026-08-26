from __future__ import annotations

from django.contrib.auth.models import Group
from django.db import models

from apps.core.db.uuid7 import uuid7


class RoleProfile(models.Model):
    """Metadonnees associees a un role standard (= un Group Django). Le
    Group porte les permissions N2 (objet-type) natives ; RoleProfile porte
    ce que le systeme de permissions Django ne modelise pas nativement."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    group = models.OneToOneField(Group, on_delete=models.CASCADE, related_name="role_profile")
    code = models.CharField(max_length=32, unique=True)
    description = models.CharField(max_length=255, blank=True)
    simple_mode_default = models.BooleanField(default=False)

    class Meta:
        db_table = "core_role_profile"

    def __str__(self) -> str:
        return self.code
