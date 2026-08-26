"""Droits RGPD de base : export (droit d'acces/portabilite) et
anonymisation (droit a l'effacement). L'agregation inter-modules se fait
par decouverte des `ModuleSpec` enregistres et un contrat optionnel
`services/public.py::export_personal_data(user) -> dict`, pour rester
extensible aux futurs modules sans modification du socle."""

from __future__ import annotations

import importlib
import io
import json
import zipfile

from apps.core.models.user import User


def export_personal_data_zip(user: User) -> bytes:
    """Assemble un ZIP contenant les donnees personnelles connues de
    l'utilisateur, en json/core.json, plus un fichier par module qui
    expose `export_personal_data()` dans son contrat public."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        core_data = {
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "phone": user.phone,
            "date_joined": user.date_joined.isoformat(),
            "tenants": list(user.tenant_memberships.values_list("tenant__code", flat=True)),
        }
        archive.writestr("core.json", json.dumps(core_data, indent=2, ensure_ascii=False))

        for app_name in _discover_installed_module_apps():
            try:
                public = importlib.import_module(f"apps.{app_name}.services.public")
            except ModuleNotFoundError:
                continue
            exporter = getattr(public, "export_personal_data", None)
            if callable(exporter):
                data = exporter(user)
                archive.writestr(f"{app_name}.json", json.dumps(data, indent=2, ensure_ascii=False))

    return buffer.getvalue()


def _discover_installed_module_apps() -> list[str]:
    from django.conf import settings

    return [app.split(".")[-1] for app in settings.INSTALLED_APPS if app.startswith("apps.")]


def anonymize_user(user: User) -> User:
    """Remplace les donnees personnelles par des valeurs generiques
    irreversibles, conserve l'id pour l'integrite referentielle (droit a
    l'effacement — les documents/ecritures lies restent traces via l'id,
    sans plus jamais reveler l'identite reelle)."""
    anonymized_email = f"anonymise-{user.id}@example.invalid"
    user.email = anonymized_email
    user.first_name = "Anonymisé"
    user.last_name = ""
    user.phone = ""
    user.is_active = False
    user.set_unusable_password()
    user.save(update_fields=["email", "first_name", "last_name", "phone", "is_active", "password"])
    return user
