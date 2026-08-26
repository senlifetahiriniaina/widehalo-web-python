from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0012_notification_whatsappmessage_searchdocument"),
    ]

    operations = [
        TrigramExtension(),
    ]
