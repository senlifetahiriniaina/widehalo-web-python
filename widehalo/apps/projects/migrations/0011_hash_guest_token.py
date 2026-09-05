"""L15 — la base cesse de stocker le jeton du portail invite en clair.

`PrjGuestAccess.token` etait un `CharField` non chiffre, alors que la ligne
elle-meme sert de jeton d'authentification anonyme : quiconque lisait la
table — ou une SAUVEGARDE — obtenait un acces en lecture a tous les projets
partages. L'audit le signalait au meme titre que
`LogServiceProvider.webhook_secret` (§3.6).

**Une empreinte, pas un chiffrement.** Le lot L15 chiffre `webhook_secret`
avec `EncryptedCharField` ; ce champ-ci ne peut pas l'etre. Il est cherche
PAR SA VALEUR (`resolve_guest_access`) et Fernet n'est pas deterministe : un
`filter(token=...)` sur un champ chiffre ne correspondrait jamais, et le
portail invite cesserait de fonctionner en silence. L'empreinte SHA-256 est
la forme qui conserve la recherche.

**Aucun lien deja distribue n'est casse** : l'empreinte est calculee a partir
du jeton existant, et un lien porteur du meme jeton continue de resoudre.
"""

from __future__ import annotations

import hashlib

from django.db import migrations, models


def hash_existing_tokens(apps, schema_editor) -> None:
    """Calcule l'empreinte des jetons deja distribues.

    `PrjGuestAccess` porte `RLS_FORCE_FOR_OWNER = False` (derogation
    disclosee dans `apps.core.management.commands.apply_rls`) : le
    proprietaire de la table lit donc toutes les lignes sans qu'aucun tenant
    ne soit actif, ce qui est precisement ce dont cette reprise a besoin. Une
    table tenant-scopee ordinaire aurait exige de poser `app.tenant_id`
    tenant par tenant."""
    GuestAccess = apps.get_model("projects", "PrjGuestAccess")
    for access in GuestAccess.objects.all().iterator():
        access.token_hash = hashlib.sha256(access.token.encode("utf-8")).hexdigest()
        access.save(update_fields=["token_hash"])


def restore_plaintext_is_impossible(apps, schema_editor) -> None:
    """Irreversible par construction, et c'est le but : une empreinte ne se
    retourne pas. Revenir en arriere signifie revoquer les liens existants et
    en emettre de nouveaux."""
    raise migrations.exceptions.IrreversibleError(
        "Les jetons en clair ne sont pas recuperables depuis leur empreinte. "
        "Revoquer les acces invite existants et en creer de nouveaux."
    )


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0010_alter_prjcustomfielddefinition_field_type_and_more"),
    ]

    operations = [
        # Ajoute d'abord sans contrainte : la table peut deja contenir des
        # lignes, et `unique=True` sur une colonne vide les ferait toutes
        # entrer en collision sur NULL... ou echouer selon le moteur.
        migrations.AddField(
            model_name="prjguestaccess",
            name="token_hash",
            field=models.CharField(default="", editable=False, max_length=64),
            preserve_default=False,
        ),
        migrations.RunPython(hash_existing_tokens, restore_plaintext_is_impossible),
        migrations.AlterField(
            model_name="prjguestaccess",
            name="token_hash",
            field=models.CharField(db_index=True, editable=False, max_length=64, unique=True),
        ),
        migrations.RemoveField(model_name="prjguestaccess", name="token"),
    ]
