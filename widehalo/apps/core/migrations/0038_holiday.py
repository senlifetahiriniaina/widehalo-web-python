"""`core` adopte le calendrier férié et renomme sa table en place.

Trois temps, dans cet ordre et pas un autre :

1. **Adoption sans écriture** (`SeparateDatabaseAndState`) : le modèle
   `Holiday` entre dans l'état Django en désignant la table EXISTANTE
   `for_holiday`. Rien n'est créé — la table est déjà là, `forecast` vient
   simplement de la lâcher (`forecast/0002`).
2. **Renommage** : `ALTER TABLE "for_holiday" RENAME TO "core_holiday"`.
   PostgreSQL renomme sans copier ; la policy de Row-Level Security suit la
   table (elle est attachée à son OID, pas à son nom), donc l'isolation
   n'est jamais interrompue, pas même le temps de la migration.
3. **Renommage de la contrainte** : `uniq_for_holiday_date` porte un
   préfixe qui ne veut plus rien dire dans `core`. L'index unique est
   reconstruit sous son nom propre — le seul temps de travail réel de cette
   migration, négligeable sur une table qui compte quelques dizaines de
   lignes par société et par année.
"""

from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import apps.core.db.uuid7


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0037_alter_idempotencykey_unique_together_and_more"),
        # `forecast` doit avoir lâché le modèle AVANT que `core` ne
        # l'adopte : deux modèles qui revendiquent la même table dans le
        # même état rendraient l'autodétection incohérente.
        ("forecast", "0002_move_holiday_to_core"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="Holiday",
                    fields=[
                        (
                            "id",
                            models.UUIDField(
                                default=apps.core.db.uuid7.uuid7,
                                editable=False,
                                primary_key=True,
                                serialize=False,
                            ),
                        ),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        ("is_active", models.BooleanField(default=True)),
                        ("archived_at", models.DateTimeField(blank=True, null=True)),
                        ("date", models.DateField()),
                        ("name", models.CharField(max_length=120)),
                        (
                            "created_by",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="+",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "tenant",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.PROTECT, to="core.tenant"
                            ),
                        ),
                        (
                            "updated_by",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="+",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "db_table": "for_holiday",
                        "ordering": ["date"],
                    },
                ),
                migrations.AddConstraint(
                    model_name="holiday",
                    constraint=models.UniqueConstraint(
                        fields=("tenant", "date"), name="uniq_for_holiday_date"
                    ),
                ),
            ],
            database_operations=[],
        ),
        migrations.AlterModelTable(name="holiday", table="core_holiday"),
        migrations.RemoveConstraint(model_name="holiday", name="uniq_for_holiday_date"),
        migrations.AddConstraint(
            model_name="holiday",
            constraint=models.UniqueConstraint(
                fields=("tenant", "date"), name="uniq_core_holiday_date"
            ),
        ),
    ]
