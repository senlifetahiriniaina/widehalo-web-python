"""ACC-CAL1 (§1.2 du document annexe) : tableau de bord des echeances
fiscales DGI. Les echeances legales malgaches se deplacent au gre des
communiques DGI — ce module ne construit volontairement PAS un moteur de
regles de recurrence : `seed_default_tax_calendar` se contente de poser un
jeu de dates par defaut, raisonnable, que le tenant (comptable/admin) peut
ensuite corriger a la main des qu'un communique DGI change une echeance.

Reserve OECFM/DGI (§0.5, §3.5 du document annexe) : TOUTES les dates par
defaut ci-dessous (jour du mois, mois de l'echeance annuelle) sont reprises
d'un document non primaire — a confirmer aupres d'un expert-comptable
OECFM ou de la DGI avant tout usage en production reelle. Elles ne sont en
aucun cas presentees comme definitives."""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.utils.translation import gettext as _

from apps.accounting.models import AccTaxCalendar
from apps.core.models.tenant import Tenant


def create_tax_calendar_entry(
    *,
    tenant: Tenant,
    declaration_type: str,
    label: str,
    due_date: dt.date,
    periodicity: str,
    is_recurring_template: bool = False,
) -> AccTaxCalendar:
    return AccTaxCalendar.objects.create(
        tenant=tenant,
        declaration_type=declaration_type,
        label=label,
        due_date=due_date,
        periodicity=periodicity,
        is_recurring_template=is_recurring_template,
    )


def upcoming_deadlines(
    tenant: Tenant, *, within_days: int = 90, today: dt.date | None = None
) -> list[AccTaxCalendar]:
    """Echeances a venir, triees par date, dans les `within_days` prochains
    jours. Pas de notion de "cleree"/"traitee" en V1 (cf. plan, etape A8) :
    on filtre simplement les echeances deja passees (`due_date < today`)."""
    today = today or dt.date.today()
    horizon = today + dt.timedelta(days=within_days)
    return list(
        AccTaxCalendar.objects.filter(
            tenant=tenant, due_date__gte=today, due_date__lte=horizon
        ).order_by("due_date")
    )


# Jeu de reference (§1.2 du document annexe) : (declaration_type, libelle,
# periodicite, fonction qui calcule l'echeance par defaut pour l'ANNEE
# donnee). Dates DGI par defaut, sujettes a communique — cf. reserve en
# tete de module :
#   - IRSA          : 15 du mois M+1 (mensuel) -> ici, le 15 du mois suivant
#     le mois courant au moment du seed, a titre d'exemple de gabarit.
#   - TVA           : 15 du mois M+1 (mensuel), meme logique que l'IRSA.
#   - IS annuel     : 31 mars N+1.
#   - IR annuel     : 15 mai N+1.
#   - IRCM          : 15 mai N+1 (memes echeances que l'IR annuel au §1.2).
#   - DCOM          : 30 juin N+1.
def _default_entries(year: int) -> list[dict[str, Any]]:
    next_year = year + 1
    return [
        {
            "declaration_type": AccTaxCalendar.DECLARATION_IRSA,
            "label": _("IRSA — retenue sur salaires"),
            "due_date": dt.date(year, 2, 15),
            "periodicity": AccTaxCalendar.PERIODICITY_MONTHLY,
        },
        {
            "declaration_type": AccTaxCalendar.DECLARATION_TVA,
            "label": _("TVA — declaration mensuelle"),
            "due_date": dt.date(year, 2, 15),
            "periodicity": AccTaxCalendar.PERIODICITY_MONTHLY,
        },
        {
            "declaration_type": AccTaxCalendar.DECLARATION_IR_ACOMPTE,
            "label": _("Acompte IR"),
            "due_date": dt.date(year, 5, 15),
            "periodicity": AccTaxCalendar.PERIODICITY_SEMIANNUAL,
        },
        {
            "declaration_type": AccTaxCalendar.DECLARATION_IS_ANNUAL,
            "label": _("IS annuel"),
            "due_date": dt.date(next_year, 3, 31),
            "periodicity": AccTaxCalendar.PERIODICITY_ANNUAL,
        },
        {
            "declaration_type": AccTaxCalendar.DECLARATION_IR_ANNUAL,
            "label": _("IR annuel"),
            "due_date": dt.date(next_year, 5, 15),
            "periodicity": AccTaxCalendar.PERIODICITY_ANNUAL,
        },
        {
            "declaration_type": AccTaxCalendar.DECLARATION_IRCM,
            "label": _("IRCM"),
            "due_date": dt.date(next_year, 5, 15),
            "periodicity": AccTaxCalendar.PERIODICITY_ANNUAL,
        },
        {
            "declaration_type": AccTaxCalendar.DECLARATION_DCOM,
            "label": _("DCOM — declaration des commissions/honoraires"),
            "due_date": dt.date(next_year, 6, 30),
            "periodicity": AccTaxCalendar.PERIODICITY_ANNUAL,
        },
        {
            "declaration_type": AccTaxCalendar.DECLARATION_TVM,
            "label": _("TVM — taxe sur les vehicules a moteur"),
            "due_date": dt.date(year, 3, 31),
            "periodicity": AccTaxCalendar.PERIODICITY_ANNUAL,
        },
        {
            "declaration_type": AccTaxCalendar.DECLARATION_IFT,
            "label": _("IFT — impot foncier sur les terrains"),
            "due_date": dt.date(year, 10, 31),
            "periodicity": AccTaxCalendar.PERIODICITY_ANNUAL,
        },
        {
            "declaration_type": AccTaxCalendar.DECLARATION_IFPB,
            "label": _("IFPB — impot foncier sur la propriete batie"),
            "due_date": dt.date(year, 10, 31),
            "periodicity": AccTaxCalendar.PERIODICITY_ANNUAL,
        },
        {
            "declaration_type": AccTaxCalendar.DECLARATION_ETATS_FINANCIERS,
            "label": _("Depot des etats financiers"),
            "due_date": dt.date(next_year, 5, 15),
            "periodicity": AccTaxCalendar.PERIODICITY_ANNUAL,
        },
    ]


def seed_default_tax_calendar(tenant: Tenant, *, year: int | None = None) -> list[AccTaxCalendar]:
    """Peuple le calendrier fiscal par defaut (11 types de declaration, cf.
    `AccTaxCalendar.DECLARATION_TYPE_CHOICES`) pour l'annee donnee (annee
    courante par defaut) — idempotent : ne recree pas une ligne modele deja
    presente pour ce (tenant, type, annee de reference de `due_date`).
    Chaque ligne est creee avec `is_recurring_template=True` : c'est un
    point de depart que le tenant peut ensuite dupliquer/ajuster periode
    apres periode, jamais une regle de recurrence appliquee
    automatiquement."""
    year = year or dt.date.today().year
    created: list[AccTaxCalendar] = []
    for entry in _default_entries(year):
        obj, was_created = AccTaxCalendar.objects.get_or_create(
            tenant=tenant,
            declaration_type=entry["declaration_type"],
            due_date=entry["due_date"],
            defaults={
                "label": entry["label"],
                "periodicity": entry["periodicity"],
                "is_recurring_template": True,
            },
        )
        if was_created:
            created.append(obj)
    return created
