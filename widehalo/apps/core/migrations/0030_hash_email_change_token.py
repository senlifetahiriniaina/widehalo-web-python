"""L15 — la base cesse de stocker en clair le jeton de changement d'e-mail.

Troisieme secret en clair du depot, trouve en fermant les deux que l'audit
signalait (§3.6 : `LogServiceProvider.webhook_secret` et
`PrjGuestAccess.token`). Il n'y figurait pas, et il est du meme ordre : ce
jeton donne le pouvoir de changer l'adresse e-mail d'un compte,
c'est-a-dire son identifiant de connexion.

Une EMPREINTE et non un chiffrement, pour la meme raison que
`PrjGuestAccess` : le champ est cherche par sa valeur
(`confirm_email_change`) et Fernet n'est pas deterministe.

**Aucun lien deja envoye n'est casse** : l'empreinte est calculee a partir
du jeton existant, et un e-mail deja recu continue de fonctionner jusqu'a
son expiration (24 h).
"""

from __future__ import annotations

import hashlib

from django.db import migrations, models


def hash_existing_tokens(apps, schema_editor) -> None:
    """`UserEmailChangeRequest` porte `RLS_FORCE_FOR_OWNER = False` (meme
    derogation que `PrjGuestAccess`, pour la meme raison structurelle : la
    vue de confirmation est publique et sans tenant actif). Le proprietaire
    de la table lit donc toutes les lignes sans contexte tenant, ce dont
    cette reprise a besoin."""
    ChangeRequest = apps.get_model("core", "UserEmailChangeRequest")
    for request in ChangeRequest.objects.all().iterator():
        request.token_hash = hashlib.sha256(request.token.encode("utf-8")).hexdigest()
        request.save(update_fields=["token_hash"])


def restore_plaintext_is_impossible(apps, schema_editor) -> None:
    raise migrations.exceptions.IrreversibleError(
        "Les jetons en clair ne sont pas recuperables depuis leur empreinte. "
        "Les demandes de changement d'e-mail en cours doivent etre relancees."
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0029_tenant_whatsapp_cost_alert_threshold_pct_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="useremailchangerequest",
            name="token_hash",
            field=models.CharField(default="", editable=False, max_length=64),
            preserve_default=False,
        ),
        migrations.RunPython(hash_existing_tokens, restore_plaintext_is_impossible),
        migrations.AlterField(
            model_name="useremailchangerequest",
            name="token_hash",
            field=models.CharField(db_index=True, editable=False, max_length=64, unique=True),
        ),
        migrations.RemoveField(model_name="useremailchangerequest", name="token"),
    ]
