"""Charge les jours feries malgaches depuis `fixtures/mg_holidays.json`.

**Correctif d'un defaut reel** : la docstring de
`apps.core.services.calendar` renvoyait a cette commande depuis la
livraison de FOR-5 — et le fichier n'existait pas. `Holiday` n'etait donc
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

from django.core.management.base import BaseCommand, CommandError

from apps.core.models.calendar import Holiday
from apps.core.models.tenant import Tenant
from apps.core.services.scheduled_commands import tenant_step

FIXTURE_PATH = Path(__file__).resolve().parent.parent.parent / "fixtures" / "mg_holidays.json"


def collisions_for_year(year: int) -> list[tuple[dt.date, list[str]]]:
    """Les dates que PLUSIEURS fetes se disputent, avec tous leurs libelles.

    Distinguee du simple rejeu, et ce n'est pas de la cosmetique : jusqu'ici
    une collision etait fondue dans le compteur « deja present », donc
    indiscernable d'une seconde execution de la commande. La docstring
    affirmait pourtant que « la commande le signale ». Elle ne le signalait
    pas — c'est corrige ici plutot que la phrase.

    Une collision n'est PAS une anomalie. Elle est meme frequente : le
    29 mars 2027 et le 29 mars 2032 portent a la fois la commemoration de
    1947 et le lundi de Paques, et le 17 mai 2027 le lundi de Pentecote et
    l'Aid el-Adha. Elle est sans consequence sur la paie — la majoration
    porte sur la DATE, jamais sur le libelle."""
    par_date: dict[dt.date, list[str]] = {}
    for date, name in holidays_for_year(year):
        par_date.setdefault(date, []).append(name)
    return sorted((date, noms) for date, noms in par_date.items() if len(noms) > 1)


def holidays_for_year(year: int) -> list[tuple[dt.date, str]]:
    """Dates feriees d'une annee, fixes puis mobiles.

    La contrainte d'unicite `(tenant, date)` de `Holiday` n'en garde qu'une
    par date : le premier libelle dans l'ordre alphabetique l'emporte, et
    `collisions_for_year` rend les autres visibles plutot que de les
    perdre."""
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
        "Charge les jours feries malgaches (FOR-5) dans Holiday, depuis "
        "apps/core/fixtures/mg_holidays.json. Idempotente ; ne remplace "
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
                "`apps/core/fixtures/mg_holidays.json` (section « movable ») "
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
                        _, was_created = Holiday.objects.get_or_create(
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
                for year in years:
                    for date, noms in collisions_for_year(year):
                        # Signale une seule fois par tenant traite : un
                        # exploitant qui voit « 2 deja present(s) » sans
                        # explication ne peut pas savoir s'il relance une
                        # commande ou s'il perd un libelle.
                        self.stdout.write(
                            self.style.WARNING(
                                f"  {date.isoformat()} : {len(noms)} fetes le meme jour "
                                f"({', '.join(noms)}) — une seule ligne est creee, sous le "
                                f"libelle « {noms[0]} ». Sans consequence sur la paie."
                            )
                        )
