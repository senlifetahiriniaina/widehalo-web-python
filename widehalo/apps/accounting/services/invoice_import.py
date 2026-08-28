"""Import de factures client et fournisseur depuis un fichier xlsx fourni
par l'utilisateur — nouvel importeur (aucun n'existait pour ce type de
donnee avant le chantier RG-QUALIF), construit comme demonstration de
bout en bout du socle de qualification/identification universelle sur un
cas neuf plutot que sur un retrofit.

**Structure du fichier** : une ligne = une ligne de facture (produit/
service, quantite, prix, taux de TVA) ; plusieurs lignes partageant la
meme colonne REFERENCE (et le meme SENS) sont regroupees pour materialiser
UNE SEULE facture (`AccMove`) — jamais une facture par ligne, une facture
reelle a presque toujours plusieurs lignes de produit/service.

**Jamais de duplication de la construction de facture** : ce module
n'appelle QUE `apps.accounting.services.public.create_customer_invoice_
from_source`/`create_supplier_invoice_from_source` (deja construits pour
`sales`/`purchase`) pour materialiser le document — aucune logique de
construction d'`AccMove`/`AccMoveLine` n'est reimplementee ici.

**Chantier RG-QUALIF** — registre defaultable/non-defaultable complet
dans `docs/IMPORT_FORMATS.md` §6 :

- Partenaire (colonne PARTENAIRE) : DEfaultable — meme resolution que
  `cash_journal_import` (`find_partner_by_name`/`ensure_default_partner`,
  role fournisseur si SENS=fournisseur, client sinon).
- Produit (colonne CODE_PRODUIT) : DEfaultable — repli sur la variante
  placeholder (`catalog.services.public.ensure_default_variant`). Purement
  une donnee d'IDENTIFICATION tracee sur la ligne d'import
  (`resolved_variant_id`) : `AccMoveLine` ne porte aucun champ variante
  (jamais materialise sur l'ecriture elle-meme), donc requalifier cette
  dimension ne touche jamais le `AccMove` — simplification assumee et
  documentee.
- Compte (colonne COMPTE, optionnelle) : si fournie mais non reconnue,
  DEfaultable — repli sur le compte d'attente
  (`chart_of_accounts.ensure_suspense_account`), meme principe que
  `cash_journal_import`. Si absente, aucun placeholder : la ligne retombe
  sur le compte produit/charge par defaut deja resolu par `create_
  customer_invoice_from_source`/`create_supplier_invoice_from_source`
  elles-memes (comportement CDC deja existant, non concerne par ce
  registre).
- Taux de TVA (colonne TAUX_TVA) : DEfaultable, mais signale avec un
  poids particulier — sujet REGLEMENTAIRE SENSIBLE (declaration TVA,
  ACC-CAL1/DCOM). Absence de taux OU taux sans `AccTax` correspondante ->
  `TVA_NON_DETERMINEE`, ligne de TVA imputee sur le compte d'attente,
  `uses_placeholder_tax=True`. **Toujours** `needs_qualification`, meme
  quand aucune autre dimension de la ligne n'utilise de placeholder — la
  seule anomalie de ce registre traitee ainsi.
- Date : DEfaultable (repli documente identique a `cash_journal_import`,
  `_fallback_date`).
- Reference facture manquante, sens invalide (ni "client" ni
  "fournisseur"), quantite/prix invalides, configuration comptable
  manquante (aucun journal vente/achat, aucune periode ouverte, aucun
  compte client/fournisseur) : **jamais defaultables** — fabriquer une
  reference, un sens, ou une piece comptable sur une configuration
  absente n'a pas de repli sûr."""

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
    AccInvoiceImportBatch,
    AccInvoiceImportRow,
    AccPeriod,
    AccTax,
)
from apps.accounting.services.chart_of_accounts import ensure_suspense_account
from apps.accounting.services.public import (
    create_customer_invoice_from_source,
    create_supplier_invoice_from_source,
)
from apps.catalog.services.public import get_variant_id_by_reference
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

INVOICE_IMPORT_FORMAT_VERSION = 1

QUALIFICATION_RULE_NAME = "accounting.accinvoiceimportrow.qualification"

INVOICE_IMPORT_HEADER_ALIASES: dict[str, set[str]] = {
    "reference": {"REFERENCE", "REFERENCE FACTURE", "NUMERO DE FACTURE"},
    "date": {"DATE"},
    "sens": {"SENS"},
    "partenaire": {"PARTENAIRE"},
    "code_produit": {"CODE_PRODUIT", "CODE PRODUIT", "REFERENCE PRODUIT"},
    "designation": {"DESIGNATION", "LIBELLE"},
    "qty": {"QUANTITE", "QTY"},
    "prix_unitaire": {"PRIX_UNITAIRE", "PRIX UNITAIRE"},
    "taux_tva": {"TAUX_TVA", "TAUX TVA", "TVA"},
    "compte": {"COMPTE", "COMPTE PCG"},
}

ANOMALY_REFERENCE_MANQUANTE = "REFERENCE_MANQUANTE"
ANOMALY_SENS_INVALIDE = "SENS_INVALIDE"
ANOMALY_QUANTITE_INVALIDE = "QUANTITE_INVALIDE"
ANOMALY_PRIX_INVALIDE = "PRIX_INVALIDE"
ANOMALY_CONFIGURATION_COMPTABLE_MANQUANTE = "CONFIGURATION_COMPTABLE_MANQUANTE"
ANOMALY_PARTENAIRE_NON_IDENTIFIE = "PARTENAIRE_NON_IDENTIFIE"
ANOMALY_PRODUIT_INCONNU = "PRODUIT_INCONNU"
ANOMALY_TVA_NON_DETERMINEE = "TVA_NON_DETERMINEE"
ANOMALY_COMPTE_INCONNU = "COMPTE_INCONNU"
ANOMALY_DATE_MANQUANTE = "DATE_MANQUANTE"
ANOMALY_DATE_INVALIDE = "DATE_INVALIDE"
ANOMALY_PERIODE_INDISPONIBLE = "PERIODE_FERMEE_OU_INEXISTANTE"

# Codes non-defaultables (cf. docstring de module) : une ligne/un groupe
# qui en porte un ne produit JAMAIS de `AccMove`, reste `STATUS_
# UNRESOLVABLE`.
_BLOCKING_ANOMALY_CODES = {
    ANOMALY_REFERENCE_MANQUANTE,
    ANOMALY_SENS_INVALIDE,
    ANOMALY_QUANTITE_INVALIDE,
    ANOMALY_PRIX_INVALIDE,
    ANOMALY_CONFIGURATION_COMPTABLE_MANQUANTE,
    ANOMALY_PERIODE_INDISPONIBLE,
}

_MIN_DATE = dt.date(2000, 1, 1)


@dataclass
class InvoiceImportSummary:
    batch: AccInvoiceImportBatch
    total_rows: int
    ok_count: int = 0
    needs_qualification_count: int = 0
    unresolvable_count: int = 0
    invoices_created_count: int = 0
    batch_warnings: list[str] = field(default_factory=list)


def _resolve_header_index(header: list[str]) -> dict[str, int]:
    normalized = [fold_header(cell) for cell in header]
    resolved: dict[str, int] = {}
    for field_name, aliases in INVOICE_IMPORT_HEADER_ALIASES.items():
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

    date_value = get("date")
    if isinstance(date_value, dt.datetime):
        date_value = date_value.date()

    def to_decimal(value: Any) -> Decimal | None:
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None

    return {
        "reference": str(get("reference") or "").strip(),
        "date": date_value if isinstance(date_value, dt.date) else None,
        "sens": str(get("sens") or "").strip().lower(),
        "partenaire": str(get("partenaire") or "").strip(),
        "code_produit": str(get("code_produit") or "").strip(),
        "designation": str(get("designation") or "").strip(),
        "qty": to_decimal(get("qty")),
        "prix_unitaire": to_decimal(get("prix_unitaire")),
        "taux_tva": to_decimal(get("taux_tva")),
        "compte": str(get("compte") or "").strip(),
    }


def _fallback_date(tenant: Tenant) -> tuple[dt.date | None, AccPeriod | None]:
    """Meme repli documente que `cash_journal_import._fallback_date`."""
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


def _resolve_date(
    tenant: Tenant, raw_date: dt.date | None
) -> tuple[dt.date | None, list[str], bool]:
    if raw_date is not None and _MIN_DATE <= raw_date <= dt.date.today() + dt.timedelta(days=366):
        return raw_date, [], False
    invalid_code = ANOMALY_DATE_MANQUANTE if raw_date is None else ANOMALY_DATE_INVALIDE
    fallback_date, fallback_period = _fallback_date(tenant)
    if fallback_date is None or fallback_period is None:
        return None, [invalid_code, ANOMALY_PERIODE_INDISPONIBLE], False
    return fallback_date, [invalid_code], True


def _resolve_partner(tenant: Tenant, sens: str, name: str) -> tuple[UUID, list[str], bool]:
    role = ROLE_SUPPLIER if sens == AccInvoiceImportRow.SENS_FOURNISSEUR else ROLE_CLIENT
    if name:
        result = find_partner_by_name(tenant, name)
        if result.confidence == ResolutionConfidence.EXACT:
            assert result.entity_id is not None
            return result.entity_id, [], False
    return ensure_default_partner(tenant, role), [ANOMALY_PARTENAIRE_NON_IDENTIFIE], True


def _resolve_variant(code: str) -> tuple[UUID | None, list[str], bool]:
    if code:
        variant_id = get_variant_id_by_reference(code)
        if variant_id is not None:
            return variant_id, [], False
    return None, [ANOMALY_PRODUIT_INCONNU], True


def _resolve_line_account(tenant: Tenant, compte_code: str) -> tuple[UUID | None, list[str], bool]:
    """Retourne `(account_id, codes, uses_placeholder)` — `None` si aucune
    colonne COMPTE n'est fournie (pas un placeholder : la resolution
    par-defaut deja existante de `create_customer_invoice_from_source`/
    `create_supplier_invoice_from_source` s'applique alors, hors registre
    RG-QUALIF, cf. docstring de module)."""
    if not compte_code:
        return None, [], False
    account = AccAccount.objects.filter(tenant=tenant, code=compte_code).first()
    if account is not None:
        account_id: UUID = account.id
        return account_id, [], False
    placeholder_id: UUID = ensure_suspense_account(tenant).id
    return placeholder_id, [ANOMALY_COMPTE_INCONNU], True


def _resolve_tax_account(
    tenant: Tenant, sens: str, rate: Decimal | None, ht_amount: Decimal
) -> tuple[UUID, Decimal, list[str], bool]:
    """Retourne `(tax_account_id, vat_amount_mga, codes, uses_placeholder)`
    — cf. docstring de module : sujet reglementaire sensible, toujours
    `TVA_NON_DETERMINEE` si le taux est absent ou sans `AccTax`
    correspondante pour ce tenant/sens. `tax_account_id` retombe TOUJOURS
    sur le compte d'attente quand le taux est indetermine — meme sans
    montant de TVA calculable (`rate is None`), pour que la ligne d'import
    trace explicitement quel compte devra etre corrige a la qualification."""
    if rate is None:
        placeholder_id: UUID = ensure_suspense_account(tenant).id
        return placeholder_id, Decimal(0), [ANOMALY_TVA_NON_DETERMINEE], True

    tax_type = AccTax.TYPE_SALE if sens == AccInvoiceImportRow.SENS_CLIENT else AccTax.TYPE_PURCHASE
    tax = AccTax.objects.filter(tenant=tenant, type=tax_type, rate=rate).first()
    account = None
    if tax is not None:
        account = (
            tax.account_collected
            if sens == AccInvoiceImportRow.SENS_CLIENT
            else tax.account_deductible
        )
    vat_amount = (ht_amount * rate / Decimal(100)).quantize(Decimal("0.0001"))
    if account is not None:
        account_id: UUID = account.id
        return account_id, vat_amount, [], False

    placeholder_id = ensure_suspense_account(tenant).id
    return placeholder_id, vat_amount, [ANOMALY_TVA_NON_DETERMINEE], True


def import_invoices_xlsx(
    tenant: Tenant, file_bytes: bytes, *, filename: str = "", format_version: int | None = None
) -> InvoiceImportSummary:
    if format_version is not None and format_version > INVOICE_IMPORT_FORMAT_VERSION:
        raise ValueError(
            f"Format d'import de factures v{format_version} non supporté "
            f"(version maximale supportée : v{INVOICE_IMPORT_FORMAT_VERSION}) — "
            "mettez à jour l'application avant de réimporter ce fichier."
        )

    header, data_rows = read_xlsx_rows(file_bytes)
    index_by_field = _resolve_header_index(header)

    batch = AccInvoiceImportBatch.objects.create(
        tenant=tenant,
        source_filename=filename,
        format_version=format_version or INVOICE_IMPORT_FORMAT_VERSION,
        total_rows=len(data_rows),
    )
    summary = InvoiceImportSummary(batch=batch, total_rows=len(data_rows))

    groups: dict[tuple[str, str], list[AccInvoiceImportRow]] = {}

    for row_index, row in enumerate(data_rows):
        entry = _normalize_row(row, index_by_field)
        raw_data = {
            k: (v.isoformat() if isinstance(v, dt.date) else str(v)) for k, v in entry.items()
        }
        import_row = AccInvoiceImportRow.objects.create(
            tenant=tenant,
            batch=batch,
            row_number=row_index + 1,
            raw_data=raw_data,
            invoice_reference=entry["reference"],
            sens=entry["sens"]
            if entry["sens"]
            in (AccInvoiceImportRow.SENS_CLIENT, AccInvoiceImportRow.SENS_FOURNISSEUR)
            else "",
        )

        anomaly_codes: list[str] = []
        if not entry["reference"]:
            anomaly_codes.append(ANOMALY_REFERENCE_MANQUANTE)
        if entry["sens"] not in (
            AccInvoiceImportRow.SENS_CLIENT,
            AccInvoiceImportRow.SENS_FOURNISSEUR,
        ):
            anomaly_codes.append(ANOMALY_SENS_INVALIDE)
        if entry["qty"] is None or entry["qty"] <= 0:
            anomaly_codes.append(ANOMALY_QUANTITE_INVALIDE)
        if entry["prix_unitaire"] is None or entry["prix_unitaire"] < 0:
            anomaly_codes.append(ANOMALY_PRIX_INVALIDE)

        if anomaly_codes:
            import_row.status = AccInvoiceImportRow.STATUS_UNRESOLVABLE
            import_row.anomaly_codes = anomaly_codes
            import_row.save(update_fields=["status", "anomaly_codes"])
            summary.unresolvable_count += 1
            continue

        groups.setdefault((entry["reference"], entry["sens"]), []).append(import_row)

    for (reference, sens), rows in groups.items():
        _materialize_invoice_group(tenant, reference, sens, rows, filename, summary)

    batch.anomaly_rows_count = summary.unresolvable_count
    batch.applied_rows_count = summary.ok_count + summary.needs_qualification_count
    batch.save(update_fields=["anomaly_rows_count", "applied_rows_count"])

    return summary


def _materialize_invoice_group(
    tenant: Tenant,
    reference: str,
    sens: str,
    rows: list[AccInvoiceImportRow],
    filename: str,
    summary: InvoiceImportSummary,
) -> None:
    entries = [dict(row.raw_data) for row in rows]
    for entry in entries:
        entry["qty"] = Decimal(entry["qty"])
        entry["prix_unitaire"] = Decimal(entry["prix_unitaire"])
        entry["taux_tva"] = (
            Decimal(entry["taux_tva"]) if entry["taux_tva"] not in (None, "None") else None
        )
        entry["date"] = (
            dt.date.fromisoformat(entry["date"]) if entry["date"] not in (None, "None") else None
        )

    date, date_codes, uses_default_date = _resolve_date(tenant, entries[0]["date"])
    if date is None:
        for row in rows:
            row.status = AccInvoiceImportRow.STATUS_UNRESOLVABLE
            row.anomaly_codes = date_codes
            row.save(update_fields=["status", "anomaly_codes"])
            summary.unresolvable_count += 1
        return

    partner_name = next((e["partenaire"] for e in entries if e["partenaire"]), "")
    partner_id, partner_codes, uses_placeholder_partner = _resolve_partner(
        tenant, sens, partner_name
    )

    lines: list[dict[str, Any]] = []
    row_meta: list[dict[str, Any]] = []
    for entry, row in zip(entries, rows, strict=True):
        variant_id, variant_codes, uses_placeholder_variant = _resolve_variant(
            entry["code_produit"]
        )
        account_id, account_codes, uses_placeholder_account = _resolve_line_account(
            tenant, entry["compte"]
        )
        ht_amount = entry["qty"] * entry["prix_unitaire"]
        tax_account_id, vat_amount, tax_codes, uses_placeholder_tax = _resolve_tax_account(
            tenant, sens, entry["taux_tva"], ht_amount
        )

        codes = list(date_codes) + list(partner_codes) + variant_codes + account_codes + tax_codes
        lines.append({"account_id": account_id, "amount": ht_amount, "label": entry["designation"]})
        line_index = len(lines) - 1
        vat_line_index = None
        if vat_amount > 0:
            lines.append(
                {
                    "account_id": tax_account_id,
                    "amount": vat_amount,
                    "label": f"TVA — {entry['designation']}",
                }
            )
            vat_line_index = len(lines) - 1

        row_meta.append(
            {
                "row": row,
                "codes": codes,
                "variant_id": variant_id,
                "uses_placeholder_variant": uses_placeholder_variant,
                "account_id": account_id,
                "uses_placeholder_account": uses_placeholder_account,
                "tax_account_id": tax_account_id,
                "uses_placeholder_tax": uses_placeholder_tax,
                "line_index": line_index,
                "vat_line_index": vat_line_index,
            }
        )

    if sens == AccInvoiceImportRow.SENS_CLIENT:
        move_id = create_customer_invoice_from_source(
            tenant=tenant, partner_id=partner_id, date=date, income_lines=lines
        )
    else:
        move_id = create_supplier_invoice_from_source(
            tenant=tenant, partner_id=partner_id, date=date, expense_lines=lines
        )

    if move_id is None:
        for row in rows:
            row.status = AccInvoiceImportRow.STATUS_UNRESOLVABLE
            row.anomaly_codes = [ANOMALY_CONFIGURATION_COMPTABLE_MANQUANTE]
            row.save(update_fields=["status", "anomaly_codes"])
            summary.unresolvable_count += 1
        return

    for meta in row_meta:
        row = meta["row"]
        needs_qualification = (
            uses_placeholder_partner
            or meta["uses_placeholder_variant"]
            or meta["uses_placeholder_account"]
            or meta["uses_placeholder_tax"]
        )
        row.status = (
            AccInvoiceImportRow.STATUS_NEEDS_QUALIFICATION
            if needs_qualification
            else AccInvoiceImportRow.STATUS_OK
        )
        row.move_id = move_id
        row.partner_id = partner_id
        row.resolved_variant_id = meta["variant_id"]
        row.resolved_account_id = meta["account_id"]
        row.resolved_tax_account_id = meta["tax_account_id"]
        row.uses_placeholder_partner = uses_placeholder_partner
        row.uses_placeholder_variant = meta["uses_placeholder_variant"]
        row.uses_placeholder_account = meta["uses_placeholder_account"]
        row.uses_placeholder_tax = meta["uses_placeholder_tax"]
        row.uses_default_date = uses_default_date
        row.anomaly_codes = meta["codes"]
        row.save(
            update_fields=[
                "status",
                "move",
                "partner_id",
                "resolved_variant_id",
                "resolved_account",
                "resolved_tax_account",
                "uses_placeholder_partner",
                "uses_placeholder_variant",
                "uses_placeholder_account",
                "uses_placeholder_tax",
                "uses_default_date",
                "anomaly_codes",
            ]
        )
        if needs_qualification:
            summary.needs_qualification_count += 1
        else:
            summary.ok_count += 1
    summary.invoices_created_count += 1


def resolve_import_row(row: AccInvoiceImportRow, *, discard: bool = False) -> AccInvoiceImportRow:
    """Ecarte volontairement une ligne `unresolvable` — contrairement a
    `cash_journal_import.resolve_import_row`/`stock_import.resolve_
    import_row`, il n'existe pas de correction ligne par ligne : une
    ligne unresolvable de ce module (reference/sens/quantite/prix/
    configuration comptable manquants) fait partie d'un GROUPE non
    materialise dans son ensemble — la seule action disponible est
    d'ecarter la ligne (et de corriger le fichier source pour un
    reimport), jamais une correction partielle qui recreerait la facture
    a moitie. Simplification assumee et documentee."""
    if not discard:
        raise ValidationError(
            _(
                "Une ligne d'import de facture non résoluble ne peut être "
                "qu'écartée — corrigez le fichier source et réimportez."
            )
        )
    row.status = AccInvoiceImportRow.STATUS_DISCARDED
    row.save(update_fields=["status"])
    return row


def ensure_qualification_approval_rule(tenant: Tenant) -> ApprovalRule:
    """Cree, si elle n'existe pas encore, LA regle d'approbation de
    qualification des lignes d'import de factures pour ce tenant — meme
    patron que `cash_journal_import.ensure_qualification_approval_rule`/
    `stock_import.ensure_qualification_approval_rule`."""
    content_type = ContentType.objects.get_for_model(AccInvoiceImportRow)
    rule, _created = ApprovalRule.objects.get_or_create(
        tenant=tenant,
        content_type=content_type,
        name=QUALIFICATION_RULE_NAME,
        defaults={"approver_role": "direction", "condition": {"requires_placeholder": True}},
    )
    return rule


def qualify_import_row(
    row: AccInvoiceImportRow,
    *,
    variant_id: UUID | None = None,
    account: AccAccount | None = None,
    tax_account: AccAccount | None = None,
    partner_id: UUID | None = None,
    qualified_by: User,
) -> AccInvoiceImportRow:
    """Remplace le(s) placeholder(s) d'une ligne `needs_qualification` par
    l'entite reelle fournie par l'utilisateur.

    **Simplification v1 assumee** : `variant_id` est une donnee
    d'IDENTIFICATION pure (jamais materialisee sur `AccMoveLine`, cf.
    docstring de module) — la corriger ne touche jamais le `AccMove`.
    `account`/`tax_account` retrouvent leur `AccMoveLine` sur le `AccMove`
    partage du groupe par correspondance de compte placeholder (le
    compte d'attente unique du tenant identifie sans ambiguite la ligne a
    corriger, puisqu'aucune autre ligne reelle n'utilise ce compte)."""
    if row.status != AccInvoiceImportRow.STATUS_NEEDS_QUALIFICATION:
        raise ValidationError(_("Seule une ligne « à qualifier » peut être qualifiée."))
    move = row.move
    if move is None:
        raise ValidationError(_("Cette ligne n'a pas d'écriture associée à qualifier."))

    requires_approval = (
        row.uses_placeholder_partner
        or row.uses_placeholder_variant
        or row.uses_placeholder_account
        or row.uses_placeholder_tax
    )

    update_fields = [
        "resolved_variant_id",
        "resolved_account",
        "resolved_tax_account",
        "partner_id",
        "uses_placeholder_variant",
        "uses_placeholder_account",
        "uses_placeholder_tax",
        "uses_placeholder_partner",
        "status",
    ]

    if variant_id is not None and row.uses_placeholder_variant:
        row.resolved_variant_id = variant_id
        row.uses_placeholder_variant = False

    designation = str(row.raw_data.get("designation") or "")

    if account is not None and row.uses_placeholder_account and row.resolved_account_id:
        # Filtre par compte placeholder ET libelle — le compte d'attente
        # est unique par tenant mais un meme groupe (facture multi-lignes)
        # peut compter plusieurs lignes placeholder simultanees, le
        # libelle (designation source) les distingue sans ambiguite.
        line = move.lines.filter(account_id=row.resolved_account_id, label=designation).first()
        if line is not None:
            line.account = account
            line.save(update_fields=["account"])
        row.resolved_account = account
        row.uses_placeholder_account = False

    if tax_account is not None and row.uses_placeholder_tax and row.resolved_tax_account_id:
        line = move.lines.filter(
            account_id=row.resolved_tax_account_id, label=f"TVA — {designation}"
        ).first()
        if line is not None:
            line.account = tax_account
            line.save(update_fields=["account"])
        row.resolved_tax_account = tax_account
        row.uses_placeholder_tax = False

    if partner_id is not None and row.uses_placeholder_partner:
        move.partner_id = partner_id
        move.save(update_fields=["partner_id"])
        move.lines.filter(partner_id=row.partner_id).update(partner_id=partner_id)
        row.partner_id = partner_id
        row.uses_placeholder_partner = False

    if requires_approval:
        rule = ensure_qualification_approval_rule(row.tenant)
        if rule.is_active:
            approval_request = approvals.request_approval(row, rule, qualified_by)
            row.status = AccInvoiceImportRow.STATUS_PENDING_APPROVAL
            row.qualification_approval_request = approval_request
            update_fields.append("qualification_approval_request")
            row.save(update_fields=update_fields)
            return row

    row.status = AccInvoiceImportRow.STATUS_QUALIFIED
    row.save(update_fields=update_fields)
    return row


def decide_qualification(
    approval_request: ApprovalRequest, decided_by: User, *, approved: bool, comment: str = ""
) -> AccInvoiceImportRow:
    """Enveloppe fine de `apps.core.services.approvals.decide` — meme
    patron que les 2 autres importeurs retrofites (Q4/Q5)."""
    approvals.decide(approval_request, decided_by, approved=approved, comment=comment)
    row = AccInvoiceImportRow.objects.get(qualification_approval_request=approval_request)
    row.status = (
        AccInvoiceImportRow.STATUS_QUALIFIED
        if approved
        else AccInvoiceImportRow.STATUS_NEEDS_QUALIFICATION
    )
    row.save(update_fields=["status"])
    return row
