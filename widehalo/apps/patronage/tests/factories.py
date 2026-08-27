"""Factories factory_boy pour les modeles du module `patronage` — une par
modele concret (couche T1 du plan de durcissement, CDC §14 couches).

`tenant` est resolu via un `SubFactory` a chemin pointe vers
`apps.core.tests.factories.TenantFactory` (resolution paresseuse,
fonctionne meme si ce module est ecrit en parallele par un autre agent).

`PatTechPack.document` pointe vers `core.Document` : plutot que de dependre
d'un `DocumentFactory` partage (pas garanti d'exister/etre stable pendant
que `apps/core/tests/factories.py` est ecrit en parallele), on instancie ici
un `Document` minimal directement — c'est le seul modele hors-app requis
par ce lot de factories, et `core.models.document.Document` (import de
modele, pas de fichier core) est stable."""

from __future__ import annotations

import uuid

import factory

from apps.core.models.document import Document
from apps.patronage.models import (
    PatConsumption,
    PatGradingRule,
    PatMarker,
    PatMeasurementPoint,
    PatPattern,
    PatPatternPiece,
    PatPieceGeometry,
    PatPieceMeasure,
    PatSizeChart,
    PatSizeChartValue,
    PatTechPack,
)


class PatSizeChartFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PatSizeChart

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"SC{n}")
    name = factory.Sequence(lambda n: f"Grille de tailles {n}")
    garment_type = PatSizeChart.GARMENT_SHIRT
    sizes = ["XS", "S", "M", "L", "XL"]
    base_size = "M"


class PatMeasurementPointFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PatMeasurementPoint

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"MP{n}")
    name = factory.Sequence(lambda n: f"Point de mesure {n}")


class PatSizeChartValueFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PatSizeChartValue

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    size_chart = factory.SubFactory(PatSizeChartFactory, tenant=factory.SelfAttribute("..tenant"))
    measurement_point = factory.SubFactory(
        PatMeasurementPointFactory, tenant=factory.SelfAttribute("..tenant")
    )
    size = "M"
    value = 50


class PatGradingRuleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PatGradingRule

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    size_chart = factory.SubFactory(PatSizeChartFactory, tenant=factory.SelfAttribute("..tenant"))
    measurement_point = factory.SubFactory(
        PatMeasurementPointFactory, tenant=factory.SelfAttribute("..tenant")
    )
    mode = PatGradingRule.MODE_FIXED
    value = 1
    from_size = "S"
    to_size = "M"


class PatPatternFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PatPattern

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"PAT{n}")
    name = factory.Sequence(lambda n: f"Patron {n}")
    size_chart = factory.SubFactory(PatSizeChartFactory, tenant=factory.SelfAttribute("..tenant"))
    # `state` reste "draft" (valeur par defaut) — RG-PAT-6 (figeage a la
    # validation) est gere par `patronage.services`, jamais par une factory.


class PatPatternPieceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PatPatternPiece

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    pattern = factory.SubFactory(PatPatternFactory, tenant=factory.SelfAttribute("..tenant"))
    code = factory.Sequence(lambda n: f"PC{n}")
    name = factory.Sequence(lambda n: f"Piece {n}")


class PatPieceGeometryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PatPieceGeometry

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    piece = factory.SubFactory(PatPatternPieceFactory, tenant=factory.SelfAttribute("..tenant"))
    size = "M"


class PatPieceMeasureFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PatPieceMeasure

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    piece = factory.SubFactory(PatPatternPieceFactory, tenant=factory.SelfAttribute("..tenant"))
    measurement_point = factory.SubFactory(
        PatMeasurementPointFactory, tenant=factory.SelfAttribute("..tenant")
    )
    size = "M"
    value = 50


class PatConsumptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PatConsumption

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    pattern = factory.SubFactory(PatPatternFactory, tenant=factory.SelfAttribute("..tenant"))
    size = "M"
    material_variant_id = factory.LazyFunction(uuid.uuid4)
    width_cm = 150


class PatMarkerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PatMarker

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    pattern = factory.SubFactory(PatPatternFactory, tenant=factory.SelfAttribute("..tenant"))
    fabric_width_cm = 150
    size_ratio = factory.LazyFunction(lambda: {"S": 2, "M": 3, "L": 3})


class DocumentFactory(factory.django.DjangoModelFactory):
    """Minimal, local (pas partage) : `PatTechPack.document` est le seul
    besoin de `core.Document` de ce lot de factories."""

    class Meta:
        model = Document

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    file = factory.django.FileField(filename="tech_pack.pdf", data=b"%PDF-1.4 dossier technique")
    original_name = "tech_pack.pdf"
    mime_type = "application/pdf"
    sha256 = factory.Sequence(lambda n: f"{n:0>64}")


class PatTechPackFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PatTechPack

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    pattern = factory.SubFactory(PatPatternFactory, tenant=factory.SelfAttribute("..tenant"))
    version = 1
    document = factory.SubFactory(DocumentFactory, tenant=factory.SelfAttribute("..tenant"))
