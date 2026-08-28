"""Import du journal de caisse (operations de tresorerie en especes) depuis
un fichier xlsx fourni par l'utilisateur. Chaque ligne source produit soit
une vraie ecriture comptable brouillon (`AccMove`, jamais postee
automatiquement — RG-ACC du module), soit une anomalie mise en attente de
resolution humaine explicite (`AccImportRow.status=unresolvable`), meme
patron que le rapprochement bancaire assiste (A16,
`services/bank_reconciliation.py`).

Contrairement au fichier de reference qui a servi de specification a ce
format (colonne CAISSE unique par ligne, plusieurs caisses physiques
melangees dans le meme classeur), la caisse cible est resolue PAR LIGNE
(vers un `AccJournal` de type `TYPE_CASH` existant, par code ou nom,
insensible a la casse/aux accents) plutot que fixee une fois pour tout
l'import — une caisse non reconnue est une anomalie de ligne
(`CAISSE_INCONNUE`), jamais une creation automatique de journal.

**Chantier RG-QUALIF (qualification et identification universelle des
donnees importees)** — retrofit de ce module, registre defaultable/
non-defaultable complet dans `docs/IMPORT_FORMATS.md` §6 :

- `COMPTE_INCONNU`/`CATEGORIE_NON_MAPPEE` : DEfaultables — repli sur le
  compte d'attente (`chart_of_accounts.ensure_suspense_account`), un
  `AccMove` brouillon est materialise immediatement, la ligne passe
  `needs_qualification` (`uses_placeholder_account=True`).
- Partenaire (colonnes `FOURNISSEUR` sur une ligne SORTIE, `CLIENT`/
  `PARTENAIRE` sur une ligne ENTREE) : DEfaultable — repli sur le
  partenaire placeholder du role concerne
  (`partners.services.public.ensure_default_partner`) si
  `find_partner_by_name` ne renvoie pas `EXACT`, `uses_placeholder_
  partner=True`. Nouvelle identification — aucun importeur ne resolvait
  de partenaire avant ce chantier.
- `DATE_MANQUANTE`/`DATE_INVALIDE` : DEfaultables — repli documente sur
  la date du jour si une periode ouverte la couvre, sinon la date de
  debut de la periode ouverte la plus recente (`_fallback_date`),
  `uses_default_date=True`. Si aucune periode ouverte n'existe du tout,
  reste non-defaultable (`PERIODE_FERMEE_OU_INEXISTANTE`).
- `MONTANT_NUL`, `MONTANT_ENTREE_ET_SORTIE` : jamais defaultables —
  fabriquer un montant serait fabriquer un fait financier. Aucun
  `AccMove`, ligne `unresolvable`, jamais un blocage du reste du lot.
- `CAISSE_INCONNUE` : non-defaultable PAR EXCEPTION DELIBEREE (une caisse
  generique fausserait la position de tresorerie par caisse) — meme
  prudence qu'un montant ambigu, malgre la politique generale "defaulter
  des que possible".
- `PERIODE_FERMEE_OU_INEXISTANTE` (date explicite valide mais hors de
  toute periode ouverte) : non-defaultable — inventer une periode
  comptable n'a pas de repli sûr.

`qualify_import_row`/`decide_qualification` remplacent ensuite un
placeholder par l'entite reelle sur une ligne `needs_qualification`,
potentiellement gates par une nouvelle `ApprovalRule` scopee au
content-type `AccImportRow` (`ensure_qualification_approval_rule`) —
independante des seuils de validation de facture deja existants
(`services/invoices.py`)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.accounting.models import (
    AccAccount,
    AccCashCategoryMapping,
    AccImportBatch,
    AccImportRow,
    AccJournal,
    AccPeriod,
)
from apps.accounting.services.chart_of_accounts import ensure_suspense_account
from apps.accounting.services.moves import add_line, create_draft_move
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.models.workflow import ApprovalRequest, ApprovalRule
from apps.core.services import approvals
from apps.core.services.entity_resolution import ResolutionConfidence
from apps.core.services.import_xlsx import fold_header, read_xlsx_rows
from apps.partners.services.public import (
    ROLE_CLIENT,
    ROLE_SUPPLIER,
    ensure_default_partner,
    find_partner_by_name,
)

CASH_JOURNAL_FORMAT_VERSION = 1

QUALIFICATION_RULE_NAME = "accounting.accimportrow.qualification"

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
# l'utilisateur (jamais un code muet), cf. docs/IMPORT_FORMATS.md §6 pour
# le registre defaultable/non-defaultable complet.
ANOMALY_MONTANT_ENTREE_ET_SORTIE = "MONTANT_ENTREE_ET_SORTIE"
ANOMALY_MONTANT_NUL = "MONTANT_NUL"
ANOMALY_DATE_MANQUANTE = "DATE_MANQUANTE"
ANOMALY_DATE_INVALIDE = "DATE_INVALIDE"
ANOMALY_PERIODE_INDISPONIBLE = "PERIODE_FERMEE_OU_INEXISTANTE"
ANOMALY_COMPTE_INCONNU = "COMPTE_INCONNU"
ANOMALY_CATEGORIE_NON_MAPPEE = "CATEGORIE_NON_MAPPEE"
ANOMALY_CAISSE_INCONNUE = "CAISSE_INCONNUE"
ANOMALY_PARTENAIRE_NON_IDENTIFIE = "PARTENAIRE_NON_IDENTIFIE"

# Codes non-defaultables (cf. docstring de module) : une ligne qui en porte
# un ne produit JAMAIS de `AccMove`, reste `STATUS_UNRESOLVABLE`.
_BLOCKING_ANOMALY_CODES = {
    ANOMALY_MONTANT_ENTREE_ET_SORTIE,
    ANOMALY_MONTANT_NUL,
    ANOMALY_CAISSE_INCONNUE,
    ANOMALY_PERIODE_INDISPONIBLE,
}

_MIN_DATE = dt.date(2000, 1, 1)


@dataclass
class CashJournalImportSummary:
    batch: AccImportBatch
    total_rows: int
    ok_count: int = 0
    needs_qualification_count: int = 0
    unresolvable_count: int = 0
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
        "partenaire": str(get("partenaire") or "").strip(),
        "client": str(get("client") or "").strip(),
        "fournisseur": str(get("fournisseur") or "").strip(),
        "nature_origine": str(get("nature_origine") or "").strip(),
        "type_piece": str(get("type_piece") or "").strip(),
    }


def _resolve_account(
    tenant: Tenant, entry: dict[str, Any], category_mappings: dict[str, AccAccount]
) -> tuple[AccAccount, list[str], bool]:
    """RG import caisse : un compte explicite (colonne COMPTE PCG) prime
    toujours sur la resolution par categorie. DEPUIS RG-QUALIF, cette
    fonction ne renvoie JAMAIS `None` : un compte introuvable retombe sur
    le compte d'attente (`ensure_suspense_account`), trace par le code
    d'anomalie retourne (pour audit) sans plus jamais bloquer la ligne."""
    if entry["compte_pcg"]:
        account = AccAccount.objects.filter(tenant=tenant, code=entry["compte_pcg"]).first()
        if account is not None:
            return account, [], False
        return ensure_suspense_account(tenant), [ANOMALY_COMPTE_INCONNU], True

    if entry["categorie"] in category_mappings:
        return category_mappings[entry["categorie"]], [], False

    return ensure_suspense_account(tenant), [ANOMALY_CATEGORIE_NON_MAPPEE], True


def _resolve_partner(tenant: Tenant, entry: dict[str, Any]) -> tuple[UUID, list[str], bool]:
    """Identifie le partenaire de la ligne — `FOURNISSEUR` sur une ligne
    SORTIE, `CLIENT`/`PARTENAIRE` sur une ligne ENTREE (repli sur
    `PARTENAIRE` si la colonne dediee est vide). Jamais bloquant : une
    correspondance non-`EXACT` (aucun nom fourni, `UNRESOLVED`, ou toute
    `FUZZY` — non produite en v1 par `find_partner_by_name`) retombe sur
    le partenaire placeholder du role concerne."""
    if entry["sortie"] > 0:
        role = ROLE_SUPPLIER
        name = entry["fournisseur"] or entry["partenaire"]
    else:
        role = ROLE_CLIENT
        name = entry["client"] or entry["partenaire"]

    if name:
        result = find_partner_by_name(tenant, name)
        if result.confidence == ResolutionConfidence.EXACT:
            assert result.entity_id is not None
            return result.entity_id, [], False

    placeholder_partner_id = ensure_default_partner(tenant, role)
    return placeholder_partner_id, [ANOMALY_PARTENAIRE_NON_IDENTIFIE], True


def _resolve_journal(
    tenant: Tenant, caisse_label: str, journal_cache: dict[str, AccJournal | None]
) -> AccJournal | None:
    """Resout la caisse de la ligne vers un `AccJournal` de type `TYPE_CASH`
    existant (par code ou nom, insensible casse/accents) — renvoie `None`
    (donc `ANOMALY_CAISSE_INCONNUE`, non-defaultable PAR EXCEPTION
    DELIBEREE, cf. docstring de module) si la caisse n'est pas reconnue OU
    si le journal trouve n'a pas de compte de caisse configure
    (`default_account`)."""
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


def _fallback_date(tenant: Tenant) -> tuple[dt.date | None, AccPeriod | None]:
    """Repli documente pour `DATE_MANQUANTE`/`DATE_INVALIDE` (cf. docstring
    de module) : la date du jour si une periode ouverte la couvre, sinon
    la date de debut de la periode ouverte la plus recente. `(None, None)`
    si aucune periode ouverte n'existe du tout (repli impossible — la
    ligne reste alors `PERIODE_FERMEE_OU_INEXISTANTE`, non-defaultable)."""
    today = dt.date.today()
    period = (
        AccPeriod.objects.filter(
            tenant=tenant, state=AccPeriod.STATE_OPEN, date_start__lte=today, date_end__gte=today
        )
        .order_by("date_start")
        .first()
    )
    if period is not None:
        return today, period

    period = (
        AccPeriod.objects.filter(tenant=tenant, state=AccPeriod.STATE_OPEN)
        .order_by("-date_start")
        .first()
    )
    if period is not None:
        return period.date_start, period
    return None, None


def _resolve_date_and_period(
    tenant: Tenant, entry: dict[str, Any]
) -> tuple[dt.date | None, AccPeriod | None, list[str], bool]:
    """Retourne `(date, periode, codes_anomalie, date_par_defaut)`. Une
    date explicite valide mais hors de toute periode ouverte n'est PAS
    defaultee ici (cf. docstring de module — inventer une periode n'a pas
    de repli sûr) : seule une date MANQUANTE ou INVALIDE declenche
    `_fallback_date`."""
    raw_date = entry["date"]
    if raw_date is not None and _MIN_DATE <= raw_date <= dt.date.today() + dt.timedelta(days=366):
        period = (
            AccPeriod.objects.filter(
                tenant=tenant,
                state=AccPeriod.STATE_OPEN,
                date_start__lte=raw_date,
                date_end__gte=raw_date,
            )
            .order_by("date_start")
            .first()
        )
        if period is None:
            return raw_date, None, [ANOMALY_PERIODE_INDISPONIBLE], False
        return raw_date, period, [], False

    invalid_code = ANOMALY_DATE_MANQUANTE if raw_date is None else ANOMALY_DATE_INVALIDE
    fallback_date, fallback_period = _fallback_date(tenant)
    if fallback_date is None or fallback_period is None:
        return None, None, [invalid_code, ANOMALY_PERIODE_INDISPONIBLE], False
    return fallback_date, fallback_period, [invalid_code], True


def _create_move_for_row(
    tenant: Tenant,
    journal: AccJournal,
    period: AccPeriod,
    account: AccAccount,
    partner_id: UUID,
    entry: dict[str, Any],
    date: dt.date,
) -> Any:
    cash_account = journal.default_account
    assert cash_account is not None  # garanti par l'appelant (cf. _resolve_journal)

    move = create_draft_move(
        tenant=tenant,
        journal=journal,
        period=period,
        date=date,
        partner_id=partner_id,
        narration=entry["libelle"],
    )
    if entry["entree"] > 0:
        add_line(move, account=cash_account, label=entry["libelle"], debit=entry["entree"])
        add_line(
            move,
            account=account,
            label=entry["libelle"],
            credit=entry["entree"],
            partner_id=partner_id,
        )
    else:
        add_line(
            move,
            account=account,
            label=entry["libelle"],
            debit=entry["sortie"],
            partner_id=partner_id,
        )
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
            # jamais de resolution necessaire, jamais d'ecriture creee.
            import_row.status = AccImportRow.STATUS_OK
            import_row.save(update_fields=["status"])
            summary.ok_count += 1
            continue

        anomaly_codes: list[str] = []

        if entry["entree"] > 0 and entry["sortie"] > 0:
            anomaly_codes.append(ANOMALY_MONTANT_ENTREE_ET_SORTIE)
        elif entry["entree"] == 0 and entry["sortie"] == 0:
            anomaly_codes.append(ANOMALY_MONTANT_NUL)

        journal = _resolve_journal(tenant, entry["caisse"], journal_cache)
        if journal is None:
            anomaly_codes.append(ANOMALY_CAISSE_INCONNUE)

        if any(code in _BLOCKING_ANOMALY_CODES for code in anomaly_codes):
            import_row.status = AccImportRow.STATUS_UNRESOLVABLE
            import_row.anomaly_codes = anomaly_codes
            import_row.save(update_fields=["status", "anomaly_codes"])
            summary.unresolvable_count += 1
            continue

        date, period, date_codes, uses_default_date = _resolve_date_and_period(tenant, entry)
        anomaly_codes.extend(date_codes)
        if any(code in _BLOCKING_ANOMALY_CODES for code in date_codes) or period is None:
            import_row.status = AccImportRow.STATUS_UNRESOLVABLE
            import_row.anomaly_codes = anomaly_codes
            import_row.save(update_fields=["status", "anomaly_codes"])
            summary.unresolvable_count += 1
            continue
        assert date is not None and journal is not None

        account, account_codes, uses_placeholder_account = _resolve_account(
            tenant, entry, category_mappings
        )
        anomaly_codes.extend(account_codes)
        if account is not None and entry["categorie"] and not uses_placeholder_account:
            category_accounts_seen.setdefault(entry["categorie"], set()).add(account.code)

        partner_id, partner_codes, uses_placeholder_partner = _resolve_partner(tenant, entry)
        anomaly_codes.extend(partner_codes)

        move = _create_move_for_row(tenant, journal, period, account, partner_id, entry, date)

        needs_qualification = (
            uses_placeholder_account or uses_placeholder_partner or uses_default_date
        )
        import_row.status = (
            AccImportRow.STATUS_NEEDS_QUALIFICATION
            if needs_qualification
            else AccImportRow.STATUS_OK
        )
        import_row.move = move
        import_row.resolved_account = account
        import_row.partner_id = partner_id
        import_row.uses_placeholder_account = uses_placeholder_account
        import_row.uses_placeholder_partner = uses_placeholder_partner
        import_row.uses_default_date = uses_default_date
        import_row.anomaly_codes = anomaly_codes
        import_row.save(
            update_fields=[
                "status",
                "move",
                "resolved_account",
                "partner_id",
                "uses_placeholder_account",
                "uses_placeholder_partner",
                "uses_default_date",
                "anomaly_codes",
            ]
        )
        if needs_qualification:
            summary.needs_qualification_count += 1
        else:
            summary.ok_count += 1

    for category_label, codes in category_accounts_seen.items():
        if len(codes) > 1:
            summary.batch_warnings.append(
                f"Catégorie « {category_label} » résolue vers {len(codes)} comptes différents "
                f"dans ce lot ({', '.join(sorted(codes))}) — incohérence à corriger."
            )

    batch.anomaly_rows_count = summary.unresolvable_count
    batch.applied_rows_count = summary.ok_count + summary.needs_qualification_count
    batch.save(update_fields=["anomaly_rows_count", "applied_rows_count"])

    return summary


def resolve_import_row(
    row: AccImportRow,
    *,
    account: AccAccount | None = None,
    date: dt.date | None = None,
    discard: bool = False,
) -> AccImportRow:
    """Corrige manuellement une ligne `unresolvable` (montant/caisse/periode
    ambigus — les seuls cas restant bloquants depuis RG-QUALIF, cf.
    docstring de module) puis retente sa materialisation — jamais de
    resolution devinee : c'est toujours un humain qui fournit le
    compte/la date corrigee ici."""
    if discard:
        row.status = AccImportRow.STATUS_DISCARDED
        row.save(update_fields=["status"])
        return row

    entry = dict(row.raw_data)
    entry["entree"] = Decimal(entry.get("entree", "0"))
    entry["sortie"] = Decimal(entry.get("sortie", "0"))
    if date is not None:
        entry["date"] = date
    elif entry.get("date") not in (None, "None"):
        entry["date"] = dt.date.fromisoformat(entry["date"])
    else:
        entry["date"] = None

    tenant = row.tenant
    anomaly_codes: list[str] = []

    if entry["entree"] > 0 and entry["sortie"] > 0:
        anomaly_codes.append(ANOMALY_MONTANT_ENTREE_ET_SORTIE)
    elif entry["entree"] == 0 and entry["sortie"] == 0:
        anomaly_codes.append(ANOMALY_MONTANT_NUL)

    journal_cache: dict[str, AccJournal | None] = {}
    journal = _resolve_journal(tenant, entry.get("caisse", ""), journal_cache)
    if journal is None:
        anomaly_codes.append(ANOMALY_CAISSE_INCONNUE)

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
        if period is None:
            anomaly_codes.append(ANOMALY_PERIODE_INDISPONIBLE)
    else:
        anomaly_codes.append(ANOMALY_DATE_MANQUANTE)

    resolved_account = account or row.resolved_account

    if anomaly_codes or journal is None or period is None or resolved_account is None:
        row.status = AccImportRow.STATUS_UNRESOLVABLE
        row.anomaly_codes = anomaly_codes
        row.resolved_account = resolved_account
        row.save(update_fields=["status", "anomaly_codes", "resolved_account"])
        return row

    partner_id, _partner_codes, _uses_placeholder = _resolve_partner(tenant, entry)
    move = _create_move_for_row(
        tenant, journal, period, resolved_account, partner_id, entry, entry["date"]
    )
    row.status = AccImportRow.STATUS_RESOLVED
    row.resolved_account = resolved_account
    row.partner_id = partner_id
    row.move = move
    row.anomaly_codes = []
    row.save(update_fields=["status", "resolved_account", "partner_id", "move", "anomaly_codes"])
    return row


def ensure_qualification_approval_rule(tenant: Tenant) -> ApprovalRule:
    """Cree, si elle n'existe pas encore, LA regle d'approbation de
    qualification des lignes d'import de journal de caisse pour ce tenant
    — idempotente, scopee au content-type `AccImportRow`, condition
    `requires_placeholder` (independante des seuils de validation de
    facture deja existants, cf. `services/invoices.py`). Approbateur par
    defaut : `direction` (pilotage transverse), qualifiable par
    `comptable` (domaine cible du module, cf. `rbac_policy.
    ROLE_APP_PERMISSIONS`)."""
    content_type = ContentType.objects.get_for_model(AccImportRow)
    rule, _created = ApprovalRule.objects.get_or_create(
        tenant=tenant,
        content_type=content_type,
        name=QUALIFICATION_RULE_NAME,
        defaults={"approver_role": "direction", "condition": {"requires_placeholder": True}},
    )
    return rule


def qualify_import_row(
    row: AccImportRow,
    *,
    account: AccAccount | None = None,
    partner_id: UUID | None = None,
    qualified_by: User,
) -> AccImportRow:
    """Remplace le(s) placeholder(s) d'une ligne `needs_qualification` par
    l'entite reelle fournie par l'utilisateur, sur l'`AccMove` DEJA
    materialise (jamais de recreation) — puis evalue la nouvelle
    `ApprovalRule` de qualification : si active, cree une `ApprovalRequest`
    et passe la ligne `pending_approval` ; sinon la marque `qualified`
    directement."""
    if row.status != AccImportRow.STATUS_NEEDS_QUALIFICATION:
        raise ValidationError(_("Seule une ligne « à qualifier » peut être qualifiée."))
    move = row.move
    if move is None:
        raise ValidationError(_("Cette ligne n'a pas d'écriture associée à qualifier."))

    requires_approval = row.uses_placeholder_account or row.uses_placeholder_partner

    if account is not None and row.uses_placeholder_account:
        line = move.lines.filter(account_id=row.resolved_account_id).first()
        if line is not None:
            line.account = account
            line.save(update_fields=["account"])
        row.resolved_account = account
        row.uses_placeholder_account = False

    if partner_id is not None and row.uses_placeholder_partner:
        move.partner_id = partner_id
        move.save(update_fields=["partner_id"])
        move.lines.filter(partner_id=row.partner_id).update(partner_id=partner_id)
        row.partner_id = partner_id
        row.uses_placeholder_partner = False

    update_fields = [
        "resolved_account",
        "partner_id",
        "uses_placeholder_account",
        "uses_placeholder_partner",
        "status",
    ]

    if requires_approval:
        rule = ensure_qualification_approval_rule(row.tenant)
        if rule.is_active:
            approval_request = approvals.request_approval(row, rule, qualified_by)
            row.status = AccImportRow.STATUS_PENDING_APPROVAL
            row.qualification_approval_request = approval_request
            update_fields.append("qualification_approval_request")
            row.save(update_fields=update_fields)
            return row

    row.status = AccImportRow.STATUS_QUALIFIED
    row.save(update_fields=update_fields)
    return row


def decide_qualification(
    approval_request: ApprovalRequest, decided_by: User, *, approved: bool, comment: str = ""
) -> AccImportRow:
    """Enveloppe fine de `apps.core.services.approvals.decide` qui met
    aussi a jour le statut de la ligne d'import qualifiee : `qualified` si
    approuvee, `needs_qualification` (a re-soumettre avec un autre choix)
    si rejetee — la donnee deja remplacee par `qualify_import_row` n'est
    PAS annulee, seule la ligne est repassee en file d'attente."""
    approvals.decide(approval_request, decided_by, approved=approved, comment=comment)
    row = AccImportRow.objects.get(qualification_approval_request=approval_request)
    row.status = (
        AccImportRow.STATUS_QUALIFIED if approved else AccImportRow.STATUS_NEEDS_QUALIFICATION
    )
    row.save(update_fields=["status"])
    return row
