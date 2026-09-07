"""Le calendrier férié quitte `forecast` pour `core` — état Django seul.

`state_operations` UNIQUEMENT : Django oublie que ce modèle lui appartient,
et PostgreSQL ne touche à rien. La table est reprise telle quelle par
`core/migrations/0038_holiday.py`, qui la renomme ensuite en place. Aucune
ligne n'est copiée, aucune n'est perdue, et la migration est instantanée
quelle que soit la taille de la table.

Le motif du déplacement est dans `apps/core/models/calendar.py`.
"""

from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("forecast", "0001_initial")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.DeleteModel(name="ForHoliday")],
            database_operations=[],
        )
    ]
