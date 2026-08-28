"""RG-STK-1 (double entree) : la seule garantie DB qui a un sens sur
`stk_move` (cf. docstring `StkMove` dans models.py — la somme algebrique
nulle par produit est vraie PAR CONSTRUCTION du modele, garantie
uniquement par le test de propriete Hypothesis, pas par un CHECK) — meme
discipline "garantie base en plus de la garantie service" que
`acc_move_balanced_when_posted` (accounting, migration 0003)."""

from django.db import migrations

FROM_NE_TO_CHECK_SQL = """
ALTER TABLE stk_move
ADD CONSTRAINT stk_move_from_ne_to
CHECK (location_from_id <> location_to_id);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("stocks", "0002_stklot_stkmove_stkquant_stkvaluationlayer_and_more"),
    ]

    operations = [
        migrations.RunSQL(sql=FROM_NE_TO_CHECK_SQL, reverse_sql=migrations.RunSQL.noop),
    ]
