"""Affine l'immuabilite RG-ACC-2 : une fois publiee, une acc_move ne doit
plus jamais voir ses champs COMPTABLES changer (montants, comptes, journal,
periode, reference, etc.) — mais son statut METIER (`invoice_state` :
validee -> payee partiellement -> payee) DOIT pouvoir evoluer apres
publication, c'est meme l'objet du workflow facture (§5.1.5). Meme chose
pour acc_move_line : `reconciled_with`/`matching_number` (lettrage, etape
A5) doivent rester modifiables apres publication, le reste non.

Remplace (CREATE OR REPLACE, idempotent) les fonctions de la migration
0003 par des versions qui comparent OLD/NEW colonne par colonne au lieu de
rejeter tout UPDATE sans distinction."""

from django.db import migrations

MOVE_IMMUTABLE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION acc_move_reject_mutation_if_posted()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.state = 'posted' THEN
            RAISE EXCEPTION 'acc_move publiee est immuable (id=%) : correction par extourne uniquement', OLD.id;
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.state = 'posted' AND (
        NEW.state IS DISTINCT FROM OLD.state OR
        NEW.total_debit IS DISTINCT FROM OLD.total_debit OR
        NEW.total_credit IS DISTINCT FROM OLD.total_credit OR
        NEW.journal_id IS DISTINCT FROM OLD.journal_id OR
        NEW.period_id IS DISTINCT FROM OLD.period_id OR
        NEW.date IS DISTINCT FROM OLD.date OR
        NEW.currency IS DISTINCT FROM OLD.currency OR
        NEW.exchange_rate IS DISTINCT FROM OLD.exchange_rate OR
        NEW.reference IS DISTINCT FROM OLD.reference OR
        NEW.partner_id IS DISTINCT FROM OLD.partner_id OR
        NEW.move_type IS DISTINCT FROM OLD.move_type OR
        NEW.narration IS DISTINCT FROM OLD.narration
    ) THEN
        RAISE EXCEPTION 'acc_move publiee est immuable sur ses champs comptables (id=%) : correction par extourne uniquement', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

MOVE_LINE_IMMUTABLE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION acc_move_line_reject_mutation_if_posted()
RETURNS TRIGGER AS $$
DECLARE
    parent_state text;
BEGIN
    SELECT state INTO parent_state FROM acc_move WHERE id = OLD.move_id;

    IF TG_OP = 'DELETE' THEN
        IF parent_state = 'posted' THEN
            RAISE EXCEPTION 'ligne d''une acc_move publiee est immuable (move_id=%)', OLD.move_id;
        END IF;
        RETURN OLD;
    END IF;

    IF parent_state = 'posted' AND (
        NEW.account_id IS DISTINCT FROM OLD.account_id OR
        NEW.partner_id IS DISTINCT FROM OLD.partner_id OR
        NEW.label IS DISTINCT FROM OLD.label OR
        NEW.debit IS DISTINCT FROM OLD.debit OR
        NEW.credit IS DISTINCT FROM OLD.credit OR
        NEW.amount_currency IS DISTINCT FROM OLD.amount_currency OR
        NEW.currency IS DISTINCT FROM OLD.currency OR
        NEW.tax_id IS DISTINCT FROM OLD.tax_id OR
        NEW.tax_base IS DISTINCT FROM OLD.tax_base OR
        NEW.analytic_distribution IS DISTINCT FROM OLD.analytic_distribution OR
        NEW.due_date IS DISTINCT FROM OLD.due_date
    ) THEN
        RAISE EXCEPTION 'ligne d''une acc_move publiee est immuable sur ses champs comptables (move_id=%)', OLD.move_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0004_accpaymentterm_accpaymenttermline_acctax_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql=MOVE_IMMUTABLE_FUNCTION_SQL,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql=MOVE_LINE_IMMUTABLE_FUNCTION_SQL,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
