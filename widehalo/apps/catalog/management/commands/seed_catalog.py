"""Jeu de demonstration `catalog` (T10, CDC §8 couche 14 — prealable a
Schemathesis) : unites de mesure + conversions, categories, attributs/valeurs
generateurs de variantes, 2 gammes de produits avec variantes generees
(`generate_variants()`), une fiche technique textile (`TextileSpec`), une
liste de prix par defaut avec ses lignes, un conditionnement, une norme
catalogue avec une certification datee, et un utilisateur de demonstration
muni du role `admin` (acces `view/add/change` complet a `catalog`, coherent
avec le fait que `catalog` est un referentiel partage administre en dehors
d'un seul module metier)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandParser

from apps.catalog.models import (
    Attribute,
    AttributeValue,
    CatalogCertification,
    CatalogStandard,
    Category,
    Packaging,
    PriceList,
    PriceListItem,
    ProductTemplate,
    TextileSpec,
    UnitConversion,
    UnitOfMeasure,
)
from apps.catalog.services.variants import generate_variants, set_variant_attributes
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.rbac_policy import sync_group_permissions
from apps.core.services.smart_defaults import apply_country_defaults
from apps.core.tenant_context import activate_tenant

DEMO_USER_EMAIL = "admin.demo@widehalo.local"
DEMO_USER_PASSWORD = "DemoCatalog#2026!"  # noqa: S105 - compte de demonstration, jamais en production


class Command(BaseCommand):
    help = (
        "Cree un jeu de demonstration coherent pour le referentiel catalog "
        "(unites de mesure + conversions, categories, attributs/valeurs, 2 "
        "gammes de produits avec variantes generees, une fiche technique "
        "textile, une liste de prix, un conditionnement, une norme + "
        "certification), utilisateur demo muni du role admin. Idempotent : "
        "toute entite de configuration est get_or_create par son code/nom "
        "naturel ; les variantes d'une gamme ne sont (re)generees que si "
        "cette gamme n'en a encore aucune."
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

            # --- Unites de mesure + conversions -----------------------------
            kg, _ = UnitOfMeasure.objects.get_or_create(
                tenant=tenant,
                code="KG",
                defaults={
                    "name": "Kilogramme",
                    "category": UnitOfMeasure.CATEGORY_WEIGHT,
                    "is_base": True,
                },
            )
            g, _ = UnitOfMeasure.objects.get_or_create(
                tenant=tenant,
                code="G",
                defaults={"name": "Gramme", "category": UnitOfMeasure.CATEGORY_WEIGHT},
            )
            m, _ = UnitOfMeasure.objects.get_or_create(
                tenant=tenant,
                code="M",
                defaults={
                    "name": "Metre",
                    "category": UnitOfMeasure.CATEGORY_LENGTH,
                    "is_base": True,
                },
            )
            cm, _ = UnitOfMeasure.objects.get_or_create(
                tenant=tenant,
                code="CM",
                defaults={"name": "Centimetre", "category": UnitOfMeasure.CATEGORY_LENGTH},
            )
            pcs, _ = UnitOfMeasure.objects.get_or_create(
                tenant=tenant,
                code="PCS",
                defaults={
                    "name": "Piece",
                    "category": UnitOfMeasure.CATEGORY_COUNT,
                    "is_base": True,
                },
            )
            UnitConversion.objects.get_or_create(
                tenant=tenant, from_unit=kg, to_unit=g, defaults={"factor": Decimal("1000")}
            )
            UnitConversion.objects.get_or_create(
                tenant=tenant, from_unit=m, to_unit=cm, defaults={"factor": Decimal("100")}
            )

            # --- Categories --------------------------------------------------
            cat_confection, _ = Category.objects.get_or_create(tenant=tenant, name="Confection")
            cat_tshirts, _ = Category.objects.get_or_create(
                tenant=tenant, name="T-shirts", defaults={"parent": cat_confection}
            )
            cat_tissus, _ = Category.objects.get_or_create(tenant=tenant, name="Tissus")

            # --- Attributs / valeurs generateurs de variantes ----------------
            attr_couleur, _ = Attribute.objects.get_or_create(tenant=tenant, name="Couleur")
            couleur_values = []
            for value in ["Rouge", "Bleu", "Vert"]:
                obj, _ = AttributeValue.objects.get_or_create(
                    tenant=tenant, attribute=attr_couleur, value=value
                )
                couleur_values.append(obj)

            attr_taille, _ = Attribute.objects.get_or_create(tenant=tenant, name="Taille")
            for value in ["S", "M", "L"]:
                AttributeValue.objects.get_or_create(
                    tenant=tenant, attribute=attr_taille, value=value
                )

            # --- Gamme 1 : T-shirt coton uni (2 attributs generateurs) -------
            tshirt_template, _ = ProductTemplate.objects.get_or_create(
                tenant=tenant,
                name="T-shirt coton uni",
                defaults={
                    "category": cat_tshirts,
                    "base_uom": pcs,
                    "base_price_mga": Decimal("15000"),
                },
            )
            if not tshirt_template.variants.exists():
                set_variant_attributes(tshirt_template, [attr_couleur.id, attr_taille.id])
                generate_variants(tshirt_template)

            # --- Gamme 2 : tissu coton (1 attribut generateur, fiche textile) -
            tissu_template, _ = ProductTemplate.objects.get_or_create(
                tenant=tenant,
                name="Tissu coton grammage moyen",
                defaults={
                    "category": cat_tissus,
                    "base_uom": m,
                    "base_price_mga": Decimal("8000"),
                },
            )
            if not tissu_template.variants.exists():
                set_variant_attributes(tissu_template, [attr_couleur.id])
                generate_variants(tissu_template)

            tissu_variant = tissu_template.variants.order_by("reference").first()
            TextileSpec.objects.get_or_create(
                tenant=tenant,
                variant=tissu_variant,
                defaults={
                    "material": "Coton 100%",
                    "composition": {"coton": 100},
                    "weight_gsm": Decimal("180.00"),
                    "width_cm": Decimal("150.00"),
                    "certifications": ["OEKO-TEX100"],
                },
            )

            # --- Liste de prix par defaut -------------------------------------
            default_price_list, _ = PriceList.objects.get_or_create(
                tenant=tenant, name="Liste de prix par defaut", kind=PriceList.KIND_DEFAULT
            )
            for variant in tshirt_template.variants.all()[:3]:
                PriceListItem.objects.get_or_create(
                    tenant=tenant,
                    price_list=default_price_list,
                    variant=variant,
                    defaults={"price_mga": Decimal("16500")},
                )

            # --- Conditionnement -----------------------------------------------
            tshirt_variant = tshirt_template.variants.order_by("reference").first()
            Packaging.objects.get_or_create(
                tenant=tenant,
                variant=tshirt_variant,
                uom=pcs,
                defaults={"unit_count": 12, "barcode": "3000000000012"},
            )

            # --- Norme + certification -----------------------------------------
            standard, _ = CatalogStandard.objects.get_or_create(
                tenant=tenant,
                code="OEKO-TEX100",
                defaults={
                    "name": "OEKO-TEX Standard 100",
                    "description": "Absence de substances nocives pour la sante.",
                },
            )
            CatalogCertification.objects.get_or_create(
                tenant=tenant,
                variant=tissu_variant,
                standard=standard,
                defaults={
                    "valid_from": dt.date(2026, 1, 1),
                    "valid_until": dt.date(2027, 12, 31),
                },
            )

            templates_count = ProductTemplate.objects.filter(tenant=tenant).count()

        self.stdout.write(
            self.style.SUCCESS(
                f"catalog seed OK — tenant={tenant.code} gammes={templates_count} "
                f"utilisateur_demo={DEMO_USER_EMAIL} (role admin)"
            )
        )
