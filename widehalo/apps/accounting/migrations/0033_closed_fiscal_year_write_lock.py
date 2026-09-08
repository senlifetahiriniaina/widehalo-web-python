"""T2 (ACC-10) — le verrou d'ecriture passe de la PERIODE a l'EXERCICE.

**Le critere** : « Un exercice clos refuse toute ecriture, y compris par
appel direct de l'API et y compris pour un utilisateur administrateur. »

`0031` a mis le refus en base pour une PERIODE close, et sa docstring dit
pourquoi : « une garantie applicative seule est contournable, une garantie
base ne l'est pas, y compris pour le proprietaire de la table ». C'est le
meme raisonnement qui impose cette migration-ci, parce que le critere parle
d'exercice et que le verrou de periode ne s'y substitue pas.

**Le trou exact, et il n'est pas theorique.** `close_fiscal_year` ferme
toutes les periodes de l'exercice en meme temps que lui. Mais rien
n'empechait, ensuite, de creer une periode NEUVE — donc ouverte par defaut
— rattachee a cet exercice clos, et d'y publier. Le trigger de `0031`
n'aurait rien vu : la periode, elle, etait bien ouverte. Une clôture
annuelle qu'on rouvre en creant une treizieme periode n'est pas une
clôture.

**Deux verrous, pas un.**

1. `acc_move_reject_post_in_closed_period` regarde desormais AUSSI l'etat
   de l'exercice de la periode visee. Une ecriture ne peut donc plus etre
   publiee dans un exercice clos, quelle que soit la periode empruntee.
2. `acc_period_reject_open_in_closed_year` refuse en plus qu'une periode
   OUVERTE naisse ou reapparaisse dans un exercice clos. Sans lui, le
   premier verrou tiendrait quand meme — mais la base porterait des
   periodes ouvertes dans un exercice clos, un etat que personne ne sait
   lire et que tout ecran afficherait de travers.

**Ce que ces verrous NE font pas**, et c'est deliberé : ils ne touchent pas
aux brouillons. Preparer une ecriture dans un exercice clos reste legitime
(on la publiera apres reouverture, ou on la repositionnera) — meme portee
etroite que `0031`, et pour la meme raison. Ils n'empechent pas non plus de
CLORE un exercice contenant deja des ecritures publiees : sans quoi aucune
clôture ne serait possible.
"""

from __future__ import annotations

from django.db import migrations

MOVE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION acc_move_reject_post_in_closed_period()
RETURNS TRIGGER AS $$
DECLARE
    period_state text;
    year_state text;
    year_code text;
BEGIN
    -- Ne regarde que les ecritures qui DEVIENNENT publiees : un brouillon
    -- dans une periode close reste parfaitement legitime.
    IF NEW.state <> 'posted' THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.state = 'posted' THEN
        RETURN NEW;
    END IF;

    SELECT p.state, y.state, y.code
      INTO period_state, year_state, year_code
      FROM acc_period p
      JOIN acc_fiscal_year y ON y.id = p.fiscal_year_id
     WHERE p.id = NEW.period_id;

    IF year_state = 'closed' THEN
        RAISE EXCEPTION
            'exercice clos (%) : publication d''ecriture refusee (move_id=%)',
            year_code, NEW.id;
    END IF;
    IF period_state = 'closed' THEN
        RAISE EXCEPTION
            'periode close (period_id=%) : publication d''ecriture refusee (move_id=%)',
            NEW.period_id, NEW.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# La version de `0031`, mot pour mot : c'est ce que `reverse_sql` doit
# restaurer pour qu'une annulation de migration laisse une base coherente
# plutot qu'une fonction supprimee et un trigger orphelin.
MOVE_FUNCTION_SQL_0031 = """
CREATE OR REPLACE FUNCTION acc_move_reject_post_in_closed_period()
RETURNS TRIGGER AS $$
DECLARE
    period_state text;
BEGIN
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

PERIOD_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION acc_period_reject_open_in_closed_year()
RETURNS TRIGGER AS $$
DECLARE
    year_state text;
    year_code text;
BEGIN
    -- Une periode CLOSE dans un exercice clos est l'etat normal : c'est
    -- exactement ce que `close_fiscal_year` produit.
    IF NEW.state <> 'open' THEN
        RETURN NEW;
    END IF;

    SELECT state, code INTO year_state, year_code
      FROM acc_fiscal_year WHERE id = NEW.fiscal_year_id;

    IF year_state = 'closed' THEN
        RAISE EXCEPTION
            'exercice clos (%) : periode ouverte refusee (period_id=%)',
            year_code, NEW.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

PERIOD_TRIGGER_SQL = """
CREATE TRIGGER acc_period_no_open_in_closed_year
BEFORE INSERT OR UPDATE ON acc_period
FOR EACH ROW EXECUTE FUNCTION acc_period_reject_open_in_closed_year();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0032_seed_vat_thresholds"),
    ]

    operations = [
        migrations.RunSQL(sql=MOVE_FUNCTION_SQL, reverse_sql=MOVE_FUNCTION_SQL_0031),
        migrations.RunSQL(
            sql=PERIOD_FUNCTION_SQL,
            reverse_sql="DROP FUNCTION IF EXISTS acc_period_reject_open_in_closed_year() CASCADE",
        ),
        migrations.RunSQL(
            sql=PERIOD_TRIGGER_SQL,
            reverse_sql="DROP TRIGGER IF EXISTS acc_period_no_open_in_closed_year ON acc_period",
        ),
    ]
