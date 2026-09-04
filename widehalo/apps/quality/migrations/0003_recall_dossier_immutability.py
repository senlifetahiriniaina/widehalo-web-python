"""QUA-6/QUA-7 (Bloc D, D4) : immuabilite technique d'un `QltRecallDossier`
DES SA CREATION, pas seulement conventionnelle — `services/recall.py`
n'expose aujourd'hui aucun chemin de mutation hors `close_recall`, mais
rien n'empechait un acces ORM/admin/shell direct de contourner cette
discipline (aucun `save()`/`clean()` de modele ne la fait respecter).
Meme discipline « une garantie applicative seule est contournable, une
garantie base ne l'est pas » que `stk_move`/`acc_move`
(stocks.0015/accounting.0003-0005).

Contrairement a `StkMove` (mutable tant que `state != 'done'`), un
`QltRecallDossier` n'a pas d'etape "brouillon" avant d'etre "genere" — il
est immuable DES SA CREATION, seuls les champs de la cloture
(`state`/`closed_by`/`closed_at`/`closing_reason`) restent modifiables
(meme exception que `invoice_state` pour `AccMove`). Champs proteges :
`reference`, `reason`, `lot_variant_id`, `lot_name`, `genealogy_snapshot`,
`impacted_lots`, `initiated_by_id`, `initiated_at`, `content_type_id`,
`object_id`. Volontairement EXCLUS (meme choix que `stk_move`/`acc_move`) :
les champs de suivi communs `BaseModel`
(`is_active`/`archived_at`/`created_by`/`updated_by`/`updated_at`) — un
`soft_delete()` reste possible.

DELETE toujours bloque (QUA-7, ajout-seul) — aucune notion de
correction par document inverse ici (contrairement a `StkMove`/`reverse_
move`) : un dossier de rappel erronement declare se cloture avec un motif
expliquant l'erreur, il ne se supprime jamais."""

from django.db import migrations

RECALL_DOSSIER_IMMUTABLE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION qlt_recall_dossier_reject_mutation()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'qlt_recall_dossier (id=%) est immuable : suppression '
            'interdite (QUA-6/QUA-7)',
            OLD.id;
    END IF;

    IF NEW.reference IS DISTINCT FROM OLD.reference OR
        NEW.reason IS DISTINCT FROM OLD.reason OR
        NEW.lot_variant_id IS DISTINCT FROM OLD.lot_variant_id OR
        NEW.lot_name IS DISTINCT FROM OLD.lot_name OR
        NEW.genealogy_snapshot IS DISTINCT FROM OLD.genealogy_snapshot OR
        NEW.impacted_lots IS DISTINCT FROM OLD.impacted_lots OR
        NEW.initiated_by_id IS DISTINCT FROM OLD.initiated_by_id OR
        NEW.initiated_at IS DISTINCT FROM OLD.initiated_at OR
        NEW.content_type_id IS DISTINCT FROM OLD.content_type_id OR
        NEW.object_id IS DISTINCT FROM OLD.object_id
    THEN
        RAISE EXCEPTION
            'qlt_recall_dossier (id=%) est immuable : seule la cloture '
            '(state/closed_by/closed_at/closing_reason) reste modifiable',
            OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

RECALL_DOSSIER_IMMUTABLE_TRIGGER_SQL = """
CREATE TRIGGER qlt_recall_dossier_immutable
BEFORE UPDATE OR DELETE ON qlt_recall_dossier
FOR EACH ROW EXECUTE FUNCTION qlt_recall_dossier_reject_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("quality", "0002_qltrecalldossier"),
    ]

    operations = [
        migrations.RunSQL(
            sql=RECALL_DOSSIER_IMMUTABLE_FUNCTION_SQL,
            reverse_sql="DROP FUNCTION IF EXISTS qlt_recall_dossier_reject_mutation() CASCADE",
        ),
        migrations.RunSQL(
            sql=RECALL_DOSSIER_IMMUTABLE_TRIGGER_SQL,
            reverse_sql="DROP TRIGGER IF EXISTS qlt_recall_dossier_immutable ON qlt_recall_dossier",
        ),
    ]
