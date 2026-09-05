"""Jeu de demonstration `core` (T10, couche 14 CDC — TST-3) : le tenant
demo et les utilisateurs de base sur lesquels les autres commandes
`seed_<module>` (mrp/patronage/accounting/crm/partners/catalog) viennent se
greffer via `get_or_create`. C'est un prealable a la campagne Schemathesis
(§8, layer 14) : elle a besoin d'un tenant + d'utilisateurs deja actifs,
avec un role RBAC reellement autorise sur les endpoints qu'elle va exercer.

**Idempotence** : entierement base sur `get_or_create` par cle naturelle
(`Tenant.code`, `User.email`, `Group.name`) — relancer cette commande
plusieurs fois ne cree jamais de doublons, et resynchronise a chaque fois
les permissions des groles de roles (`load_roles`) au cas ou
`rbac_policy.ROLE_APP_PERMISSIONS` aurait change entre deux execution.

**Choix des roles des utilisateurs demo** : `settings.CORE_MFA_REQUIRED_ROLES`
= {"admin", "direction", "comptable", "rh"} bloquerait un login JWT direct
(Schemathesis n'a pas de flux d'enrolement TOTP) tant qu'aucun device MFA
n'est enrole. L'utilisateur PRINCIPAL de demo (`demo.production@...`) recoit
donc "resp_production" (acces mrp+patronage, les deux modules de ce lot),
qui n'est PAS dans cet ensemble. Un second utilisateur "demo.commercial@..."
recoit "commercial" (crm+partners), egalement hors MFA obligatoire, pour
couvrir les endpoints du second agent en parallele. Un troisieme
"demo.admin@..." recoit "admin" (acces large a tous les modules metier) —
utile pour l'exploration manuelle/l'admin Django, mais volontairement PAS
le login par defaut d'un futur test Schemathesis puisqu'il exigerait un
enrolement MFA prealable."""

from __future__ import annotations

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandParser

from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.services.rbac_policy import sync_group_permissions
from apps.core.services.smart_defaults import apply_country_defaults

DEMO_PASSWORD = "Str0ngPassw0rd!23"  # noqa: S105 — mot de passe de demo, jamais utilise en prod.

# (local-part de l'email, role RBAC) — les 3 utilisateurs de demo crees par
# ce seed. "resp_production" est le premier de la liste : c'est le login
# principal recommande pour Schemathesis (hors CORE_MFA_REQUIRED_ROLES).
DEMO_USERS: list[tuple[str, str]] = [
    ("demo.production", "resp_production"),
    ("demo.commercial", "commercial"),
    ("demo.admin", "admin"),
]


class Command(BaseCommand):
    help = (
        "Jeu de demonstration du socle core (tenant + roles + utilisateurs) — "
        "prealable partage aux commandes seed_<module> des autres apps."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant-code", default="DEMO")

    def handle(self, *args, **options) -> None:
        tenant_code = options["tenant_code"]

        tenant, created = Tenant.objects.get_or_create(
            code=tenant_code,
            defaults={
                "name": "WideHalo Demo",
                "country_code": "MG",
            },
        )
        # Idempotent (`retention_policy.setdefault`) : sans danger de
        # rappeler a chaque execution, y compris si le tenant preexistait.
        apply_country_defaults(tenant, "MG")
        # Catalogue de types de tickets helpdesk (54 entrees, idempotent par
        # tenant+code) — utile aux futures campagnes Schemathesis/demo qui
        # exerceraient les endpoints helpdesk.
        call_command("load_ticket_type_catalog", tenant=tenant_code)
        # Plan comptable PCG 2005 (generique + sectoriel, cf. UXR7) et 7
        # journaux comptables par defaut — idempotents, utiles aux futures
        # campagnes Schemathesis/demo qui exerceraient les endpoints
        # comptables. PCG charge AVANT les journaux : `load_default_journals`
        # resout `default_account` (BQ/CAI) par prefixe de code parmi les
        # comptes deja crees, donc l'ordre importe.
        call_command("load_chart_of_accounts", tenant=tenant_code)
        call_command("load_default_journals", tenant=tenant_code)

        call_command("load_roles")

        created_users = 0
        for local_part, role_code in DEMO_USERS:
            email = f"{local_part}@{tenant_code.lower()}.widehalo.local"
            user, was_created = User.objects.get_or_create(
                email=email,
                defaults={"is_staff": False, "is_superuser": False},
            )
            if was_created:
                user.set_password(DEMO_PASSWORD)
                user.save(update_fields=["password"])
                created_users += 1

            group, _ = Group.objects.get_or_create(name=role_code)
            sync_group_permissions(group, role_code)
            user.groups.add(group)

            UserTenantMembership.objects.get_or_create(
                user=user, tenant=tenant, defaults={"is_default": True}
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Tenant demo '{tenant.code}' ({'cree' if created else 'existant'}), "
                f"{len(DEMO_USERS)} utilisateurs demo verifies ({created_users} crees), "
                f"roles synchronises."
            )
        )
