from __future__ import annotations

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.db.uuid7 import uuid7


class UserManager(DjangoUserManager["User"]):
    pass


class User(AbstractUser):
    """Utilisateur global — un compte peut appartenir a plusieurs societes
    via UserTenantMembership (sélecteur de société apres login), sans etre
    duplique par tenant."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    username = None  # type: ignore[assignment]
    email = models.EmailField(_("adresse e-mail"), unique=True)
    phone = models.CharField(max_length=32, blank=True)
    preferred_language = models.CharField(max_length=5, default="fr")
    must_change_password = models.BooleanField(default=False)
    auth_provider = models.CharField(max_length=16, default="local")
    """Point d'extension pour un futur SSO OIDC (V2) : seul 'local' est
    implemente dans ce lot."""

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []  # type: ignore[misc]

    objects: DjangoUserManager[User] = UserManager()  # type: ignore[misc]

    class Meta:
        db_table = "core_user"
        verbose_name = _("utilisateur")
        verbose_name_plural = _("utilisateurs")

    def __str__(self) -> str:
        return self.email


class UserTenantMembership(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tenant_memberships")
    tenant = models.ForeignKey("core.Tenant", on_delete=models.CASCADE, related_name="memberships")
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_user_tenant_membership"
        unique_together = ("user", "tenant")

    def __str__(self) -> str:
        return f"{self.user} @ {self.tenant}"
