"""T9 — le prestataire devient lisible par le point d'entree de webhook, en
lecture seule et sur demande explicite.

**Le defaut ferme, et il rendait le webhook transporteur inutilisable en
production.** `carrier_webhook_endpoint` lit `LogServiceProvider.
all_objects` sans contexte de societe — un transporteur n'a ni session, ni
jeton, ni en-tete de societe. Or `all_objects` ne contourne que la RLS
APPLICATIVE de `TenantManager` : `log_service_provider` reste en `FORCE ROW
LEVEL SECURITY` comme toute sous-classe de `BaseModel`, et sans
`app.tenant_id` PostgreSQL ne rend aucune ligne.

**Mesure faite avant correction**, en `django_db(transaction=True)` :

- un appel authentique, correctement signe, rendait **404** ;
- et un appel a signature INVALIDE rendait 404 lui aussi — le refus
  arrivait avant meme la verification de signature, ce qui rendait le test
  de securite existant faussement rassurant.

Le test qui passait (`logistics/tests/test_api.py`) ne pouvait pas le voir :
pytest-django enveloppe chaque test dans une transaction, le `SET LOCAL
app.tenant_id` de la fixture survivait a son bloc, et la requete lisait la
ligne grace a un contexte **qui n'existe que dans le harnais**.

C'est exactement le defaut repare sur `flw_link` au lot T5
(`flows/0009_flwlink_readable_without_tenant`), et cette migration en est la
copie conforme — meme reglage de session, meme portee `FOR SELECT`, meme
refus de la derogation `RLS_FORCE_FOR_OWNER = False` qui rendrait la table
ecrivable hors societe.
"""

from __future__ import annotations

from django.db import migrations

POLICY_NAME = "webhook_lookup_policy"
TABLE = "log_service_provider"


def create_lookup_policy(apps, schema_editor) -> None:
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(f'DROP POLICY IF EXISTS {POLICY_NAME} ON "{TABLE}"')
    schema_editor.execute(
        f'CREATE POLICY {POLICY_NAME} ON "{TABLE}" FOR SELECT '
        "USING (current_setting('app.webhook_lookup', true) = 'on')"
    )


def drop_lookup_policy(apps, schema_editor) -> None:
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(f'DROP POLICY IF EXISTS {POLICY_NAME} ON "{TABLE}"')


class Migration(migrations.Migration):
    dependencies = [("logistics", "0008_encrypt_webhook_secret")]

    operations = [migrations.RunPython(create_lookup_policy, drop_lookup_policy)]
