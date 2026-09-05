"""L8 — rattrapage du dictionnaire d'indicateurs pour les tenants existants.

Le jeu de depart est charge a la creation d'un tenant
(`load_metric_dictionary`, appele par les quatre chemins de creation, meme
patron que `load_chart_of_accounts`). Les tenants deja en base, eux,
n'ont jamais rien recu : `AnMetricDefinition` etait presentee comme la
« SEULE voie declaree d'acces aux donnees decisionnelles » et rien ne la
peuplait. Cette migration comble ce retard, une fois.

**Sur l'import de `STARTING_METRICS` plutot qu'une copie figee ici.** Une
migration de donnees dont le contenu suit le code peut faire diverger deux
instances au meme numero de migration. Le cas ne peut pas se produire ici :
sur une base neuve il n'existe encore AUCUN tenant au moment ou cette
migration s'execute, elle ne seme donc rien — les tenants y viendront par
leur chemin de creation. Elle ne concerne que le rattrapage, ou le jeu
courant est precisement ce qu'on veut.

La table est tenant-scopee et soumise a la RLS : sans `app.tenant_id` pose,
la boucle n'ecrirait rien et le rattrapage serait un silence. Meme idiome
que `logistics/migrations/0008_encrypt_webhook_secret.py`.
"""

from __future__ import annotations

from django.db import migrations


def seed_existing_tenants(apps, schema_editor) -> None:
    from apps.analytics.services.starting_metrics import STARTING_METRICS

    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return
    Tenant = apps.get_model("core", "Tenant")
    Metric = apps.get_model("analytics", "AnMetricDefinition")

    for tenant_id in Tenant.objects.values_list("id", flat=True):
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL app.tenant_id = %s", [str(tenant_id)])
        for entry in STARTING_METRICS:
            # `get_or_create` sur (tenant, code, is_current) : un tenant qui
            # aurait deja recu ce code — par la commande, jouee a la main
            # avant la migration — n'en recoit pas une seconde version.
            # Jamais un ecrasement : `AnMetricDefinition` est versionnee par
            # INSERTION (BI-9), une reprise ne doit pas reecrire une
            # definition que quelqu'un aurait deja fait evoluer.
            if Metric.objects.filter(
                tenant_id=tenant_id, code=entry["code"], is_current=True
            ).exists():
                continue
            Metric.objects.create(
                tenant_id=tenant_id,
                version=1,
                is_current=True,
                statut="publie",
                description="",
                maille_minimale=entry.get("maille_minimale", ""),
                **{
                    key: value
                    for key, value in entry.items()
                    if key not in {"maille_minimale"}
                },
            )


def unseed(apps, schema_editor) -> None:
    """Retire uniquement les lignes en version 1 encore courantes : une
    definition qu'un client a fait evoluer depuis (version >= 2) n'est pas
    du ressort de cette migration et ne doit pas disparaitre a un rollback.
    """
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return
    from apps.analytics.services.starting_metrics import STARTING_METRICS

    Tenant = apps.get_model("core", "Tenant")
    Metric = apps.get_model("analytics", "AnMetricDefinition")
    codes = [entry["code"] for entry in STARTING_METRICS]
    for tenant_id in Tenant.objects.values_list("id", flat=True):
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL app.tenant_id = %s", [str(tenant_id)])
        Metric.objects.filter(
            tenant_id=tenant_id, code__in=codes, version=1, is_current=True
        ).delete()


class Migration(migrations.Migration):
    dependencies = [("analytics", "0007_metric_definition_fait_source")]

    operations = [migrations.RunPython(seed_existing_tenants, unseed)]
