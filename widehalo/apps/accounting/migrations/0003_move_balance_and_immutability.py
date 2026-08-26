"""RG-ACC-1 (partie double) et RG-ACC-2 (immuabilite) : verifiees en base,
pas seulement en service (cf. apps/accounting/services/moves.py) — meme
discipline que core_audit_log (Lot 1, etape 10) et que la RLS (etape 3) :
une garantie applicative seule est contournable, une garantie base ne
l'est pas, y compris pour le proprietaire de la table."""

from django.db import migrations

BALANCE_CHECK_SQL = """
ALTER TABLE acc_move
ADD CONSTRAINT acc_move_balanced_when_posted
CHECK (state <> 'posted' OR total_debit = total_credit);
"""

MOVE_IMMUTABLE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION acc_move_reject_mutation_if_posted()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.state = 'posted' THEN
        RAISE EXCEPTION 'acc_move publiee est immuable (id=%) : correction par extourne uniquement', OLD.id;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

MOVE_IMMUTABLE_TRIGGER_SQL = """
CREATE TRIGGER acc_move_immutable_when_posted
BEFORE UPDATE OR DELETE ON acc_move
FOR EACH ROW EXECUTE FUNCTION acc_move_reject_mutation_if_posted();
"""

MOVE_LINE_IMMUTABLE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION acc_move_line_reject_mutation_if_posted()
RETURNS TRIGGER AS $$
DECLARE
    parent_state text;
BEGIN
    SELECT state INTO parent_state FROM acc_move WHERE id = OLD.move_id;
    IF parent_state = 'posted' THEN
        RAISE EXCEPTION 'ligne d''une acc_move publiee est immuable (move_id=%)', OLD.move_id;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

MOVE_LINE_IMMUTABLE_TRIGGER_SQL = """
CREATE TRIGGER acc_move_line_immutable_when_posted
BEFORE UPDATE OR DELETE ON acc_move_line
FOR EACH ROW EXECUTE FUNCTION acc_move_line_reject_mutation_if_posted();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0002_accmove_accmoveline_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql=BALANCE_CHECK_SQL,
            reverse_sql="ALTER TABLE acc_move DROP CONSTRAINT IF EXISTS acc_move_balanced_when_posted",
        ),
        migrations.RunSQL(
            sql=MOVE_IMMUTABLE_FUNCTION_SQL,
            reverse_sql="DROP FUNCTION IF EXISTS acc_move_reject_mutation_if_posted() CASCADE",
        ),
        migrations.RunSQL(
            sql=MOVE_IMMUTABLE_TRIGGER_SQL,
            reverse_sql="DROP TRIGGER IF EXISTS acc_move_immutable_when_posted ON acc_move",
        ),
        migrations.RunSQL(
            sql=MOVE_LINE_IMMUTABLE_FUNCTION_SQL,
            reverse_sql="DROP FUNCTION IF EXISTS acc_move_line_reject_mutation_if_posted() CASCADE",
        ),
        migrations.RunSQL(
            sql=MOVE_LINE_IMMUTABLE_TRIGGER_SQL,
            reverse_sql="DROP TRIGGER IF EXISTS acc_move_line_immutable_when_posted ON acc_move_line",
        ),
    ]
