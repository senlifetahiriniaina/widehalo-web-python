"""STK-11 (Phase 3 §12.2/§12.3, sprint A5) : deux gardes d'integrite posees
en base, pas seulement en Python — meme discipline « une garantie
applicative seule est contournable, une garantie base ne l'est pas, y
compris pour le proprietaire de la table » que `core_audit_log`
(core.0010) et `AccMove`/RG-ACC-2 (accounting.0003/0005), reprise ici pour
`catalog` :

1. `catalog_product_template.base_uom_id` devient immuable des qu'AU MOINS
   UN `StkMove` `done` existe pour une variante de ce template (« l'unite
   de stock est unique et immuable apres le premier mouvement »).
2. `catalog_product_variant.is_lot_tracked` ne peut pas passer de
   `false` a `true` si le stock physique (emplacements INTERNES
   uniquement, meme perimetre que `stocks.services.quants.on_hand_qty`) de
   cette variante n'est pas nul (« le passage de non a oui n'est possible
   qu'a stock nul »). Le sens inverse (oui -> non) n'est pas contraint par
   le CDC.

Les deux triggers referencent directement `stk_move`/`stk_quant`/
`stk_location` en SQL brut : AUCUN import Python `apps.stocks.*` n'est
ajoute a `catalog` (qui ne declare toujours pas `stocks` comme dependance,
cf. `catalog/module.py`) — une trigger Postgres n'est pas un import Python
et n'est donc pas soumise a la regle de couplage n1
(`tests/architecture/test_module_boundaries.py` ne scanne que les imports
Python). Ceci evite d'introduire une dependance inverse `catalog -> stocks`
qui casserait le sens unique etabli par `stocks/module.py`
(`stocks -> catalog`, jamais l'inverse)."""

from django.db import migrations

TEMPLATE_UOM_IMMUTABLE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION catalog_product_template_reject_uom_change_after_movement()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.base_uom_id IS DISTINCT FROM OLD.base_uom_id THEN
        IF EXISTS (
            SELECT 1
            FROM stk_move
            JOIN catalog_product_variant ON catalog_product_variant.id = stk_move.variant_id
            WHERE catalog_product_variant.template_id = OLD.id
              AND stk_move.state = 'done'
        ) THEN
            RAISE EXCEPTION
                'unite de stock immuable apres le premier mouvement valide '
                '(template id=%) : creer un nouvel article plutot que de '
                'changer son unite',
                OLD.id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

TEMPLATE_UOM_IMMUTABLE_TRIGGER_SQL = """
CREATE TRIGGER catalog_product_template_uom_immutable_after_movement
BEFORE UPDATE ON catalog_product_template
FOR EACH ROW EXECUTE FUNCTION catalog_product_template_reject_uom_change_after_movement();
"""

VARIANT_LOT_TRACKING_FLIP_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION catalog_product_variant_reject_lot_tracking_flip_with_stock()
RETURNS TRIGGER AS $$
DECLARE
    on_hand numeric;
BEGIN
    IF NEW.is_lot_tracked IS DISTINCT FROM OLD.is_lot_tracked AND NEW.is_lot_tracked THEN
        SELECT COALESCE(SUM(stk_quant.qty), 0) INTO on_hand
        FROM stk_quant
        JOIN stk_location ON stk_location.id = stk_quant.location_id
        WHERE stk_quant.variant_id = OLD.id
          AND stk_location.type = 'interne';
        IF on_hand <> 0 THEN
            RAISE EXCEPTION
                'passage en gestion par lot refuse : le stock physique de '
                'cette variante n''est pas nul (variant id=%, stock=%)',
                OLD.id, on_hand;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

VARIANT_LOT_TRACKING_FLIP_TRIGGER_SQL = """
CREATE TRIGGER catalog_product_variant_lot_tracking_flip_guard
BEFORE UPDATE ON catalog_product_variant
FOR EACH ROW EXECUTE FUNCTION catalog_product_variant_reject_lot_tracking_flip_with_stock();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0012_productvariant_is_lot_tracked"),
        ("stocks", "0014_alter_stkmove_move_type"),
    ]

    operations = [
        migrations.RunSQL(
            sql=TEMPLATE_UOM_IMMUTABLE_FUNCTION_SQL,
            reverse_sql=(
                "DROP FUNCTION IF EXISTS "
                "catalog_product_template_reject_uom_change_after_movement() CASCADE"
            ),
        ),
        migrations.RunSQL(
            sql=TEMPLATE_UOM_IMMUTABLE_TRIGGER_SQL,
            reverse_sql=(
                "DROP TRIGGER IF EXISTS catalog_product_template_uom_immutable_after_movement "
                "ON catalog_product_template"
            ),
        ),
        migrations.RunSQL(
            sql=VARIANT_LOT_TRACKING_FLIP_FUNCTION_SQL,
            reverse_sql=(
                "DROP FUNCTION IF EXISTS "
                "catalog_product_variant_reject_lot_tracking_flip_with_stock() CASCADE"
            ),
        ),
        migrations.RunSQL(
            sql=VARIANT_LOT_TRACKING_FLIP_TRIGGER_SQL,
            reverse_sql=(
                "DROP TRIGGER IF EXISTS catalog_product_variant_lot_tracking_flip_guard "
                "ON catalog_product_variant"
            ),
        ),
    ]
