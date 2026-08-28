"""Import de gammes produit (`ProductTemplate` + variantes generees +
specification textile optionnelle) depuis un fichier xlsx fourni par
l'utilisateur — meme idiome que
`apps.accounting.services.chart_of_accounts_import` (alias d'en-tetes,
version de format, validation a blanc avant ecriture).

**Une ligne = un gabarit produit** (`template_code`/`template_name`/
`category`/`uom`), avec au plus 2 paires `attribut=valeur` dans
`variant_attributes` qui amorcent les attributs generateurs de variantes
du gabarit (`Attribute`/`AttributeValue`, crees si absents) — la
generation effective des variantes est deleguee integralement a
`apps.catalog.services.variants.generate_variants` (jamais reimplementee
ici), qui applique deja le plafond de 50 combinaisons (RG catalogue).

**Choix "tout ou rien"** : comme le plan comptable (§2 de
docs/IMPORT_FORMATS.md), pas de file d'anomalies — un gabarit produit n'a
pas de notion de "corriger plus tard" comparable a une caisse ou un
compte inconnu du journal de tresorerie : soit la ligne est valide (UOM
existante, categorie resolue/creee, attributs bien formes, plafond de
variantes respecte), soit elle doit etre corrigee dans le fichier source.
Idempotent par `template_code` (-> `ProductTemplate.reference`) : un code
deja utilise par ce tenant est ignore (jamais ecrase, ni ses variantes
regenerees), meme discipline que le plan comptable.

**`uom` obligatoire et doit deja exister** (`ProductTemplate.base_uom` est
une FK non nullable) : un code d'UOM inconnu produit une erreur de ligne
explicite, jamais une creation automatique d'unite de mesure (une unite de
mesure engage des conversions/`UnitConversion` que l'import n'a pas a
deviner). **`category` est creee a la volee si absente** (simple
classification par nom, sans code ni hierarchie a resoudre — contrairement
a l'UOM, une categorie manquante n'est pas une ambiguite metier)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.catalog.models import (
    MAX_VARIANT_GENERATING_ATTRIBUTES,
    Attribute,
    AttributeValue,
    Category,
    ProductTemplate,
    TextileSpec,
    UnitOfMeasure,
)
from apps.catalog.services.variants import generate_variants, set_variant_attributes
from apps.core.models.tenant import Tenant
from apps.core.services.import_wizard import RowError
from apps.core.services.import_xlsx import fold_header, read_xlsx_rows

CATALOG_FORMAT_VERSION = 1

CATALOG_HEADER_ALIASES: dict[str, set[str]] = {
    "template_code": {"TEMPLATE_CODE", "CODE"},
    "template_name": {"TEMPLATE_NAME", "NOM", "NAME"},
    "category": {"CATEGORY", "CATEGORIE"},
    "uom": {"UOM", "UNITE", "UNITE DE MESURE"},
    "variant_attributes": {"VARIANT_ATTRIBUTES", "ATTRIBUTS DE VARIANTES", "ATTRIBUTS"},
    "material": {"MATERIAL", "MATIERE"},
    "composition": {"COMPOSITION"},
    "weight_gsm": {"WEIGHT_GSM", "GRAMMAGE"},
    "width_cm": {"WIDTH_CM", "LAIZE"},
}


@dataclass
class CatalogImportSummary:
    total_rows: int
    created_count: int = 0
    skipped_existing_count: int = 0
    variants_created_count: int = 0
    textile_specs_created_count: int = 0
    row_errors: list[RowError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.row_errors


def _resolve_header_index(header: list[str]) -> dict[str, int]:
    normalized = [fold_header(cell) for cell in header]
    resolved: dict[str, int] = {}
    for field_name, aliases in CATALOG_HEADER_ALIASES.items():
        folded_aliases = {fold_header(alias) for alias in aliases}
        for index, cell in enumerate(normalized):
            if cell in folded_aliases:
                resolved[field_name] = index
                break
    return resolved


def _parse_variant_attributes(raw: Any) -> list[tuple[str, str]]:
    """`attribut=valeur;attribut2=valeur2` -> liste de paires ordonnees.
    Ne deduplique pas les noms d'attribut ici (fait par l'appelant, qui a
    besoin de compter les attributs DISTINCTS pour la garde du plafond)."""
    if not raw:
        return []
    pairs: list[tuple[str, str]] = []
    for token in str(raw).split(";"):
        token = token.strip()
        if not token:
            continue
        if "=" not in token:
            continue
        attr_name, _, value = token.partition("=")
        attr_name, value = attr_name.strip(), value.strip()
        if attr_name and value:
            pairs.append((attr_name, value))
    return pairs


def _normalize_row(row: list[Any], index_by_field: dict[str, int]) -> dict[str, Any]:
    def get(field_name: str) -> Any:
        index = index_by_field.get(field_name)
        if index is None or index >= len(row):
            return None
        value = row[index]
        return value.strip() if isinstance(value, str) else value

    def to_decimal(value: Any) -> Decimal | None:
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None

    return {
        "template_code": str(get("template_code") or "").strip(),
        "template_name": str(get("template_name") or "").strip(),
        "category": str(get("category") or "").strip(),
        "uom": str(get("uom") or "").strip(),
        "variant_attributes": _parse_variant_attributes(get("variant_attributes")),
        "material": str(get("material") or "").strip(),
        "composition": str(get("composition") or "").strip(),
        "weight_gsm": to_decimal(get("weight_gsm")),
        "width_cm": to_decimal(get("width_cm")),
    }


def import_catalog_xlsx(
    tenant: Tenant, file_bytes: bytes, *, filename: str = "", format_version: int | None = None
) -> CatalogImportSummary:
    if format_version is not None and format_version > CATALOG_FORMAT_VERSION:
        raise ValueError(
            f"Format d'import de catalogue v{format_version} non supporté "
            f"(version maximale supportée : v{CATALOG_FORMAT_VERSION}) — "
            "mettez à jour l'application avant de réimporter ce fichier."
        )

    header, data_rows = read_xlsx_rows(file_bytes)
    index_by_field = _resolve_header_index(header)
    normalized_rows = [_normalize_row(row, index_by_field) for row in data_rows]

    summary = CatalogImportSummary(total_rows=len(normalized_rows))
    existing_codes = set(
        ProductTemplate.objects.filter(tenant=tenant)
        .exclude(reference="")
        .values_list("reference", flat=True)
    )

    # Tout-ou-rien : chaque ligne est ecrite au fil de l'eau dans UNE seule
    # transaction ; la premiere erreur (validation de champ ou plafond de
    # variantes depasse, cf. `generate_variants`) annule tout le lot via
    # `transaction.set_rollback` plutot qu'une exception qui remonterait
    # jusqu'a l'appelant — meme resultat observable que `commit_import()`
    # (rien n'est enregistre en cas d'echec), mais permet de renvoyer un
    # `row_errors` detaille comme le reste des imports de ce chantier,
    # plutot que la simple exception generique de `commit_import`.
    with transaction.atomic():
        for row_index, entry in enumerate(normalized_rows):
            code = entry["template_code"]
            if code and code in existing_codes:
                summary.skipped_existing_count += 1
                continue

            errors: dict[str, list[str]] = {}
            if not entry["template_name"]:
                errors.setdefault("template_name", []).append("Ce champ est obligatoire.")

            uom = None
            if not entry["uom"]:
                errors.setdefault("uom", []).append("Ce champ est obligatoire.")
            else:
                uom = UnitOfMeasure.objects.filter(tenant=tenant, code=entry["uom"]).first()
                if uom is None:
                    errors.setdefault("uom", []).append(
                        f"Unité de mesure « {entry['uom']} » inconnue."
                    )

            attribute_names = {name for name, _value in entry["variant_attributes"]}
            if len(attribute_names) > MAX_VARIANT_GENERATING_ATTRIBUTES:
                errors.setdefault("variant_attributes", []).append(
                    f"Au maximum {MAX_VARIANT_GENERATING_ATTRIBUTES} attributs générateurs "
                    "de variantes par gamme."
                )

            if errors:
                summary.row_errors.append(RowError(row_index=row_index, errors=errors))
                transaction.set_rollback(True)
                return summary

            assert uom is not None  # garanti par la garde ci-dessus

            category = None
            if entry["category"]:
                category, _created = Category.objects.get_or_create(
                    tenant=tenant, name=entry["category"]
                )

            template = ProductTemplate.objects.create(
                tenant=tenant,
                reference=code,
                name=entry["template_name"],
                category=category,
                base_uom=uom,
            )
            if code:
                existing_codes.add(code)
            summary.created_count += 1

            attribute_ids: list[Any] = []
            for attr_name, value in entry["variant_attributes"]:
                attribute, _created = Attribute.objects.get_or_create(tenant=tenant, name=attr_name)
                AttributeValue.objects.get_or_create(
                    tenant=tenant, attribute=attribute, value=value
                )
                if attribute.id not in attribute_ids:
                    attribute_ids.append(attribute.id)

            if attribute_ids:
                try:
                    set_variant_attributes(template, attribute_ids)
                    variants = generate_variants(template)
                except ValidationError as exc:
                    summary.row_errors.append(
                        RowError(row_index=row_index, errors={"variant_attributes": exc.messages})
                    )
                    transaction.set_rollback(True)
                    return summary
                summary.variants_created_count += len(variants)

                if (
                    entry["material"]
                    or entry["composition"]
                    or entry["weight_gsm"]
                    or entry["width_cm"]
                ):
                    composition = (
                        {"description": entry["composition"]} if entry["composition"] else {}
                    )
                    for variant in variants:
                        TextileSpec.objects.create(
                            tenant=tenant,
                            variant=variant,
                            material=entry["material"],
                            composition=composition,
                            weight_gsm=entry["weight_gsm"],
                            width_cm=entry["width_cm"],
                        )
                        summary.textile_specs_created_count += 1

    return summary
