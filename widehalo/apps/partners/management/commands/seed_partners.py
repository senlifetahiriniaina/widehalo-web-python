"""Jeu de demonstration `partners` (T10, CDC §8 couche 14 — prealable a
Schemathesis) : 6 partenaires couvrant les 4 roles (client, fournisseur,
transporteur, sous-traitant), avec des `credit_limit_mga` varies dont un
volontairement depasse (pour exercer `services.public.is_over_credit_limit`),
un doublon de NIF intentionnel (pour exercer la `DuplicateAlert` non
bloquante), et un utilisateur de demonstration muni du role `admin` (acces
`view/add/change` complet a `partners`, le plus large de la matrice RBAC —
pertinent ici puisque `partners` est un referentiel partage consulte/modifie
par plusieurs modules metier, pas le domaine reserve d'un seul role
commercial)."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandParser

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.rbac_policy import sync_group_permissions
from apps.core.services.smart_defaults import apply_country_defaults
from apps.core.tenant_context import activate_tenant
from apps.partners.models import Partner
from apps.partners.services.onboarding import create_partner

DEMO_USER_EMAIL = "admin.demo@widehalo.local"
DEMO_USER_PASSWORD = "DemoPartners#2026!"  # noqa: S105 - compte de demonstration, jamais en production

# (name, roles, nif, credit_limit_mga)
DEMO_PARTNERS = [
    ("Textiles Analakely SARL", [Partner.ROLE_CLIENT], "MG-NIF-100001", Decimal("5000000")),
    ("Boutique Hasina", [Partner.ROLE_CLIENT], "MG-NIF-100002", Decimal("1000000")),
    (
        "Grossiste Confection Toamasina",
        [Partner.ROLE_CLIENT, Partner.ROLE_SUBCONTRACTOR],
        "MG-NIF-100002",  # doublon volontaire du NIF ci-dessus -> DuplicateAlert
        Decimal("2000000"),
    ),
    ("Cotona Import SA", [Partner.ROLE_SUPPLIER], "MG-NIF-100004", Decimal("0")),
    ("Filatures de l'Ocean Indien", [Partner.ROLE_SUPPLIER], "MG-NIF-100005", Decimal("8000000")),
    ("Transport Rakoto & Fils", [Partner.ROLE_CARRIER], "MG-NIF-100006", Decimal("500000")),
    (
        "Atelier Sous-Traitance Sud",
        [Partner.ROLE_SUBCONTRACTOR],
        "MG-NIF-100007",
        Decimal("300000"),
    ),
]


class Command(BaseCommand):
    help = (
        "Cree un jeu de demonstration coherent pour le referentiel partners "
        "(7 partenaires couvrant client/fournisseur/transporteur/sous-traitant, "
        "un doublon de NIF intentionnel, un partenaire au-dela de son plafond "
        "de credit), utilisateur demo muni du role admin. Idempotent : "
        "aucun partenaire n'est recree si un partenaire du meme nom existe "
        "deja pour ce tenant (le nom sert de cle naturelle pour ce jeu de "
        "demonstration, faute d'unicite NIF imposee par le modele)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--tenant-code", default="DEMO", help="Code du tenant a creer/reutiliser."
        )

    def handle(self, *args, **options) -> None:
        tenant_code = options["tenant_code"]
        tenant, tenant_created = Tenant.objects.get_or_create(
            code=tenant_code,
            defaults={
                "name": "Societe demonstration WideHalo",
                "country_code": "MG",
                "fiscal_regime": Tenant.FISCAL_REGIME_REAL_WITH_VAT,
            },
        )
        if tenant_created:
            apply_country_defaults(tenant, "MG")

        with activate_tenant(tenant.id):
            demo_user, user_created = User.objects.get_or_create(
                email=DEMO_USER_EMAIL,
                defaults={"first_name": "Demo", "last_name": "Admin"},
            )
            if user_created:
                demo_user.set_password(DEMO_USER_PASSWORD)
                demo_user.save(update_fields=["password"])
            group, _ = Group.objects.get_or_create(name="admin")
            sync_group_permissions(group, "admin")
            demo_user.groups.add(group)

            existing_names = set(
                Partner.objects.filter(tenant=tenant).values_list("name", flat=True)
            )
            created_count = 0
            for name, roles, nif, credit_limit in DEMO_PARTNERS:
                if name in existing_names:
                    continue
                create_partner(
                    tenant=tenant, name=name, roles=roles, nif=nif, credit_limit_mga=credit_limit
                )
                created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"partners seed OK — tenant={tenant.code} partenaires_crees={created_count} "
                f"utilisateur_demo={DEMO_USER_EMAIL} (role admin)"
            )
        )
