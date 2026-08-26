from __future__ import annotations

from typing import Any

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.db.uuid7 import uuid7


class UserManager(DjangoUserManager["User"]):
    """USERNAME_FIELD = 'email' : create_user/create_superuser prennent
    l'email en premier argument positionnel (pas de champ username, donc pas
    de reutilisation de UserManager._create_user qui l'exige)."""

    def _create(self, email: str, password: str | None, **extra_fields: Any) -> User:
        if not email:
            raise ValueError("L'adresse e-mail est obligatoire.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(  # type: ignore[override]
        self, email: str, password: str | None = None, **extra_fields: Any
    ) -> User:
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create(email, password, **extra_fields)

    def create_superuser(  # type: ignore[override]
        self, email: str, password: str | None = None, **extra_fields: Any
    ) -> User:
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Le superutilisateur doit avoir is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Le superutilisateur doit avoir is_superuser=True.")
        return self._create(email, password, **extra_fields)


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
