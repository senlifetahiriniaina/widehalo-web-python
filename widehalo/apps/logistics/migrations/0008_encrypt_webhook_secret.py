"""L15 — `LogServiceProvider.webhook_secret` chiffre au repos.

Le secret partage servant a verifier la signature HMAC des webhooks
transporteurs etait un `CharField` en clair, alors que `EncryptedCharField`
existait deja dans ce depot et servait pour `PrsEmployee.cin`. L'API
n'exposait que `has_webhook_secret: bool`, ce qui limitait la fuite par
l'application — mais ne protegeait ni la base ni les sauvegardes, qui sont
precisement ce qui circule le plus (audit §3.6).

Le champ est lu une fois pour calculer un HMAC et n'est jamais filtre par
l'ORM : c'est la condition d'emploi d'un champ Fernet, dont le chiffrement
n'est pas deterministe. `PrjGuestAccess.token`, traite dans le meme lot, ne
remplit PAS cette condition et recoit une empreinte plutot qu'un
chiffrement.
"""

from __future__ import annotations

import apps.core.db.fields
from django.db import migrations


def encrypt_existing_secrets(apps, schema_editor) -> None:
    """Re-ecrit les secrets deja stockes pour qu'ils passent par le chiffrement.

    Sans cette reprise, `AlterField` changerait le type de la colonne sans
    toucher aux valeurs : les anciens secrets resteraient lisibles en base et
    le lot n'aurait rien protege. `EncryptedCharField.from_db_value` tolere
    une valeur en clair (retour tel quel sur `InvalidToken`), la relecture
    puis la re-ecriture suffisent donc.

    La table est tenant-scopee et soumise a la RLS : sans `app.tenant_id`
    pose, la boucle ne verrait aucune ligne et la reprise serait un silence.
    Le contexte est donc active tenant par tenant, comme le fait
    `apps.core.tenant_context.activate_tenant` a l'execution."""
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return
    Tenant = apps.get_model("core", "Tenant")
    Provider = apps.get_model("logistics", "LogServiceProvider")
    for tenant_id in Tenant.objects.values_list("id", flat=True):
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL app.tenant_id = %s", [str(tenant_id)])
        for provider in Provider.objects.filter(tenant_id=tenant_id).exclude(webhook_secret=""):
            provider.save(update_fields=["webhook_secret"])


def leave_encrypted(apps, schema_editor) -> None:
    """Retour arriere sans perte : `from_db_value` ne dechiffrerait plus rien
    apres un retour au `CharField`, mais aucune donnee n'est detruite ici —
    un dechiffrement de masse serait un choix d'exploitation, pas un effet de
    bord de migration."""
    return


class Migration(migrations.Migration):
    dependencies = [
        ("logistics", "0007_logserviceprovider_partner_id"),
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="logserviceprovider",
            name="webhook_secret",
            field=apps.core.db.fields.EncryptedCharField(blank=True, max_length=128),
        ),
        migrations.RunPython(encrypt_existing_secrets, leave_encrypted),
    ]
