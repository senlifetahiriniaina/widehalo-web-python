"""Jeu de demonstration `patronage` (T10, couche 14 CDC — TST-3) : une
grille de tailles avec points de mesure + valeurs, une regle de gradation,
un patron avec une piece + geometrie generee (gabarit parametrique, cf.
`services/patterns.py`) pour chaque taille de la grille, une consommation
calculee + un plan de coupe (marker), et le patron valide
(`services.patterns.validate_pattern` — RG-PAT-6, fige le patron).

**Idempotence** : referentiel (grille/points de mesure/valeurs/regle) par
`get_or_create` sur cle naturelle. Le patron est recupere par son `code`
au sein du tenant (pas de contrainte unique en base, mais un seul jeu de
demo est cree par cette commande) ; ses pieces/geometries/consommations
utilisent deja `update_or_create`/verification d'existence cote service ou
ici, donc un second passage ne duplique rien. La validation
(`validate_pattern`) n'est rejouee que si le patron est encore en
brouillon.

Peut etre lance seul (cree son propre tenant/utilisateur via
`get_or_create` si `seed_core` n'a pas ete execute d'abord)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandParser

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.rbac_policy import sync_group_permissions
from apps.core.tenant_context import activate_tenant
from apps.patronage.models import (
    PatGradingRule,
    PatMeasurementPoint,
    PatPattern,
    PatSizeChart,
    PatSizeChartValue,
)
from apps.patronage.services.consumption import compute_consumption, compute_marker
from apps.patronage.services.grading import apply_grading
from apps.patronage.services.patterns import (
    add_pattern_piece,
    create_pattern,
    generate_piece_geometry,
    validate_pattern,
)

DEMO_MATERIAL_VARIANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000d01")


class Command(BaseCommand):
    help = (
        "Jeu de demonstration patronage (grille de tailles, gradation, patron valide, "
        "consommation, plan de coupe) — prealable Schemathesis (T10)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant-code", default="DEMO")

    def handle(self, *args, **options) -> None:
        tenant_code = options["tenant_code"]

        tenant, _ = Tenant.objects.get_or_create(
            code=tenant_code, defaults={"name": "WideHalo Demo", "country_code": "MG"}
        )

        with activate_tenant(tenant.id):
            self._seed(tenant, tenant_code)

    def _seed(self, tenant: Tenant, tenant_code: str) -> None:
        user, was_created = User.objects.get_or_create(
            email=f"demo.production@{tenant_code.lower()}.widehalo.local",
            defaults={"is_staff": False, "is_superuser": False},
        )
        if was_created:
            user.set_password("Str0ngPassw0rd!23")
            user.save(update_fields=["password"])
        group, _ = Group.objects.get_or_create(name="resp_production")
        sync_group_permissions(group, "resp_production")
        user.groups.add(group)

        size_chart, _ = PatSizeChart.objects.get_or_create(
            tenant=tenant,
            code="SC-CHEMISE",
            defaults={
                "name": "Grille de tailles chemise homme",
                "garment_type": PatSizeChart.GARMENT_SHIRT,
                "sizes": ["S", "M", "L"],
                "base_size": "M",
            },
        )

        mp_poitrine, _ = PatMeasurementPoint.objects.get_or_create(
            tenant=tenant,
            code="tour_poitrine",
            defaults={
                "name": "Tour de poitrine",
                "category": PatMeasurementPoint.CATEGORY_CIRCUMFERENCE,
            },
        )
        mp_longueur, _ = PatMeasurementPoint.objects.get_or_create(
            tenant=tenant,
            code="longueur",
            defaults={"name": "Longueur", "category": PatMeasurementPoint.CATEGORY_LENGTH},
        )

        PatSizeChartValue.objects.get_or_create(
            tenant=tenant,
            size_chart=size_chart,
            measurement_point=mp_poitrine,
            size="M",
            defaults={"value": Decimal(100)},
        )
        PatSizeChartValue.objects.get_or_create(
            tenant=tenant,
            size_chart=size_chart,
            measurement_point=mp_longueur,
            size="M",
            defaults={"value": Decimal(70)},
        )

        PatGradingRule.objects.get_or_create(
            tenant=tenant,
            size_chart=size_chart,
            measurement_point=mp_poitrine,
            from_size="M",
            to_size="L",
            defaults={"mode": PatGradingRule.MODE_FIXED, "value": Decimal(4)},
        )
        PatGradingRule.objects.get_or_create(
            tenant=tenant,
            size_chart=size_chart,
            measurement_point=mp_longueur,
            from_size="M",
            to_size="L",
            defaults={"mode": PatGradingRule.MODE_FIXED, "value": Decimal(2)},
        )

        pattern = PatPattern.objects.filter(tenant=tenant, code="PAT-CHEMISE-DEMO").first()
        if pattern is None:
            pattern = create_pattern(
                tenant=tenant,
                code="PAT-CHEMISE-DEMO",
                name="Chemise homme demo",
                size_chart=size_chart,
            )

        piece = pattern.pieces.filter(code="devant").first()
        if piece is None:
            piece = add_pattern_piece(
                pattern,
                code="devant",
                name="Devant",
                material_variant_id=DEMO_MATERIAL_VARIANT_ID,
            )

        graded = apply_grading(size_chart)
        for size in size_chart.sizes:
            generate_piece_geometry(
                piece,
                size=size,
                graded_measurements={
                    "tour_poitrine": graded["tour_poitrine"][size],
                    "longueur": graded["longueur"][size],
                },
            )

        compute_consumption(
            pattern, size="M", material_variant_id=DEMO_MATERIAL_VARIANT_ID, width_cm=Decimal(150)
        )

        if not pattern.markers.exists():
            compute_marker(
                pattern,
                material_variant_id=DEMO_MATERIAL_VARIANT_ID,
                fabric_width_cm=Decimal(150),
                size_ratio={"S": 2, "M": 3, "L": 3},
                efficiency_pct=Decimal(85),
            )

        if pattern.state == PatPattern.STATE_DRAFT:
            validate_pattern(pattern)

        self.stdout.write(
            self.style.SUCCESS(
                f"patronage: grille={size_chart.code}, patron={pattern.code} "
                f"(etat={pattern.state}), {pattern.pieces.count()} piece(s), "
                f"{pattern.consumptions.count()} consommation(s), "
                f"{pattern.markers.count()} marker(s)."
            )
        )
