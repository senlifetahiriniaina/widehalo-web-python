"""A15 — ACC-REL (RG-ACC-11) : relances client a 3 niveaux.

V1 documentee explicitement (cf. `record_dunning_action`) : ce module ne
CONSTRUIT AUCUN mecanisme d'envoi (email/WhatsApp/SMS) — il permet
seulement de detecter les creances en retard, de determiner le niveau de
relance applicable, et d'enregistrer qu'une action de relance a ete menee
(par un humain ou un processus externe). Le futur ecran/notification
d'envoi reel s'appuiera sur `AccDunningAction` sans modification de ce
module.

Reserve legere (meme discipline que les formules de `services/reports.py::
financial_ratios`, A13) : les libelles et seuils par defaut de
`seed_default_dunning_levels` sont des valeurs RAISONNABLES INVENTEES — le
CDC (RG-ACC-11) impose "3 niveaux" sans en fixer le libelle exact ni les
seuils en jours. Ajustables par tenant a tout moment via `AccDunningLevel`."""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.utils.translation import gettext as _

from apps.accounting.models import (
    AccAccount,
    AccDunningAction,
    AccDunningLevel,
    AccMove,
    AccMoveLine,
)
from apps.core.models.tenant import Tenant

# Valeurs par defaut INVENTEES (documentees ci-dessus et sur le modele) :
# niveau 1 = rappel amical peu apres l'echeance, niveau 2 = mise en demeure a
# 30 jours, niveau 3 = relance formelle (avant contentieux) a 60 jours.
_DEFAULT_LEVELS: tuple[tuple[int, str, int, str], ...] = (
    (
        1,
        "Rappel amical",
        15,
        _("Nous constatons que votre facture demeure impayée. Merci de régulariser."),
    ),
    (
        2,
        "Mise en demeure",
        30,
        _(
            "Mise en demeure de payer sous 8 jours, a défaut de quoi des poursuites "
            "seront engagees."
        ),
    ),
    (
        3,
        "Relance formelle",
        60,
        _("Dernier rappel avant transmission du dossier au contentieux."),
    ),
)


def seed_default_dunning_levels(tenant: Tenant) -> list[AccDunningLevel]:
    """Cree les 3 niveaux par defaut si aucun n'existe encore pour ce tenant
    (idempotent : `get_or_create` par `(tenant, level)`, jamais d'ecrasement
    d'une valeur deja personnalisee par le tenant)."""
    levels = []
    for level, label, threshold, message in _DEFAULT_LEVELS:
        entry, _created = AccDunningLevel.objects.get_or_create(
            tenant=tenant,
            level=level,
            defaults={
                "label": label,
                "days_overdue_threshold": threshold,
                "message_template": message,
            },
        )
        levels.append(entry)
    return levels


def _applicable_level(days_overdue: int, levels: list[AccDunningLevel]) -> AccDunningLevel | None:
    """Le niveau le plus eleve dont le seuil est deja franchi, ou `None` si
    la creance n'a pas encore atteint le seuil du niveau 1."""
    applicable: AccDunningLevel | None = None
    for level in sorted(levels, key=lambda entry: entry.days_overdue_threshold):
        if days_overdue >= level.days_overdue_threshold:
            applicable = level
    return applicable


def overdue_receivables(tenant: Tenant, *, as_of_date: Any = None) -> list[dict[str, Any]]:
    """Une ligne par creance client OUVERTE (memes criteres qu'`aged_
    receivables`, A9 : `matching_number == ""`) dont `due_date` est deja
    depassee a `as_of_date`, avec le niveau de relance applicable (le plus
    eleve dont le seuil `days_overdue_threshold` est deja franchi, `None` si
    la creance n'a pas encore atteint le seuil du niveau 1)."""
    as_of = as_of_date or dt.date.today()
    levels = list(AccDunningLevel.objects.all())

    lines = AccMoveLine.objects.filter(
        account__type=AccAccount.TYPE_RECEIVABLE,
        move__state=AccMove.STATE_POSTED,
        matching_number="",
        due_date__isnull=False,
        due_date__lt=as_of,
    ).select_related("account")

    rows: list[dict[str, Any]] = []
    for line in lines:
        assert line.due_date is not None  # garanti par due_date__isnull=False ci-dessus
        days_overdue = (as_of - line.due_date).days
        applicable = _applicable_level(days_overdue, levels)
        rows.append(
            {
                "move_line_id": str(line.id),
                "partner_id": line.partner_id,
                "days_overdue": days_overdue,
                "applicable_level": applicable.level if applicable is not None else None,
                "amount_mga": line.debit - line.credit,
            }
        )
    return rows


def record_dunning_action(
    move_line: AccMoveLine,
    level: AccDunningLevel,
    *,
    date_sent: dt.date | None = None,
    notes: str = "",
) -> AccDunningAction:
    """Enregistre qu'une relance de `level` a ete envoyee pour `move_line` —
    aucun envoi reel n'est declenche ici (cf. docstring de module, V1)."""
    return AccDunningAction.objects.create(
        tenant=move_line.tenant,
        move_line=move_line,
        level=level,
        date_sent=date_sent or dt.date.today(),
        notes=notes,
    )


__all__ = [
    "overdue_receivables",
    "record_dunning_action",
    "seed_default_dunning_levels",
]
