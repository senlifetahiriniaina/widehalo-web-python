"""Immuabilité STR-3/STR-7 (cahier §13.3, §17.2 « Immutabilité du figé » :
« un pack de revue et un budget verrouillé refusent toute modification, y
compris par l'API et pour un administrateur ») — même patron que
`apps.accounting`, migrations 0003/0005 (RG-ACC-2, immuabilité d'une
`AccMove` publiée) : un trigger Postgres, pas seulement une vérification
côté service Python, qui rejette toute écriture au niveau base.

**`stg_budget` reste conscient des champs (comme la migration accounting
0005, pas 0003)** : une fois verrouillé, les CHIFFRES engagés
(`lines`/`name`/`period_*`/`source_*`/`version`/`previous_version_id`)
deviennent immuables, mais `variance_comments` doit RESTER modifiable —
STR-6 exige un commentaire de gestion sur une ligne en écart AVANT la
clôture de la REVUE, un processus qui se déroule justement APRÈS le
verrouillage du budget (on commente un écart contre des chiffres déjà
figés, jamais avant). Bloquer `variance_comments` au verrouillage rendrait
STR-6 impossible à satisfaire."""

from django.db import migrations

BUDGET_IMMUTABLE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION stg_budget_reject_mutation_if_locked()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.is_locked THEN
            RAISE EXCEPTION 'stg_budget verrouille est immuable (id=%) : creez une nouvelle version', OLD.id;
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.is_locked AND (
        NEW.lines IS DISTINCT FROM OLD.lines OR
        NEW.name IS DISTINCT FROM OLD.name OR
        NEW.period_start IS DISTINCT FROM OLD.period_start OR
        NEW.period_end IS DISTINCT FROM OLD.period_end OR
        NEW.source_type IS DISTINCT FROM OLD.source_type OR
        NEW.source_reference IS DISTINCT FROM OLD.source_reference OR
        NEW.version IS DISTINCT FROM OLD.version OR
        NEW.previous_version_id IS DISTINCT FROM OLD.previous_version_id OR
        NEW.is_locked IS DISTINCT FROM OLD.is_locked
    ) THEN
        RAISE EXCEPTION 'stg_budget verrouille est immuable sur ses chiffres engages (id=%) : creez une nouvelle version', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

REVIEW_PACK_IMMUTABLE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION stg_review_pack_reject_mutation()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'stg_review_pack est immuable (id=%) : jamais de suppression physique', OLD.id;
    END IF;

    IF NEW.snapshot IS DISTINCT FROM OLD.snapshot OR
       NEW.period_start IS DISTINCT FROM OLD.period_start OR
       NEW.period_end IS DISTINCT FROM OLD.period_end OR
       NEW.generated_at IS DISTINCT FROM OLD.generated_at OR
       NEW.generated_by_id IS DISTINCT FROM OLD.generated_by_id OR
       NEW.budget_id IS DISTINCT FROM OLD.budget_id
    THEN
        RAISE EXCEPTION 'stg_review_pack est immuable sur son contenu fige (id=%)', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

CREATE_TRIGGERS_SQL = """
DROP TRIGGER IF EXISTS trg_stg_budget_immutable ON stg_budget;
CREATE TRIGGER trg_stg_budget_immutable
    BEFORE UPDATE OR DELETE ON stg_budget
    FOR EACH ROW EXECUTE FUNCTION stg_budget_reject_mutation_if_locked();

DROP TRIGGER IF EXISTS trg_stg_review_pack_immutable ON stg_review_pack;
CREATE TRIGGER trg_stg_review_pack_immutable
    BEFORE UPDATE OR DELETE ON stg_review_pack
    FOR EACH ROW EXECUTE FUNCTION stg_review_pack_reject_mutation();
"""

DROP_TRIGGERS_SQL = """
DROP TRIGGER IF EXISTS trg_stg_budget_immutable ON stg_budget;
DROP TRIGGER IF EXISTS trg_stg_review_pack_immutable ON stg_review_pack;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("strategy", "0003_stgkeyresult_metric_code_stgbudget_stginitiative_and_more"),
    ]

    operations = [
        migrations.RunSQL(sql=BUDGET_IMMUTABLE_FUNCTION_SQL, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(sql=REVIEW_PACK_IMMUTABLE_FUNCTION_SQL, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(sql=CREATE_TRIGGERS_SQL, reverse_sql=DROP_TRIGGERS_SQL),
    ]
