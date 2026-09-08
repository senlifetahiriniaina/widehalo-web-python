"""T3 — CHIFFRER les identifiants fiscaux non conformes, avant qu'ils ne
bloquent quoi que ce soit.

**Pourquoi cette commande existe, et pourquoi elle ne corrige rien.** Le
cahier range la qualité du référentiel tiers parmi les « trois travaux que
la Phase 4 impose au CLIENT, et qui ne sont pas du développement » : « un
identifiant fiscal absent ou faux […] empêchera désormais une validation.
[…] Ces trois travaux relèvent du client, avec un accompagnement à chiffrer
séparément du développement. Les inscrire dans le contrat évite qu'ils ne
soient découverts au sprint 11, quand le connecteur sera prêt et
l'habilitation non demandée. »

Un travail qu'on met à la charge de quelqu'un sans lui donner de quoi le
mesurer n'est pas un travail : c'est une surprise. Cette commande est
l'instrument de mesure. Elle LIT et ne modifie rien — normaliser en masse
réécrirait la saisie de comptables sans qu'ils l'aient demandée, et l'une
des deux formes en présence peut être la forme officielle.

**Ce qu'elle sépare, parce que ce sont trois travaux différents** : les
tiers sans identifiant du tout (à collecter), ceux dont l'identifiant ne
passe pas le format déclaré (à corriger), et ceux qui portent le même
identifiant que d'autres sous une forme différente (à fusionner ou à
distinguer). Un seul total les mélangerait et ne dirait à personne par où
commencer.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand

from apps.core.models.tenant import Tenant
from apps.core.services.fiscal_identifiers import (
    IDENTIFIER_NIF,
    IDENTIFIER_STAT,
    canonical,
    validate_identifier,
)
from apps.core.tenant_context import activate_tenant
from apps.partners.models import Partner


class Command(BaseCommand):
    help = (
        "Chiffre les identifiants fiscaux absents, mal formés ou en doublon, "
        "société par société. Ne modifie rien."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--tenant-code",
            default="",
            help="Limite l'audit à une société (défaut : toutes).",
        )
        parser.add_argument(
            "--details",
            action="store_true",
            help="Liste chaque tiers concerné, pas seulement les totaux.",
        )

    def handle(self, *args: object, **options: object) -> None:
        code = str(options.get("tenant_code") or "")
        tenants = Tenant.objects.filter(code=code) if code else Tenant.objects.all()
        if not tenants.exists():
            self.stdout.write(self.style.WARNING("Aucune société à auditer."))
            return

        total_global = 0
        for tenant in tenants.order_by("code"):
            total_global += self._audit_tenant(tenant, details=bool(options.get("details")))

        if total_global:
            self.stdout.write(
                self.style.WARNING(
                    f"\n{total_global} tiers à traiter au total. Aucune modification "
                    "n'a été faite : la correction reste une décision humaine."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "\nAucun identifiant fiscal à corriger — le référentiel est prêt "
                    "pour une soumission."
                )
            )

    def _audit_tenant(self, tenant: Tenant, *, details: bool) -> int:
        with activate_tenant(tenant.id):
            partenaires = list(Partner.objects.filter(is_placeholder=False).order_by("reference"))

        sans_nif: list[Partner] = []
        mal_formes: list[tuple[Partner, str, str]] = []
        par_canonique: dict[str, list[Partner]] = defaultdict(list)
        pays = tenant.country_code or ""

        for partenaire in partenaires:
            if not partenaire.nif:
                sans_nif.append(partenaire)
            for champ, identifiant in (
                ("nif", IDENTIFIER_NIF),
                ("stat", IDENTIFIER_STAT),
            ):
                valeur = getattr(partenaire, champ)
                if not valeur:
                    continue
                try:
                    validate_identifier(valeur, identifier=identifiant, country_code=pays)
                except ValidationError as refus:
                    mal_formes.append((partenaire, champ, "; ".join(refus.messages)))
            if partenaire.nif:
                par_canonique[canonical(partenaire.nif)].append(partenaire)

        doublons = {clef: liste for clef, liste in par_canonique.items() if len(liste) > 1}
        total = len(sans_nif) + len(mal_formes) + sum(len(liste) for liste in doublons.values())

        self.stdout.write(
            f"\n{tenant.code} — {len(partenaires)} tiers, "
            f"{len(sans_nif)} sans NIF, {len(mal_formes)} mal formé(s), "
            f"{len(doublons)} groupe(s) de doublon."
        )
        if not details:
            return total

        for partenaire in sans_nif:
            self.stdout.write(f"  sans NIF   {partenaire.reference} — {partenaire.name}")
        for partenaire, champ, motif in mal_formes:
            self.stdout.write(
                f"  mal formé  {partenaire.reference} — {partenaire.name} [{champ}] {motif}"
            )
        for clef, liste in doublons.items():
            noms = ", ".join(f"{p.reference} ({p.nif})" for p in liste)
            self.stdout.write(f"  doublon    {clef} → {noms}")
        return total
