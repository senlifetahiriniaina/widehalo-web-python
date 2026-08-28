"""Import du referentiel partenaires depuis un fichier xlsx fourni par
l'utilisateur — meme idiome que
`apps.accounting.services.chart_of_accounts_import` (lecture/alias
d'en-tetes, validation a blanc via `apps.core.services.import_wizard`,
version de format).

**Choix "tout ou rien" (pas de file d'anomalies)** : contrairement a
`cash_journal_import` (une ligne en anomalie n'empeche jamais les autres
d'etre importees, parce qu'un compte/une caisse peut manquer sans qu'il y
ait de notion de "corriger plus tard" evidente cote utilisateur), un
partenaire n'a pas ce meme besoin de resolution differee : soit la ligne
est structurellement valide (nom present, roles reconnus, NIF bien forme),
soit elle doit etre corrigee dans le fichier source et reimportee — il n'y
a pas de reference externe (compte comptable, caisse) a resoudre qui
justifierait une file d'attente separee. Meme discipline "validation a
blanc puis ecriture" que le plan comptable (§2 de docs/IMPORT_FORMATS.md),
PAS `commit_import()` (tout-ou-rien generique) car l'import reste
idempotent par `code` (colonne facultative -> `Partner.reference`), a
l'image de l'import de plan comptable : un code deja utilise par ce tenant
est ignore (jamais ecrase), pour permettre de reimporter un fichier mis a
jour sans dupliquer les partenaires deja crees.

**Detection de doublon NIF non bloquante** : reprend exactement la logique
de `apps.partners.services.onboarding.create_partner` (une `DuplicateAlert`
est journalisee, jamais un blocage de la creation) — l'import ne doit pas
se comporter differemment de la creation manuelle sur ce point.

**Coordonnees (`email`/`phone`/`address`)** : colonnes acceptees (pour
compatibilite avec le format deja documente dans
`docs/IMPORT_FORMATS.md` avant ce chantier) mais **non persistees** —
`apps.partners.models.Partner` ne porte aujourd'hui aucun champ
coordonnees (pas de modele `Contact`/`Adresse` dans ce module). Plutot que
d'inventer un modele hors perimetre de cette tache, ces colonnes sont
lues sans erreur (compatibilite ascendante d'un fichier qui les
renseignerait) mais explicitement ignorees — signale dans le resume
d'import (`coordinates_ignored_count`) plutot que silencieusement perdu
sans aucune trace."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.core.models.tenant import Tenant
from apps.core.services.import_wizard import RowError, dry_run_validate
from apps.core.services.import_xlsx import fold_header, read_xlsx_rows
from apps.core.services.sequences import next_reference
from apps.partners.models import DuplicateAlert, Partner

PARTNER_FORMAT_VERSION = 1

PARTNER_HEADER_ALIASES: dict[str, set[str]] = {
    "code": {"CODE"},
    "name": {"NAME", "NOM", "RAISON SOCIALE"},
    "nif": {"NIF"},
    "roles": {"ROLES", "ROLE"},
    "credit_limit_mga": {"CREDIT_LIMIT_MGA", "PLAFOND DE CREDIT", "LIMITE DE CREDIT"},
    "email": {"EMAIL"},
    "phone": {"PHONE", "TELEPHONE"},
    "address": {"ADDRESS", "ADRESSE"},
}

# Libelles de role acceptes (francais, cf. docs/IMPORT_FORMATS.md) ->
# valeur canonique `Partner.ROLE_CHOICES`. Les codes canoniques eux-memes
# (deja en anglais dans le modele) sont acceptes en repli pour ne jamais
# bloquer un fichier qui les utiliserait directement. Toute valeur absente
# de cette table n'est PAS devinee : elle est laissee telle quelle, ce qui
# fait naturellement echouer la validation ArrayField/choices (row error
# explicite), jamais une resolution silencieuse.
ROLE_LABEL_TO_CODE: dict[str, str] = {
    "CLIENT": Partner.ROLE_CLIENT,
    "FOURNISSEUR": Partner.ROLE_SUPPLIER,
    "TRANSPORTEUR": Partner.ROLE_CARRIER,
    "SOUS_TRAITANT": Partner.ROLE_SUBCONTRACTOR,
    "SUPPLIER": Partner.ROLE_SUPPLIER,
    "CARRIER": Partner.ROLE_CARRIER,
    "SUBCONTRACTOR": Partner.ROLE_SUBCONTRACTOR,
}


@dataclass
class PartnerImportSummary:
    total_rows: int
    created_count: int = 0
    skipped_existing_count: int = 0
    duplicate_alerts_count: int = 0
    coordinates_ignored_count: int = 0
    row_errors: list[RowError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.row_errors


def _resolve_header_index(header: list[str]) -> dict[str, int]:
    normalized = [fold_header(cell) for cell in header]
    resolved: dict[str, int] = {}
    for field_name, aliases in PARTNER_HEADER_ALIASES.items():
        folded_aliases = {fold_header(alias) for alias in aliases}
        for index, cell in enumerate(normalized):
            if cell in folded_aliases:
                resolved[field_name] = index
                break
    return resolved


def _parse_roles(raw: Any) -> list[str]:
    if not raw:
        return []
    tokens = [token.strip() for token in str(raw).split(";") if token.strip()]
    resolved: list[str] = []
    for token in tokens:
        code = ROLE_LABEL_TO_CODE.get(fold_header(token), token)
        if code not in resolved:
            resolved.append(code)
    return resolved


def _normalize_row(row: list[Any], index_by_field: dict[str, int]) -> dict[str, Any]:
    def get(field_name: str) -> Any:
        index = index_by_field.get(field_name)
        if index is None or index >= len(row):
            return None
        value = row[index]
        return value.strip() if isinstance(value, str) else value

    def to_decimal(value: Any) -> Decimal:
        if value in (None, ""):
            return Decimal(0)
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return Decimal(0)

    return {
        "code": str(get("code") or "").strip(),
        "name": str(get("name") or "").strip(),
        "nif": str(get("nif") or "").strip(),
        "roles": _parse_roles(get("roles")),
        "credit_limit_mga": to_decimal(get("credit_limit_mga")),
        "email": str(get("email") or "").strip(),
        "phone": str(get("phone") or "").strip(),
        "address": str(get("address") or "").strip(),
    }


def import_partners_xlsx(
    tenant: Tenant, file_bytes: bytes, *, filename: str = "", format_version: int | None = None
) -> PartnerImportSummary:
    if format_version is not None and format_version > PARTNER_FORMAT_VERSION:
        raise ValueError(
            f"Format d'import de partenaires v{format_version} non supporté "
            f"(version maximale supportée : v{PARTNER_FORMAT_VERSION}) — "
            "mettez à jour l'application avant de réimporter ce fichier."
        )

    header, data_rows = read_xlsx_rows(file_bytes)
    index_by_field = _resolve_header_index(header)
    normalized_rows = [_normalize_row(row, index_by_field) for row in data_rows]

    # Validation structurelle a blanc (full_clean, rien d'ecrit) — meme
    # mecanisme generique que le plan comptable. `reference` n'est
    # renseignee ici que si `code` a ete fourni (sinon vide -> sequence
    # generee au commit, jamais validee a blanc contre une valeur qui n'est
    # pas encore connue).
    index_to_field = {0: "reference", 1: "name", 2: "nif", 3: "roles", 4: "credit_limit_mga"}
    validation_rows = [
        [entry["code"], entry["name"], entry["nif"], entry["roles"], entry["credit_limit_mga"]]
        for entry in normalized_rows
    ]
    dry_run = dry_run_validate(Partner, validation_rows, index_to_field, tenant=tenant)

    summary = PartnerImportSummary(total_rows=len(normalized_rows), row_errors=dry_run.errors)
    if not dry_run.is_valid:
        return summary

    existing_codes = set(
        Partner.objects.filter(tenant=tenant)
        .exclude(reference="")
        .values_list("reference", flat=True)
    )

    for entry in normalized_rows:
        if entry["email"] or entry["phone"] or entry["address"]:
            summary.coordinates_ignored_count += 1

        code = entry["code"]
        if code and code in existing_codes:
            summary.skipped_existing_count += 1
            continue

        reference = code or next_reference(tenant, "PART", _current_year())
        partner = Partner.objects.create(
            tenant=tenant,
            reference=reference,
            name=entry["name"],
            roles=entry["roles"],
            nif=entry["nif"],
            credit_limit_mga=entry["credit_limit_mga"],
        )
        if code:
            existing_codes.add(code)
        summary.created_count += 1

        if entry["nif"]:
            existing_matches = Partner.objects.filter(tenant=tenant, nif=entry["nif"]).exclude(
                pk=partner.pk
            )
            for match in existing_matches:
                DuplicateAlert.objects.create(
                    tenant=tenant, partner=partner, duplicate_of=match, matched_field="nif"
                )
                summary.duplicate_alerts_count += 1

    return summary


def _current_year() -> int:
    from django.utils import timezone

    year: int = timezone.now().year
    return year
