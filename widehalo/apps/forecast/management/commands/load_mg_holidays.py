"""Charge les jours feries malgaches depuis `fixtures/mg_holidays.json`.

**Correctif d'un defaut reel** : la docstring de
`apps.forecast.services.calendar` renvoyait a cette commande depuis la
livraison de FOR-5 — et le fichier n'existait pas. `ForHoliday` n'etait donc
peuple par rien d'autre qu'une saisie manuelle : sur une instance neuve,
`is_business_day` tenait TOUT jour de semaine pour ouvre, et
`business_days_in_month` surestimait la capacite de production de dix a
douze jours par an. Le code etait juste ; rien ne l'amorcait. C'est le meme
patron que le dictionnaire d'indicateurs de la Phase 2, peuple nulle part
hors des tests.

Ponctuelle par nature (une fois par tenant et par annee, ou a la creation
d'un tenant), donc jamais planifiee — inscrite comme telle sur la liste
motivee de `tests/architecture/test_scheduled_commands_declared.py`.
Idempotente : relancee, elle ne cree rien de neuf et ne remplace jamais une
ligne saisie ou corrigee a la main."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from apps.core.models.tenant import Tenant
from apps.core.services.scheduled_commands import tenant_step
from apps.forecast.models import ForHoliday
from django.core.management.base import BaseCommand, CommandError

FIXTURE_PATH = Path(__file__).resolve().parent.parent.parent / "fixtures" / "mg_holidays.json"


def holidays_for_year(year: int) -> list[tuple[dt.date, str]]:
    """Dates feriees d'une annee, fixes puis mobiles.

    Une collision est possible et n'est pas une anomalie : le 29 mars 2027 et
    le 29 mars 2032 sont a la fois la commemoration de 1947 et le lundi de
    Paques. La contrainte d'unicite `(tenant, date)` de `ForHoliday` l'exige,
    le premier libelle rencontre l'emporte, et la commande le signale plutot
    que d'echouer."""
    data: dict[str, Any] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    entries: list[tuple[dt.date, str]] = [
        (dt.date(year, item["month"], item["day"]), item["name"]) for item in data["fixed"]
    ]
    for item in data["movable"].get(str(year), []):
        entries.append((dt.date.fromisoformat(item["date"]), item["name"]))
    return sorted(entries)


def available_years() -> list[int]:
    data: dict[str, Any] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return sorted(int(year) for year in data["movable"])


class Command(BaseCommand):
    help = (
        "Charge les jours feries malgaches (FOR-5) dans ForHoliday, depuis "
        "apps/forecast/fixtures/mg_holidays.json. Idempotente ; ne remplace "
        "jamais une ligne existante."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--year",
            type=int,
            action="append",
            dest="years",
            help="Annee a charger (repetable). Par defaut : l'annee courante et la suivante.",
        )
        parser.add_argument(
            "--tenant",
            dest="tenant_code",
            help="Code du tenant. Par defaut : tous les tenants.",
        )

    def handle(self, *args, **options) -> None:
        today = dt.date.today()
        years = options["years"] or [today.year, today.year + 1]
        known = available_years()
        unknown = [year for year in years if year not in known]
        if unknown:
            raise CommandError(
                f"Aucune date mobile connue pour {unknown} — la fixture couvre "
                f"{known[0]}-{known[-1]}. Completer "
                "`apps/forecast/fixtures/mg_holidays.json` (section « movable ») "
                "plutot que de calculer Paques dans le code."
            )

        tenants = Tenant.objects.all()
        if options["tenant_code"]:
            tenants = tenants.filter(code=options["tenant_code"])
            if not tenants.exists():
                raise CommandError(f"Tenant {options['tenant_code']!r} introuvable.")

        for tenant in tenants:
            with tenant_step(self, tenant):
                created = skipped = 0
                for year in years:
                    for date, name in holidays_for_year(year):
                        _, was_created = ForHoliday.objects.get_or_create(
                            tenant=tenant, date=date, defaults={"name": name}
                        )
                        created += int(was_created)
                        skipped += int(not was_created)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Tenant {tenant.code} : {created} jour(s) ferie(s) cree(s), "
                        f"{skipped} deja present(s) sur {years}."
                    )
                )
