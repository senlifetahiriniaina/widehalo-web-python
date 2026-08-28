"""Import du journal de caisse (operations de tresorerie en especes) depuis
un fichier xlsx fourni par l'utilisateur. Chaque ligne source produit soit
une vraie ecriture comptable brouillon (`AccMove`, jamais postee
automatiquement — RG-ACC du module), soit une anomalie mise en attente de
resolution humaine explicite (`AccImportRow.status=anomaly`) — jamais de
resolution devinee, meme patron que le rapprochement bancaire assiste (A16,
`services/bank_reconciliation.py`).

Contrairement au fichier de reference qui a servi de specification a ce
format (colonne CAISSE unique par ligne, plusieurs caisses physiques
melangees dans le meme classeur), la caisse cible est resolue PAR LIGNE
(vers un `AccJournal` de type `TYPE_CASH` existant, par code ou nom,
insensible a la casse/aux accents) plutot que fixee une fois pour tout
l'import — une caisse non reconnue est une anomalie de ligne
(`CAISSE_INCONNUE`), jamais une creation automatique de journal."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.accounting.models import (
    AccAccount,
    AccCashCategoryMapping,
    AccImportBatch,
    AccImportRow,
    AccJournal,
    AccPeriod,
)
from apps.accounting.services.moves import add_line, create_draft_move
from apps.core.models.tenant import Tenant
from apps.core.services.import_xlsx import fold_header, read_xlsx_rows

CASH_JOURNAL_FORMAT_VERSION = 1

CASH_JOURNAL_HEADER_ALIASES: dict[str, set[str]] = {
    "date": {"DATE"},
    "date_estimee": {"DATE ESTIMEE"},
    "caisse": {"CAISSE"},
    "categorie": {"CATEGORIE"},
    "exclu_des_totaux": {"EXCLU DES TOTAUX (SOLDE PERIODE)", "EXCLU DES TOTAUX"},
    "compte_pcg": {"COMPTE PCG", "CODE PCG DETECTE"},
    "nature_origine": {"NATURE DORIGINE"},
    "type_piece": {"TYPE PIECE"},
    "partenaire": {"PARTENAIRE"},
    "client": {"CLIENT"},
    "fournisseur": {"FOURNISSEUR"},
    "libelle": {"LIBELLE"},
    "entree": {"ENTREE"},
    "sortie": {"SORTIE"},
}

# Anomalies de ligne — chaque code doit rester explicite et actionnable par
# l'utilisateur (jamais un code muet), cf. docs/IMPORT_FORMATS.md.
ANOMALY_MONTANT_ENTREE_ET_SORTIE = "MONTANT_ENTREE_ET_SORTIE"
ANOMALY_MONTANT_NUL = "MONTANT_NUL"
ANOMALY_DATE_MANQUANTE = "DATE_MANQUANTE"
ANOMALY_DATE_INVALIDE = "DATE_INVALIDE"
ANOMALY_PERIODE_INDISPONIBLE = "PERIODE_FERMEE_OU_INEXISTANTE"
ANOMALY_COMPTE_INCONNU = "COMPTE_INCONNU"
ANOMALY_CATEGORIE_NON_MAPPEE = "CATEGORIE_NON_MAPPEE"
ANOMALY_CAISSE_INCONNUE = "CAISSE_INCONNUE"

_MIN_DATE = dt.date(2000, 1, 1)


@dataclass
class CashJournalImportSummary:
    batch: AccImportBatch
    total_rows: int
    ok_count: int = 0
    anomaly_count: int = 0
    batch_warnings: list[str] = field(default_factory=list)


def _normalize_row(row: list[Any], index_by_field: dict[str, int]) -> dict[str, Any]:
    def get(field_name: str) -> Any:
        index = index_by_field.get(field_name)
        if index is None or index >= len(row):
            return None
        value = row[index]
        return value.strip() if isinstance(value, str) else value

    date_value = get("date")
    if isinstance(date_value, dt.datetime):
        date_value = date_value.date()

    def to_decimal(value: Any) -> Decimal:
        if value in (None, ""):
            return Decimal(0)
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return Decimal(0)

    return {
        "date": date_value if isinstance(date_value, dt.date) else None,
        "caisse": str(get("caisse") or "").strip(),
        "categorie": str(get("categorie") or "").strip(),
        "exclu_des_totaux": fold_header(str(get("exclu_des_totaux") or "")) == "OUI",
        "compte_pcg": str(get("compte_pcg") or "").strip(),
        "libelle": str(get("libelle") or "").strip(),
        "entree": to_decimal(get("entree")),
        "sortie": to_decimal(get("sortie")),
        # Champs purement informatifs (tracabilite `raw_data`) — jamais
        # utilises pour resoudre un compte/une caisse/une periode, jamais
        # rapproches d'un partenaire reel (aucune resolution devinee vers
        # `partners.Partner`, hors perimetre de ce chantier).
        "partenaire": str(get("partenaire") or "").strip(),
        "client": str(get("client") or "").strip(),
        "fournisseur": str(get("fournisseur") or "").strip(),
        "nature_origine": str(get("nature_origine") or "").strip(),
        "type_piece": str(get("type_piece") or "").strip(),
    }


def _resolve_account(
    tenant: Tenant, entry: dict[str, Any], category_mappings: dict[str, AccAccount]
) -> tuple[AccAccount | None, list[str]]:
    """RG import caisse : un compte explicite (colonne COMPTE PCG) prime
    toujours sur la resolution par categorie — jamais l'inverse, pour
    respecter un compte que l'utilisateur/sa comptabilite a deja identifie
    avec certitude."""
    if entry["compte_pcg"]:
        account = AccAccount.objects.filter(tenant=tenant, code=entry["compte_pcg"]).first()
        if account is None:
            return None, [ANOMALY_COMPTE_INCONNU]
        return account, []

    if entry["categorie"] in category_mappings:
        return category_mappings[entry["categorie"]], []

    return None, [ANOMALY_CATEGORIE_NON_MAPPEE]


def _resolve_journal(
    tenant: Tenant, caisse_label: str, journal_cache: dict[str, AccJournal | None]
) -> AccJournal | None:
    """Resout la caisse de la ligne vers un `AccJournal` de type `TYPE_CASH`
    existant (par code ou nom, insensible casse/accents) — renvoie `None`
    (donc `ANOMALY_CAISSE_INCONNUE`, cf. `_detect_row_anomalies`) si la
    caisse n'est pas reconnue OU si le journal trouve n'a pas de compte de
    caisse configure (`default_account`), sans quoi aucune ecriture ne
    pourrait de toute facon etre construite."""
    key = fold_header(caisse_label)
    if key in journal_cache:
        return journal_cache[key]

    journal = (
        AccJournal.objects.filter(tenant=tenant, type=AccJournal.TYPE_CASH)
        .filter(code__iexact=caisse_label)
        .first()
        or AccJournal.objects.filter(tenant=tenant, type=AccJournal.TYPE_CASH)
        .filter(name__iexact=caisse_label)
        .first()
    )
    if journal is not None and journal.default_account is None:
        journal = None
    journal_cache[key] = journal
    return journal


def _detect_row_anomalies(
    tenant: Tenant,
    entry: dict[str, Any],
    *,
    journal: AccJournal | None,
    account: AccAccount | None,
    account_anomalies: list[str],
    period: AccPeriod | None,
) -> list[str]:
    codes: list[str] = list(account_anomalies)

    if entry["entree"] > 0 and entry["sortie"] > 0:
        codes.append(ANOMALY_MONTANT_ENTREE_ET_SORTIE)
    elif entry["entree"] == 0 and entry["sortie"] == 0 and not entry["exclu_des_totaux"]:
        codes.append(ANOMALY_MONTANT_NUL)

    if entry["date"] is None:
        codes.append(ANOMALY_DATE_MANQUANTE)
    elif entry["date"] < _MIN_DATE or entry["date"] > dt.date.today() + dt.timedelta(days=366):
        codes.append(ANOMALY_DATE_INVALIDE)
    elif period is None:
        codes.append(ANOMALY_PERIODE_INDISPONIBLE)

    if journal is None:
        codes.append(ANOMALY_CAISSE_INCONNUE)

    return codes


def _create_move_for_row(
    tenant: Tenant,
    journal: AccJournal,
    period: AccPeriod,
    account: AccAccount,
    entry: dict[str, Any],
) -> Any:
    cash_account = journal.default_account
    assert cash_account is not None  # garanti par l'appelant (cf. _detect_row_anomalies)

    move = create_draft_move(
        tenant=tenant,
        journal=journal,
        period=period,
        date=entry["date"],
        narration=entry["libelle"],
    )
    if entry["entree"] > 0:
        add_line(move, account=cash_account, label=entry["libelle"], debit=entry["entree"])
        add_line(move, account=account, label=entry["libelle"], credit=entry["entree"])
    else:
        add_line(move, account=account, label=entry["libelle"], debit=entry["sortie"])
        add_line(move, account=cash_account, label=entry["libelle"], credit=entry["sortie"])
    return move


def import_cash_journal_xlsx(
    tenant: Tenant, file_bytes: bytes, *, filename: str = "", format_version: int | None = None
) -> CashJournalImportSummary:
    if format_version is not None and format_version > CASH_JOURNAL_FORMAT_VERSION:
        raise ValueError(
            f"Format d'import de journal de caisse v{format_version} non supporté "
            f"(version maximale supportée : v{CASH_JOURNAL_FORMAT_VERSION}) — "
            "mettez à jour l'application avant de réimporter ce fichier."
        )

    header, data_rows = read_xlsx_rows(file_bytes)
    normalized_header = [fold_header(cell) for cell in header]
    index_by_field: dict[str, int] = {}
    for field_name, aliases in CASH_JOURNAL_HEADER_ALIASES.items():
        folded_aliases = {fold_header(alias) for alias in aliases}
        for index, cell in enumerate(normalized_header):
            if cell in folded_aliases:
                index_by_field[field_name] = index
                break

    batch = AccImportBatch.objects.create(
        tenant=tenant,
        kind=AccImportBatch.KIND_CASH_JOURNAL,
        source_filename=filename,
        format_version=format_version or CASH_JOURNAL_FORMAT_VERSION,
        total_rows=len(data_rows),
    )

    category_mappings = {
        mapping.category_label: mapping.account
        for mapping in AccCashCategoryMapping.objects.filter(tenant=tenant).select_related(
            "account"
        )
    }
    journal_cache: dict[str, AccJournal | None] = {}
    category_accounts_seen: dict[str, set[str]] = {}
    summary = CashJournalImportSummary(batch=batch, total_rows=len(data_rows))

    for row_index, row in enumerate(data_rows):
        entry = _normalize_row(row, index_by_field)
        raw_data = {
            k: (v.isoformat() if isinstance(v, dt.date) else str(v)) for k, v in entry.items()
        }
        import_row = AccImportRow.objects.create(
            tenant=tenant, batch=batch, row_number=row_index + 1, raw_data=raw_data
        )

        if entry["exclu_des_totaux"]:
            # Ligne purement informative (solde de periode/report a
            # nouveau, GROUPE=SOLDE_PERIODE du fichier de reference) —
            # jamais de resolution de compte/caisse/periode necessaire,
            # jamais d'ecriture creee : compter deux fois le meme argent en
            # la traitant comme une vraie operation serait une erreur
            # comptable, pas une simplification.
            import_row.status = AccImportRow.STATUS_OK
            import_row.save(update_fields=["status"])
            summary.ok_count += 1
            continue

        account, account_anomalies = _resolve_account(tenant, entry, category_mappings)
        journal = _resolve_journal(tenant, entry["caisse"], journal_cache)
        period = None
        if entry["date"] is not None:
            period = (
                AccPeriod.objects.filter(
                    tenant=tenant,
                    state=AccPeriod.STATE_OPEN,
                    date_start__lte=entry["date"],
                    date_end__gte=entry["date"],
                )
                .order_by("date_start")
                .first()
            )
        if account is not None and entry["categorie"]:
            category_accounts_seen.setdefault(entry["categorie"], set()).add(account.code)

        anomaly_codes = _detect_row_anomalies(
            tenant,
            entry,
            journal=journal,
            account=account,
            account_anomalies=account_anomalies,
            period=period,
        )

        if anomaly_codes:
            import_row.status = AccImportRow.STATUS_ANOMALY
            import_row.anomaly_codes = anomaly_codes
            import_row.save(update_fields=["status", "anomaly_codes"])
            summary.anomaly_count += 1
            continue

        assert journal is not None and account is not None and period is not None
        move = _create_move_for_row(tenant, journal, period, account, entry)
        import_row.status = AccImportRow.STATUS_OK
        import_row.move = move
        import_row.save(update_fields=["status", "move"])
        summary.ok_count += 1

    for category_label, codes in category_accounts_seen.items():
        if len(codes) > 1:
            summary.batch_warnings.append(
                f"Catégorie « {category_label} » résolue vers {len(codes)} comptes différents "
                f"dans ce lot ({', '.join(sorted(codes))}) — incohérence à corriger."
            )

    batch.anomaly_rows_count = summary.anomaly_count
    batch.applied_rows_count = summary.ok_count
    batch.save(update_fields=["anomaly_rows_count", "applied_rows_count"])

    return summary


def resolve_import_row(
    row: AccImportRow,
    *,
    account: AccAccount | None = None,
    date: dt.date | None = None,
    discard: bool = False,
) -> AccImportRow:
    """Corrige manuellement une ligne en anomalie puis retente sa
    materialisation — jamais de resolution automatique/devinee : c'est
    toujours un humain qui fournit le compte/la date corrigee ici."""
    if discard:
        row.status = AccImportRow.STATUS_DISCARDED
        row.save(update_fields=["status"])
        return row

    entry = dict(row.raw_data)
    entry["entree"] = Decimal(entry.get("entree", "0"))
    entry["sortie"] = Decimal(entry.get("sortie", "0"))
    entry["exclu_des_totaux"] = str(entry.get("exclu_des_totaux")) == "True"
    if date is not None:
        entry["date"] = date
    elif entry.get("date") not in (None, "None"):
        entry["date"] = dt.date.fromisoformat(entry["date"])
    else:
        entry["date"] = None

    resolved_account = account or row.resolved_account
    tenant = row.tenant
    journal_cache: dict[str, AccJournal | None] = {}
    journal = _resolve_journal(tenant, entry.get("caisse", ""), journal_cache)
    period = None
    if entry["date"] is not None:
        period = (
            AccPeriod.objects.filter(
                tenant=tenant,
                state=AccPeriod.STATE_OPEN,
                date_start__lte=entry["date"],
                date_end__gte=entry["date"],
            )
            .order_by("date_start")
            .first()
        )

    account_anomalies: list[str] = (
        [] if resolved_account is not None else [ANOMALY_CATEGORIE_NON_MAPPEE]
    )
    anomaly_codes = _detect_row_anomalies(
        tenant,
        entry,
        journal=journal,
        account=resolved_account,
        account_anomalies=account_anomalies,
        period=period,
    )

    if anomaly_codes:
        row.status = AccImportRow.STATUS_ANOMALY
        row.anomaly_codes = anomaly_codes
        row.resolved_account = resolved_account
        row.save(update_fields=["status", "anomaly_codes", "resolved_account"])
        return row

    assert journal is not None and resolved_account is not None and period is not None
    move = _create_move_for_row(tenant, journal, period, resolved_account, entry)
    row.status = AccImportRow.STATUS_RESOLVED
    row.resolved_account = resolved_account
    row.move = move
    row.anomaly_codes = []
    row.save(update_fields=["status", "resolved_account", "move", "anomaly_codes"])
    return row
