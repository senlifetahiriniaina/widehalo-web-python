from __future__ import annotations

from typing import Any

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.db.uuid7 import uuid7
from apps.core.models.base import BaseModel

PREFERRED_LANGUAGE_CHOICES = [
    ("fr", "Français"),
    ("en", "English"),
    # Sprint 10 (L6 Personnalisation) : catalogue de traductions vide pour
    # l'instant (cf. locale/mg/LC_MESSAGES/django.po) -- l'utilisateur qui
    # choisit "Malagasy" voit donc l'application dans la langue source
    # (français) tant qu'une traduction professionnelle n'a pas été
    # fournie, jamais une erreur ni un fallback silencieux vers l'anglais.
    ("mg", "Malagasy"),
]

THEME_CHOICES = [
    ("light", "Clair"),
    ("dark", "Sombre"),
    ("system", "Système"),
]

DENSITY_CHOICES = [
    ("comfortable", "Confortable"),
    ("compact", "Compacte"),
]


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
    preferred_language = models.CharField(
        max_length=5, choices=PREFERRED_LANGUAGE_CHOICES, default="fr"
    )
    # Sprint 10 (L6 Personnalisation & offline) : `theme`/`density` sont de
    # simples preferences d'affichage (jamais de logique metier dessus).
    # "system" (defaut) se resout cote serveur en "light" (cf.
    # `apps.core.context_processors.account`) -- la resolution reelle du
    # `prefers-color-scheme` du systeme reste une amelioration cote client
    # (petit script inline dans base.html), coherente avec la discipline
    # "fonctionne sans JS, degrade proprement" du reste de ce chantier.
    theme = models.CharField(max_length=8, choices=THEME_CHOICES, default="system")
    density = models.CharField(max_length=12, choices=DENSITY_CHOICES, default="comfortable")
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
        # UXR1 : `core.manage_users` (meme patron que `projects.
        # bill_prjproject`, cf. `apps.core.services.rbac_policy`) garde le
        # nouvel ecran admin (`apps.core.views.admin_users`) qui liste/edite
        # TOUT utilisateur (roles, societes, changement d'e-mail via
        # `services/email_change.py`) — restreint a `admin`/`direction`,
        # jamais accorde via la matrice generique `ROLE_APP_PERMISSIONS`
        # (qui ne couvre pas `core`, cf. RSK1-2/QLT1-2 dans ce meme
        # registre pour le meme raisonnement).
        permissions = [("manage_users", "Peut gérer les comptes utilisateurs")]

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


class UserEmailChangeRequest(BaseModel):
    """UXR1 — confirmation d'un changement d'adresse e-mail par lien a
    jeton envoye par e-mail (cf. `apps.core.services.email_change`), jamais
    une ecriture directe de `User.email` depuis l'ecran admin
    (`apps.core.views.admin_users.admin_user_edit`). Delibere : `email` est
    `USERNAME_FIELD` (identite de connexion), le modifier sans verifier que
    le destinataire possede reellement cette boite mail romprait
    silencieusement l'acces au compte (faute de frappe, usurpation).

    **Pas de `ReferenceMixin`** (consigne explicite du plan) : cette table
    est un jeton de flux transitoire (24h), jamais un document metier
    numerote/recherche par reference.

    **`RLS_FORCE_FOR_OWNER = False`** : meme derogation, pour la meme
    raison structurelle, que `apps.projects.models.PrjGuestAccess` (cf. sa
    docstring et celle de `apps.core.management.commands.apply_rls`). La
    vue publique `GET /account/confirm-email/<token>/` (cf. `config.urls`)
    n'exige PAS de session authentifiee — le destinataire clique depuis sa
    boite mail, potentiellement sans jamais s'etre connecte depuis ce
    navigateur — donc AUCUN tenant n'est necessairement actif au moment de
    resoudre le token (meme probleme de la poule et l'oeuf que le portail
    invite PJ14). `confirm_email_change` (`services/email_change.py`)
    utilise donc `UserEmailChangeRequest.all_objects.filter(token_hash=...)`,
    jamais le manager `objects` filtre par tenant.

    **Rejet indiscernable** (token inconnu / deja confirme / expire) :
    `confirm_email_change` renvoie `False` dans les 3 cas, jamais une
    exception, meme discipline que `apps.projects.services.guest_portal.
    resolve_guest_access`.

    **L15 — la base ne stocke que l'empreinte du jeton.** Meme traitement,
    pour la meme raison, que `PrjGuestAccess.token_hash` : ce jeton donne le
    pouvoir de changer l'adresse e-mail d'un compte, c'est-a-dire son
    identifiant de connexion. Une empreinte SHA-256 plutot qu'un chiffrement
    parce que le champ est cherche par sa valeur (`confirm_email_change`) et
    que Fernet n'est pas deterministe ; nu, sans sel ni derivation lente,
    parce que `secrets.token_urlsafe(32)` porte 256 bits d'entropie et n'a
    donc rien a craindre d'un dictionnaire. L'audit ne signalait que deux
    secrets en clair (§3.6) ; celui-ci est le troisieme, trouve en fermant
    les deux autres."""

    RLS_FORCE_FOR_OWNER = False

    # Attribut TRANSITOIRE, jamais un champ : le jeton en clair, pose par
    # `request_email_change` le temps de composer le lien envoye par e-mail.
    plaintext_token: str | None = None

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="email_change_requests")
    new_email = models.EmailField()
    token_hash = models.CharField(max_length=64, unique=True, db_index=True, editable=False)
    requested_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Admin a l'origine du changement, ou None si l'utilisateur "
        "a lui-meme demande le changement.",
    )
    expires_at = models.DateTimeField()
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_user_email_change_request"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user_id} -> {self.new_email}"
