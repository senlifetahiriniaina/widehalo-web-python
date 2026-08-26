from django.db import migrations

TRIGGER_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION core_audit_log_reject_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'core_audit_log est immuable : UPDATE/DELETE interdits (tentative sur id=%)',
        OLD.id;
END;
$$ LANGUAGE plpgsql;
"""

TRIGGER_SQL = """
CREATE TRIGGER core_audit_log_immutable
BEFORE UPDATE OR DELETE ON core_audit_log
FOR EACH ROW EXECUTE FUNCTION core_audit_log_reject_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0009_regulatory_parameter_no_overlap"),
    ]

    operations = [
        migrations.RunSQL(
            sql=TRIGGER_FUNCTION_SQL,
            reverse_sql="DROP FUNCTION IF EXISTS core_audit_log_reject_mutation() CASCADE",
        ),
        migrations.RunSQL(
            sql=TRIGGER_SQL,
            reverse_sql="DROP TRIGGER IF EXISTS core_audit_log_immutable ON core_audit_log",
        ),
    ]
