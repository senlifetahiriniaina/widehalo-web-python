from django.db import migrations


def seed_madagascar(apps, schema_editor):
    CountryDefaultsProfile = apps.get_model("core", "CountryDefaultsProfile")
    CountryDefaultsProfile.objects.update_or_create(
        country_code="MG",
        defaults={
            "base_currency": "MGA",
            "default_language": "fr",
            "timezone": "Indian/Antananarivo",
            "vat_rate": "20.00",
            "chart_of_accounts_code": "PCG2005",
            "payment_methods": ["cash", "bank_transfer", "mvola", "orange_money", "airtel_money"],
            "holidays": [
                "01-01",  # Jour de l'an
                "03-29",  # Jour des martyrs
                "05-01",  # Fête du travail
                "05-25",  # Anniversaire de l'OUA
                "06-26",  # Fête de l'indépendance
                "08-15",  # Assomption
                "11-01",  # Toussaint
                "12-25",  # Noël
            ],
        },
    )


def remove_madagascar(apps, schema_editor):
    CountryDefaultsProfile = apps.get_model("core", "CountryDefaultsProfile")
    CountryDefaultsProfile.objects.filter(country_code="MG").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_audit_log_immutable"),
    ]

    operations = [
        migrations.RunPython(seed_madagascar, remove_madagascar),
    ]
