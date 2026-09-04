"""STK-9 (Phase 3 §7.3, sprint A6, mode degrade terrain) : etend le trigger
d'immuabilite pose en A5 (`stocks.0015`, fonction
`stk_move_reject_mutation_if_done`) pour proteger aussi le nouveau champ
`StkMove.client_uuid` une fois le mouvement `done` — meme patron exact que
l'evolution `accounting.0003` -> `accounting.0005` (`CREATE OR REPLACE
FUNCTION`, jamais retoucher le fichier de migration deja pousse qui a
introduit le trigger).

`client_uuid` est ecrit une seule fois, a la creation (`services.scan.
sync_scan_reception_line`), jamais retouche par un flux legitime ensuite —
meme raisonnement que `picking_id`, deja exclu de la garde en A5 sans
consequence puisqu'il est affecte avant validation. Le proteger ici reste
neanmoins coherent avec la discipline « ceinture et bretelles » deja
appliquee a tous les autres champs identifiants du mouvement (variant_id,
lot_id, reverses_id...) — une mutation de la clef d'idempotence sur un
mouvement deja valide n'a aucun scenario legitime, et casserait
silencieusement la tracabilite du journal d'audit (`AuditLog`, cf.
`services.scan`) si elle etait permise.

Contrairement a `accounting.0005` (qui utilise volontairement
`reverse_sql=migrations.RunSQL.noop`, cas asymetrique documente dans son
propre fichier), cette migration EST symetriquement reversible : redescendre
restaure exactement la fonction de `stocks.0015` (sans la clause
`client_uuid`), aucun besoin de conserver un « sur-ensemble sûr » puisque
`stocks.0015` etait deja field-aware des le depart (pas de version
« blunt » intermediaire ici, cf. docstring de `0015`)."""

from django.db import migrations

MOVE_IMMUTABLE_FUNCTION_SQL_WITH_CLIENT_UUID = """
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
        NEW.picking_id IS DISTINCT FROM OLD.picking_id OR
        NEW.client_uuid IS DISTINCT FROM OLD.client_uuid
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

MOVE_IMMUTABLE_FUNCTION_SQL_WITHOUT_CLIENT_UUID = """
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


class Migration(migrations.Migration):
    dependencies = [
        ("stocks", "0016_stkmove_client_uuid"),
    ]

    operations = [
        migrations.RunSQL(
            sql=MOVE_IMMUTABLE_FUNCTION_SQL_WITH_CLIENT_UUID,
            reverse_sql=MOVE_IMMUTABLE_FUNCTION_SQL_WITHOUT_CLIENT_UUID,
        ),
    ]
