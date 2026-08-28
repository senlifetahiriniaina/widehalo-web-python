"""Import du plan comptable d'un tenant depuis un fichier xlsx fourni par
l'utilisateur — a distinguer de `chart_of_accounts.py::load_pcg2005()`
(chargement du plan comptable GENERIQUE PCG 2005 depuis la fixture interne
du depot). Ce module importe le plan comptable ADAPTE d'une entreprise
donnee, potentiellement different du generique (comptes supplementaires,
categories de caisse propres), depuis un fichier que l'utilisateur televerse.

Reutilise `apps.core.services.import_wizard` pour la phase de validation
(deja construit, jamais branche jusqu'ici) mais PAS pour le commit : celui-ci
(`commit_import`) est tout-ou-rien et sans deduplication, alors que le plan
comptable doit rester idempotent par code — memes principe/format que
`load_pcg2005` (un code deja present pour ce tenant est ignore, jamais
ecrase), pour permettre de reimporter un fichier mis a jour sans dupliquer
les comptes deja crees manuellement entre-temps.

Format documente dans `docs/IMPORT_FORMATS.md` — reserve OECFM identique a
celle deja portee par tout le module `accounting` : un plan comptable
importe depuis un fichier utilisateur n'est pas plus valide par un
expert-comptable que la fixture PCG2005 elle-meme."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apps.accounting.models import AccAccount, AccCashCategoryMapping
from apps.core.models.tenant import Tenant
from apps.core.services.import_wizard import RowError, dry_run_validate
from apps.core.services.import_xlsx import fold_header, read_xlsx_rows

CHART_OF_ACCOUNTS_FORMAT_VERSION = 1

# Table d'alias d'en-tetes (cf. docs/IMPORT_FORMATS.md, section
# "Compatibilite ascendante") : chaque champ canonique accepte plusieurs
# libelles de colonne, dont ceux du fichier reel fourni comme reference.
CHART_OF_ACCOUNTS_HEADER_ALIASES: dict[str, set[str]] = {
    "code": {"CODE", "N° DE COMPTE", "N° DE COMPTE PROPOSE"},
    "name": {"NAME", "INTITULE", "INTITULE DU COMPTE (PCG 2005)"},
    "account_class": {"ACCOUNT_CLASS", "CLASSE", "CLASSE PCG"},
    "type": {"TYPE"},
    "nature": {"NATURE"},
    "categorie_caisse": {"CATEGORIE_CAISSE", "CATEGORIE DE CAISSE LIFE MDG", "CATEGORIE DE CAISSE"},
}

# Correspondance approximative "Nature" (libelle francais descriptif du
# fichier reel fourni, pas une valeur canonique de l'application) ->
# `AccAccount.TYPE_CHOICES` — best-effort documente, jamais une supposition
# silencieuse : toute valeur absente de cette table doit etre corrigee par
# l'utilisateur (colonne `type` explicite) plutot que devinee. Cles deja
# normalisees via `_fold()` (majuscules, sans accent) — comparees ainsi a la
# lecture, cf. `_normalize_row`.
NATURE_TO_TYPE: dict[str, str] = {
    "ACTIF IMMOBILISE": AccAccount.TYPE_ASSET,
    "ACTIF (TIERS)": AccAccount.TYPE_RECEIVABLE,
    "PASSIF FINANCIER": AccAccount.TYPE_LIABILITY,
    "PASSIF (TIERS)": AccAccount.TYPE_PAYABLE,
    "TRESORERIE": AccAccount.TYPE_CASH,
    "CHARGE": AccAccount.TYPE_EXPENSE,
    "CHARGE FINANCIERE": AccAccount.TYPE_EXPENSE,
    "PRODUIT": AccAccount.TYPE_INCOME,
    "PRODUIT (CONTRA)": AccAccount.TYPE_INCOME,
}


@dataclass
class ChartImportSummary:
    total_rows: int
    created_count: int = 0
    skipped_existing_count: int = 0
    category_mappings_count: int = 0
    row_errors: list[RowError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.row_errors


def _resolve_header_index(header: list[str]) -> dict[str, int]:
    """Associe chaque champ canonique a l'index de la colonne correspondante
    dans le fichier source, via la table d'alias — insensible a la casse,
    aux accents et aux espaces superflus."""
    normalized = [fold_header(cell) for cell in header]
    resolved: dict[str, int] = {}
    for field_name, aliases in CHART_OF_ACCOUNTS_HEADER_ALIASES.items():
        folded_aliases = {fold_header(alias) for alias in aliases}
        for index, cell in enumerate(normalized):
            if cell in folded_aliases:
                resolved[field_name] = index
                break
    return resolved


def _normalize_row(row: list[Any], index_by_field: dict[str, int]) -> dict[str, Any]:
    def get(field_name: str) -> Any:
        index = index_by_field.get(field_name)
        if index is None or index >= len(row):
            return None
        value = row[index]
        return value.strip() if isinstance(value, str) else value

    resolved_type = get("type")
    if not resolved_type:
        nature = get("nature")
        if isinstance(nature, str):
            resolved_type = NATURE_TO_TYPE.get(fold_header(nature))

    return {
        "code": str(get("code") or "").strip(),
        "name": str(get("name") or "").strip(),
        "account_class": get("account_class"),
        "type": resolved_type,
        "categorie_caisse": get("categorie_caisse"),
    }


def import_chart_of_accounts_xlsx(
    tenant: Tenant, file_bytes: bytes, *, filename: str = "", format_version: int | None = None
) -> ChartImportSummary:
    if format_version is not None and format_version > CHART_OF_ACCOUNTS_FORMAT_VERSION:
        raise ValueError(
            f"Format d'import de plan comptable v{format_version} non supporté "
            f"(version maximale supportée : v{CHART_OF_ACCOUNTS_FORMAT_VERSION}) — "
            "mettez à jour l'application avant de réimporter ce fichier."
        )

    header, data_rows = read_xlsx_rows(file_bytes)
    index_by_field = _resolve_header_index(header)
    normalized_rows = [_normalize_row(row, index_by_field) for row in data_rows]

    # Validation structurelle via le mecanisme generique deja existant
    # (jamais branche avant ce chantier) : chaque ligne devient une instance
    # AccAccount non sauvegardee, validee par full_clean(). Mapping fige
    # directement en index (les colonnes source ont deja ete resolues par
    # `_resolve_header_index`/`_normalize_row` ci-dessus, `parse_mapping`
    # n'apporterait ici qu'une indirection sans valeur ajoutee).
    index_to_field = {0: "code", 1: "name", 2: "account_class", 3: "type"}
    validation_rows = [
        [entry["code"], entry["name"], entry["account_class"], entry["type"]]
        for entry in normalized_rows
    ]
    dry_run = dry_run_validate(AccAccount, validation_rows, index_to_field, tenant=tenant)

    summary = ChartImportSummary(total_rows=len(normalized_rows), row_errors=dry_run.errors)
    if not dry_run.is_valid:
        return summary

    existing_codes = set(AccAccount.objects.filter(tenant=tenant).values_list("code", flat=True))
    accounts_by_code: dict[str, AccAccount] = {}

    for entry in normalized_rows:
        code = entry["code"]
        if code in existing_codes:
            summary.skipped_existing_count += 1
            accounts_by_code[code] = AccAccount.objects.get(tenant=tenant, code=code)
            continue
        account = AccAccount.objects.create(
            tenant=tenant,
            code=code,
            name=entry["name"],
            account_class=entry["account_class"],
            type=entry["type"],
        )
        existing_codes.add(code)
        accounts_by_code[code] = account
        summary.created_count += 1

    for entry in normalized_rows:
        category_label = entry["categorie_caisse"]
        if not category_label:
            continue
        account = accounts_by_code[entry["code"]]
        AccCashCategoryMapping.objects.update_or_create(
            tenant=tenant,
            category_label=str(category_label).strip(),
            defaults={"account": account},
        )
        summary.category_mappings_count += 1

    return summary
