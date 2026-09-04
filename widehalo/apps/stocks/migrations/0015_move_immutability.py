"""STK-11 (Phase 3 §13.1, sprint A5) : immuabilite technique d'un
`StkMove` valide (`state='done'`), pas seulement conventionnelle —
`services.moves.validate_move`/`cancel_move`/`reverse_move` refusent deja
toute mutation d'un mouvement `done` au niveau service, mais rien
n'empechait un acces ORM/admin/shell direct de contourner ces gardes
(aucun `save()`/`clean()` de modele ne les fait respecter). Meme discipline
« une garantie applicative seule est contournable, une garantie base ne
l'est pas » que `core_audit_log` (core.0010) et `AccMove`/RG-ACC-2
(accounting.0003/0005) — meme patron « field-aware » directement (compare
OLD/NEW colonne par colonne des la premiere version, pas d'etape 0003
« blunt » intermediaire a affiner ensuite comme pour `AccMove`, ce
mouvement n'a pas de champ metier equivalent a `invoice_state` qui
justifierait une evolution en deux temps).

Champs proteges une fois `done` : tout ce qui definit le mouvement lui-meme
(`variant_id`, `lot_id`, `qty`, `uom`, `location_from_id`,
`location_to_id`, `date`, `move_type`, `source_document`,
`unit_cost_mga`, `value_mga`, `operator_id`, `reverses_id`,
`cancel_reason`, `picking_id`, `state`). Volontairement EXCLUS (meme choix
que `AccMove`) : les champs de suivi communs `BaseModel`
(`is_active`/`archived_at`/`created_by`/`updated_by`/`updated_at`) — un
`soft_delete()` reste possible sur un mouvement `done`, symetrique au
comportement deja en place pour `AccMove`, pas un gap introduit ici.

DELETE egalement bloque une fois `done` (correction uniquement par
`services.moves.reverse_move`, qui cree un nouveau mouvement et ne touche
jamais l'original). `picking_id` est protege ici alors qu'il EST ecrit par
`services.pickings.add_picking_line` (`move.picking = picking;
move.save(update_fields=["picking"])`) — sans consequence : cette
affectation a lieu juste apres `create_move` (le mouvement est encore
`draft` a ce moment, `validate_move` ne le passe a `done` qu'ensuite), donc
`OLD.state` vaut `draft` a cet instant precis et le trigger ne se
declenche pas."""

from django.db import migrations

MOVE_IMMUTABLE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION stk_move_reject_mutation_if_done()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.state = 'done' THEN
            RAISE EXCEPTION
                'stk_move valide (id=%) est immuable : correction par '
                'mouvement inverse (reverse_move) uniquement',
                OLD.id;
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.state = 'done' AND (
        NEW.state IS DISTINCT FROM OLD.state OR
        NEW.variant_id IS DISTINCT FROM OLD.variant_id OR
        NEW.lot_id IS DISTINCT FROM OLD.lot_id OR
        NEW.qty IS DISTINCT FROM OLD.qty OR
        NEW.uom IS DISTINCT FROM OLD.uom OR
        NEW.location_from_id IS DISTINCT FROM OLD.location_from_id OR
        NEW.location_to_id IS DISTINCT FROM OLD.location_to_id OR
        NEW.date IS DISTINCT FROM OLD.date OR
        NEW.move_type IS DISTINCT FROM OLD.move_type OR
        NEW.source_document IS DISTINCT FROM OLD.source_document OR
        NEW.unit_cost_mga IS DISTINCT FROM OLD.unit_cost_mga OR
        NEW.value_mga IS DISTINCT FROM OLD.value_mga OR
        NEW.operator_id IS DISTINCT FROM OLD.operator_id OR
        NEW.reverses_id IS DISTINCT FROM OLD.reverses_id OR
        NEW.cancel_reason IS DISTINCT FROM OLD.cancel_reason OR
        NEW.picking_id IS DISTINCT FROM OLD.picking_id
    ) THEN
        RAISE EXCEPTION
            'stk_move valide (id=%) est immuable : correction par '
            'mouvement inverse (reverse_move) uniquement',
            OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

MOVE_IMMUTABLE_TRIGGER_SQL = """
CREATE TRIGGER stk_move_immutable_when_done
BEFORE UPDATE OR DELETE ON stk_move
FOR EACH ROW EXECUTE FUNCTION stk_move_reject_mutation_if_done();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("stocks", "0014_alter_stkmove_move_type"),
    ]

    operations = [
        migrations.RunSQL(
            sql=MOVE_IMMUTABLE_FUNCTION_SQL,
            reverse_sql="DROP FUNCTION IF EXISTS stk_move_reject_mutation_if_done() CASCADE",
        ),
        migrations.RunSQL(
            sql=MOVE_IMMUTABLE_TRIGGER_SQL,
            reverse_sql="DROP TRIGGER IF EXISTS stk_move_immutable_when_done ON stk_move",
        ),
    ]
