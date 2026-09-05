"""L3 (RG-ACC-4) — le refus d'écriture en période close passe en base.

**Le défaut fermé ici.** `services/moves.py::post_move` refuse de publier
dans une période close — mais c'est une garde APPLICATIVE, et une garde
applicative se contourne par construction : toute écriture qui n'emprunte
pas ce service (un `AccMove.objects.create(state="posted")`, un
`queryset.update(state=...)`, un import, une commande de reprise, un accès
psql) publie sans que rien ne s'y oppose.

Le dépôt a déjà tranché ce débat, deux fois, et dans le même sens. La
docstring de `0003_move_balance_and_immutability.py` le dit mot pour mot :
« une garantie applicative seule est contournable, une garantie base ne
l'est pas, y compris pour le propriétaire de la table. » L'équilibre
débit/crédit et l'immuabilité des écritures publiées sont en base depuis la
Phase 1 ; la période close, elle, était restée en Python. C'est le seul des
trois invariants comptables à ne pas l'être.

**Portée délibérément étroite.** Le trigger refuse deux choses, et rien de
plus :

1. **INSERT** d'une écriture directement à l'état `posted` dans une période
   close ;
2. **UPDATE** faisant passer une écriture à `posted` dans une période close.

Il ne touche PAS aux brouillons : préparer une écriture dans une période
close est légitime (on la publiera après réouverture, ou on la
repositionnera). Et il n'interdit pas de FERMER une période contenant déjà
des écritures publiées — sans quoi aucune clôture ne serait possible.

**Le cas de la période changée sous une écriture publiée** est couvert par
le trigger d'immuabilité déjà en place (`acc_move_immutable_when_posted`) :
une écriture publiée ne se modifie plus du tout, période comprise.
"""

from __future__ import annotations

from django.db import migrations

CLOSED_PERIOD_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION acc_move_reject_post_in_closed_period()
RETURNS TRIGGER AS $$
DECLARE
    period_state text;
BEGIN
    -- Ne regarde que les ecritures qui DEVIENNENT publiees : un brouillon
    -- dans une periode close reste parfaitement legitime.
    IF NEW.state <> 'posted' THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.state = 'posted' THEN
        RETURN NEW;
    END IF;

    SELECT state INTO period_state FROM acc_period WHERE id = NEW.period_id;
    IF period_state = 'closed' THEN
        RAISE EXCEPTION
            'periode close (period_id=%) : publication d''ecriture refusee (move_id=%)',
            NEW.period_id, NEW.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

CLOSED_PERIOD_TRIGGER_SQL = """
CREATE TRIGGER acc_move_no_post_in_closed_period
BEFORE INSERT OR UPDATE ON acc_move
FOR EACH ROW EXECUTE FUNCTION acc_move_reject_post_in_closed_period();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0030_seed_vat_reference_rate"),
    ]

    operations = [
        migrations.RunSQL(
            sql=CLOSED_PERIOD_FUNCTION_SQL,
            reverse_sql="DROP FUNCTION IF EXISTS acc_move_reject_post_in_closed_period() CASCADE",
        ),
        migrations.RunSQL(
            sql=CLOSED_PERIOD_TRIGGER_SQL,
            reverse_sql="DROP TRIGGER IF EXISTS acc_move_no_post_in_closed_period ON acc_move",
        ),
    ]
