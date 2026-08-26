from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_countrydefaultsprofile_regulatoryparameter_auditlog_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS btree_gist",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="""
            ALTER TABLE core_regulatory_parameter
            ADD CONSTRAINT core_regulatory_parameter_no_overlap
            EXCLUDE USING gist (
                code WITH =,
                COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid) WITH =,
                daterange(valid_from, COALESCE(valid_to, 'infinity'::date), '[]') WITH &&
            )
            """,
            reverse_sql="""
            ALTER TABLE core_regulatory_parameter
            DROP CONSTRAINT core_regulatory_parameter_no_overlap
            """,
        ),
    ]
