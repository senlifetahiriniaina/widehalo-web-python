"""Chargement du plan comptable PCG 2005 malgache — jeu de donnees
REPRESENTATIF et SIMPLIFIE (pas exhaustif), a valider par un
expert-comptable membre de l'OECFM avant toute utilisation en production
(exigence explicite du cahier des charges, § 5.1.6). Modifiable par le
tenant apres chargement : ajout de sous-comptes, desactivation de comptes
inutilises.

Depuis l'etape A9 (Phase 2), la fixture porte aussi des valeurs par defaut
POUR `is_current` (ACC-BIL, §1.10.1 du document annexe) et
`functional_destination` (ACC-CR-FN1, §1.10.2) — ces deux mappings sont
EGALEMENT non valides par un expert-comptable OECFM, au meme titre que le
reste du plan comptable :
- `is_current` : False uniquement pour les immobilisations (classe 2) et les
  capitaux propres/dettes long terme (classe 1) — structurellement non
  courants au sens des criteres Art. 131-3 a 131-11. True par defaut
  partout ailleurs (creances, dettes, tresorerie, taxes, stocks classe 3),
  coherent avec le fait que ce sont les elements du cycle d'exploitation
  normal de l'entreprise.
- `functional_destination` : renseigne uniquement sur les comptes de charge
  (classe 6) — matieres premieres -> `production` (matiere transformee),
  achats de marchandises/transport -> `distribution` (cout de revient
  commercial), le reste (loyers, frais bancaires, impots, personnel,
  dotations aux amortissements) -> `administration` par defaut faute d'une
  cle de ventilation plus fine en V1 (ex. la masse salariale de production
  vs administrative n'est pas encore distinguee analytiquement) ; `autre`
  n'est utilise pour aucun compte de la fixture V1. Ce choix « tout ce qui
  n'est pas clairement production/distribution va en administration » est
  une simplification assumee, a affiner avec un vrai expert-comptable.

Depuis UXR7, la fixture porte aussi ~15 comptes sectoriels (3 par secteur,
`AccAccount.sector_code` renseigne : textile/cuir/agroalimentaire/
import_export/artisanat, matiere premiere/achat/sous-traitance-ou-poste
specifique) en plus des 39 comptes generiques existants (`sector_code` vide).
**Meme reserve OECFM que le reste de cette fixture** : ce contenu sectoriel
est lui aussi indicatif, non valide par un expert-comptable ni un expert
sectoriel independant — a ne jamais presenter comme une nomenclature
sectorielle faisant autorite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.accounting.models import AccAccount, AccJournal
from apps.accounting.services.framework import chart_for_country, framework_for_tenant
from apps.core.models.tenant import Tenant

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "pcg2005_mg.json"

# Compte d'attente ("suspense") du chantier RG-QUALIF — cree a la demande,
# jamais dans le chargement initial du plan comptable, pour ne pas polluer un
# plan comptable qui n'a jamais eu besoin d'un import "degrade" avec
# identification incertaine.
#
# D10-4 : son code et sa classe viennent du referentiel actif
# (`AccFramework.suspense_account_code`/`suspense_account_class`) — le "471"
# et la classe 4 etaient la forme PCG 2005 ("Comptes transitoires ou
# d'attente"), et un plan SYSCOHADA n'aurait aucune raison de les partager.


def _read_fixture() -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return data


def load_pcg2005(tenant: Tenant) -> int:
    """Cree les comptes du plan PCG 2005 pour ce tenant. Idempotent : un
    compte dont le code existe deja pour ce tenant n'est pas recree.

    Charge **tous** les comptes de la fixture, generiques ET sectoriels
    (`sector_code` renseigne), sans aucun filtrage par secteur — decision
    disclosed (UXR7) : ce depot n'a nulle part de notion de "secteur du
    tenant" a laquelle rattacher un filtre (`catalog.CatalogSectorSpec` est
    porte par variante produit, `strategy.StgSectorBenchmark` par code
    sectoriel generique du referentiel — ni l'un ni l'autre n'est un
    attribut de `Tenant`). Charger quelques comptes sectoriels en trop pour
    un tenant qui ne les utilisera jamais est sans risque (comptes inactifs
    de fait, desactivables manuellement) ; filtrer a tort en excluant un
    compte dont un tenant aurait eu besoin serait pire."""
    existing_codes = set(AccAccount.objects.filter(tenant=tenant).values_list("code", flat=True))

    created = 0
    for entry in _read_fixture():
        if entry["code"] in existing_codes:
            continue
        AccAccount.objects.create(
            tenant=tenant,
            code=entry["code"],
            name=entry["name"],
            account_class=entry["account_class"],
            type=entry["type"],
            is_current=entry.get("is_current", True),
            functional_destination=entry.get("functional_destination", ""),
            sector_code=entry.get("sector_code") or None,
        )
        created += 1

    return created


def ensure_suspense_account(tenant: Tenant) -> AccAccount:
    """Cree, s'il n'existe pas encore, LE compte d'attente (`is_placeholder
    =True`, code `471`, classe 47x) de ce tenant — idempotent par code,
    meme discipline que `load_pcg2005`. Utilise par
    `apps.accounting.services.cash_journal_import`/`invoice_import` quand
    un compte reel n'a pas pu etre identifie avec certitude (chantier
    RG-QUALIF) : plutot que de bloquer la ligne (`COMPTE_INCONNU`
    devenait non-defaultable auparavant), un `AccMove` brouillon est
    materialise immediatement sur ce compte, marque `needs_qualification`."""
    framework = framework_for_tenant(tenant)
    if framework is None or not framework.suspense_account_code:
        raise ValidationError(
            _("Aucun compte d'attente n'est defini par le referentiel comptable de ce tenant.")
        )
    code = framework.suspense_account_code
    existing = AccAccount.objects.filter(tenant=tenant, code=code).first()
    if existing is not None:
        return existing
    return AccAccount.objects.create(
        tenant=tenant,
        code=code,
        name=str(_("Compte d'attente (à qualifier)")),
        account_class=framework.suspense_account_class,
        type=AccAccount.TYPE_ASSET,
        is_placeholder=True,
        chart=chart_for_country(tenant.country_code),
    )


# UXR7 : un journal par type d'`AccJournal.TYPE_CHOICES`, code -> (type,
# libelle, prefixe de compte par defaut a resoudre defensivement). Prefixes
# alignes sur la numerotation PCG 2005 REELLEMENT presente dans
# `pcg2005_mg.json` (compte "512" Banques, compte "530" Caisse) — pas sur le
# "571" generique parfois cite ailleurs pour la caisse, absent de cette
# fixture. `None` = aucun compte par defaut resolu a ce stade (VTE/ACH/OD/
# PAI/STK) : simplification disclosed, coherente avec le reste du depot —
# a configurer manuellement via `config_journals` si un tenant en a besoin.
_DEFAULT_JOURNALS: list[tuple[str, str, str, str | None]] = [
    ("VTE", AccJournal.TYPE_SALE, "Journal des ventes", None),
    ("ACH", AccJournal.TYPE_PURCHASE, "Journal des achats", None),
    # D10-4 : "bank"/"cash" sont des marqueurs symboliques, resolus a l'appel
    # depuis `AccFramework.bank_account_prefix`/`cash_account_prefix` — les
    # litteraux "512"/"530" etaient la numerotation PCG 2005.
    ("BQ", AccJournal.TYPE_BANK, "Journal de banque", "bank"),
    ("CAI", AccJournal.TYPE_CASH, "Journal de caisse", "cash"),
    ("OD", AccJournal.TYPE_MISC, "Operations diverses", None),
    ("PAI", AccJournal.TYPE_PAYROLL, "Journal de paie", None),
    ("STK", AccJournal.TYPE_STOCK, "Journal de stock", None),
]


def ensure_default_journals(tenant: Tenant) -> int:
    """Cree les 7 journaux comptables par defaut de ce tenant (un par
    `AccJournal.TYPE_CHOICES`) — idempotent par `code`, meme discipline que
    `load_pcg2005` : un journal dont le code existe deja pour ce tenant
    n'est pas recree, et cette fonction n'est jamais appelee avant que le
    plan comptable ne soit charge (`load_pcg2005` doit tourner en premier,
    cf. les 3 points d'appel de creation de tenant) puisque `BQ`/`CAI`
    tentent de resoudre defensivement un `default_account` par prefixe de
    code (`512*` banque, `530*` caisse) parmi les comptes deja crees pour ce
    tenant — aucune exception levee si rien ne correspond, `default_account`
    reste simplement `None`. Les 5 autres journaux (ventes/achats/operations
    diverses/paie/stock) n'ont pas de compte par defaut evident a ce niveau
    (simplification disclosed) et restent `default_account=None`."""
    framework = framework_for_tenant(tenant)
    prefix_by_marker = {
        "bank": framework.bank_account_prefix if framework else "",
        "cash": framework.cash_account_prefix if framework else "",
    }
    existing_codes = set(AccJournal.objects.filter(tenant=tenant).values_list("code", flat=True))

    created = 0
    for code, journal_type, name, account_prefix in _DEFAULT_JOURNALS:
        if code in existing_codes:
            continue
        default_account = None
        prefix = prefix_by_marker.get(account_prefix) if account_prefix else None
        if prefix:
            default_account = (
                AccAccount.objects.filter(tenant=tenant, code__startswith=prefix)
                .order_by("code")
                .first()
            )
        AccJournal.objects.create(
            tenant=tenant,
            code=code,
            name=name,
            type=journal_type,
            default_account=default_account,
            sequence_prefix=code,
        )
        created += 1

    return created
