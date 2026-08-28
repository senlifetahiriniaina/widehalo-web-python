"""Cree un compte administrateur par defaut sur une instance fraichement
installee, pour que l'application soit immediatement utilisable sans passer
par l'API/l'admin Django avant toute chose (cf. docs/DEPLOYMENT_HETZNER.md).

**Identifiant** : l'authentification de ce socle est batie sur l'e-mail
(`USERNAME_FIELD = "email"`, etape 4) — un identifiant litteral "admin" sans
"@" echouerait a la fois la validation HTML5 du formulaire de connexion et
`EmailField`. Le compte utilise donc `admin@admin.local` comme email
(reconnaissable, jamais un domaine reel) avec le mot de passe "admin" —
c'est ce mot de passe, jamais l'identifiant, qui porte la valeur "admin/admin"
demandee. Ce mot de passe est volontairement DANS la liste des mots de passe
courants (rejete par `CommonPasswordValidator`) : il ne peut donc jamais
etre choisi de nouveau au changement de mot de passe obligatoire ci-dessous,
qui est OBLIGATOIRE des la premiere connexion (`must_change_password=True`,
applique par `apps.core.middleware.OnboardingMiddleware`).

**Idempotence stricte** : ne s'execute que si AUCUN superutilisateur
n'existe encore (`User.objects.filter(is_superuser=True)`) — PAS un simple
`User.objects.exists()`, qui serait toujours vrai : `django-guardian`
(deja active dans ce socle pour le RBAC N3, etape 5) cree automatiquement
un utilisateur `AnonymousUser` reel en base via un signal `post_migrate`
(`ANONYMOUS_USER_NAME`), present des le premier `migrate` sur TOUTE
instance — bug reel trouve en ecrivant les tests de cette commande (le
garde-fou initial ne se declenchait jamais). Rien a voir avec un vrai
compte utilisateur : ce garde-fou corrige reste sans danger a rappeler a
chaque demarrage de conteneur (cf. docker/entrypoint.sh), exactement comme
`migrate` — jamais declenche sur une instance deja peuplee d'un vrai
superutilisateur, meme si l'admin par defaut a ete supprime depuis."""

from __future__ import annotations

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import BaseCommand

from apps.core.models.user import User

DEFAULT_ADMIN_EMAIL = "admin@admin.local"
DEFAULT_ADMIN_PASSWORD = "admin"  # noqa: S105 — identifiant de PREMIERE UTILISATION uniquement, changement forcé à la première connexion (jamais un secret de production).


class Command(BaseCommand):
    help = (
        "Cree un compte administrateur par defaut (admin@admin.local / admin, "
        "mot de passe a changer obligatoirement a la premiere connexion) si "
        "et seulement si aucun superutilisateur n'existe encore sur cette "
        "instance."
    )

    def handle(self, *args, **options) -> None:
        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write("Un superutilisateur existe déjà — bootstrap ignoré.")
            return

        call_command("load_roles")
        user = User.objects.create_superuser(
            email=DEFAULT_ADMIN_EMAIL,
            password=DEFAULT_ADMIN_PASSWORD,
            must_change_password=True,
        )
        admin_group = Group.objects.get(name="admin")
        user.groups.add(admin_group)

        self.stdout.write(
            self.style.WARNING(
                f"Compte administrateur par défaut créé : {DEFAULT_ADMIN_EMAIL} / "
                f"{DEFAULT_ADMIN_PASSWORD} — changement de mot de passe obligatoire "
                "à la première connexion, suivi du paramétrage de la première "
                "société de cette instance."
            )
        )
