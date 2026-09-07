"""Les deux modèles de validation passent sous `BaseModel`, donc sous RLS.

**Couche 2 de la correction d'isolation.** La couche 1 (commit précédent) a
fermé la fuite dans `services/approvals.py` : un validateur ne voit plus les
demandes des autres sociétés. Elle repose sur un filtre applicatif — un seul
niveau. Cette migration pose le filet en dessous : colonne de société portée
par la ligne, `TenantManager` en lecture, et policy PostgreSQL.

**`ApprovalRule` ne change presque rien en base.** `id` et `is_active`
étaient déjà identiques à ceux de `BaseModel`. Seuls les champs d'audit sont
ajoutés, et `on_delete` passe de CASCADE à PROTECT — une correction :
supprimer une société qui porte des règles de validation ne doit pas les
emporter en silence. Les chemins de purge (`sandbox`, `tenant_reset`)
parcourent tous les `BaseModel` et les prennent donc désormais en charge.

**`ApprovalRequest` gagne une colonne qu'elle n'avait pas.** Son
rattachement passait uniquement par `rule.tenant_id` — une jointure, donc
quelque chose qu'une requête peut oublier, et qu'elle a effectivement
oublié. La colonne est ajoutée en trois temps (nullable, remplie depuis la
règle, rendue obligatoire) : une seule passe avec `NOT NULL` échouerait sur
toute base contenant déjà des demandes.

Le remplissage lit la société de LA RÈGLE, jamais un contexte actif — une
migration s'exécute hors de toute société, et c'est la règle qui porte la
vérité du rattachement.
"""

from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import OuterRef, Subquery
from django.utils import timezone


def _remplir_la_societe_depuis_la_regle(apps, schema_editor) -> None:
    Demande = apps.get_model("core", "ApprovalRequest")
    Regle = apps.get_model("core", "ApprovalRule")
    Demande.objects.filter(tenant_id__isnull=True).update(
        tenant_id=Subquery(Regle.objects.filter(pk=OuterRef("rule_id")).values("tenant_id")[:1])
    )


def _vider_la_societe(apps, schema_editor) -> None:
    """Retour arrière : la colonne est retirée par l'opération inverse
    d'`AddField`, il n'y a donc rien à défaire ici. Écrite quand même pour
    que la migration soit réversible plutôt que bloquante."""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0038_holiday"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # --- ApprovalRule : les champs d'audit de BaseModel ---------------
        migrations.AddField(
            model_name="approvalrule",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="approvalrule",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddField(
            model_name="approvalrule",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="approvalrule",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="approvalrule",
            name="updated_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="approvalrule",
            name="tenant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, to="core.tenant"
            ),
        ),
        # --- ApprovalRequest : les champs d'audit -------------------------
        migrations.AddField(
            model_name="approvalrequest",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddField(
            model_name="approvalrequest",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="approvalrequest",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="approvalrequest",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="approvalrequest",
            name="updated_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # --- ApprovalRequest : la société, en trois temps -----------------
        migrations.AddField(
            model_name="approvalrequest",
            name="tenant",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to="core.tenant",
            ),
        ),
        migrations.RunPython(_remplir_la_societe_depuis_la_regle, _vider_la_societe),
        migrations.AlterField(
            model_name="approvalrequest",
            name="tenant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, to="core.tenant"
            ),
        ),
    ]
