"""T2 (ACC-10) — clôturer un exercice, et le rendre opposable à tous.

**Le critère, mot pour mot** : « Un exercice clos refuse toute écriture, y
compris par appel direct de l'API et y compris pour un utilisateur
administrateur. »

**Ce que la mesure a trouvé, et ce n'est pas ce que l'audit disait.**
L'audit classait ACC-10 🟡 avec pour réserve « le refus n'est pas garanti
par la base ». Cette réserve a été levée depuis par L3 : le déclencheur
`acc_move_no_post_in_closed_period` (migration `accounting/0031`) refuse en
base la publication dans une PÉRIODE close. Mais le critère parle
d'EXERCICE, et là la mesure donne autre chose : `AccFiscalYear.state`
(`open`/`closing`/`closed`) n'était **écrit par personne et lu par
personne** — aucun service de clôture, aucun endpoint, aucun écran ; son
unique lecteur était un filtre sur `STATE_OPEN` pour les budgets.

**Un exercice ne pouvait donc pas être clos du tout**, et le verrou de
période ne s'y substitue pas : fermer un exercice ne ferme pas ses
périodes, et rien n'empêchait d'en créer une nouvelle, ouverte, dans un
exercice « clos ». Le champ était décoratif, dans le module où ça se
pardonne le moins.

**Trois choses vont ensemble ici, et aucune ne suffit seule** :

1. la clôture ferme l'exercice ET toutes ses périodes, d'un seul geste
   transactionnel — sans quoi « clos » ne voudrait rien dire pour le
   déclencheur, qui regarde la période ;
2. le déclencheur de base est étendu à l'exercice (migration `0033`), si
   bien que le refus tient même pour une période créée après coup, même
   par `psql`, même pour le propriétaire de la table. C'est ce qui rend le
   critère opposable « à un utilisateur administrateur » : la garantie
   n'est pas applicative ;
3. la clôture refuse de laisser des brouillons derrière elle — les publier
   deviendrait impossible, et ils resteraient indéfiniment en suspens sans
   que personne ne sache pourquoi.

**La réouverture existe, et ce n'est pas un contournement.** Le critère
porte sur les ÉCRITURES d'un exercice clos, pas sur l'irréversibilité de
la clôture : un exercice rouvert n'est plus clos, et le refus continue de
s'appliquer à tous ceux qui le sont. Ne pas offrir de réouverture rendrait
une clôture par erreur irréparable autrement qu'en SQL — un remède pire
que le mal. Elle est en revanche journalisée comme un acte de gouvernance
(`core.services.audit`), et elle refuse de rouvrir un exercice qui n'est
pas le dernier : rouvrir 2024 en laissant 2025 clos produirait des
à-nouveaux incohérents.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.accounting.models import AccFiscalYear, AccMove, AccPeriod
from apps.core.models.user import User
from apps.core.services.audit import log_action


def closing_blockers(year: AccFiscalYear) -> list[str]:
    """Ce qui empêche de clore, en clair et TOUT D'UN COUP.

    Rapporter plutôt que lever au premier problème : un comptable qui
    clôture veut la liste des choses à faire, pas les découvrir une par
    une en relançant la clôture."""
    problemes: list[str] = []

    brouillons = AccMove.objects.filter(period__fiscal_year=year, state=AccMove.STATE_DRAFT).count()
    if brouillons:
        problemes.append(
            _(
                "%(n)s écriture(s) encore en brouillon : les publier ou les "
                "supprimer avant de clore, car la clôture les rendrait "
                "définitivement impubliables."
            )
            % {"n": brouillons}
        )

    if not year.periods.exists():
        problemes.append(
            _(
                "Aucune période rattachée à cet exercice : le clore ne "
                "fermerait rien, et une écriture pourrait encore y entrer par "
                "une période créée après coup."
            )
        )
    return problemes


@transaction.atomic
def close_fiscal_year(year: AccFiscalYear, *, by: User) -> AccFiscalYear:
    """Clôt l'exercice ET toutes ses périodes, ou refuse en nommant ce qui
    bloque.

    Les deux écritures dans la même transaction : un exercice marqué clos
    dont les périodes seraient restées ouvertes serait le pire des deux
    états — l'écran dirait « clos » et la base accepterait les écritures."""
    if year.state == AccFiscalYear.STATE_CLOSED:
        raise ValidationError(_("L'exercice « %(code)s » est déjà clos.") % {"code": year.code})

    problemes = closing_blockers(year)
    if problemes:
        raise ValidationError(problemes)

    year.periods.update(state=AccPeriod.STATE_CLOSED)
    year.state = AccFiscalYear.STATE_CLOSED
    year.save(update_fields=["state"])
    log_action(
        "accounting.fiscal_year_closed",
        actor=by,
        obj=year,
        metadata={
            "code": year.code,
            "date_start": str(year.date_start),
            "date_end": str(year.date_end),
            "periodes_fermees": year.periods.count(),
        },
    )
    return year


@transaction.atomic
def reopen_fiscal_year(year: AccFiscalYear, *, by: User, motif: str) -> AccFiscalYear:
    """Rouvre un exercice clos — acte de gouvernance, jamais de routine.

    Refuse de rouvrir un exercice qui n'est pas le DERNIER clos : rouvrir
    2024 en laissant 2025 clos produirait des à-nouveaux incohérents, et
    l'incohérence ne se verrait qu'à la liasse suivante.

    Le motif est obligatoire et journalisé. Une réouverture sans motif
    écrit est exactement ce qu'un contrôle fiscal demandera d'expliquer."""
    if year.state != AccFiscalYear.STATE_CLOSED:
        raise ValidationError(_("L'exercice « %(code)s » n'est pas clos.") % {"code": year.code})
    if not motif.strip():
        raise ValidationError(_("Une réouverture d'exercice exige un motif écrit."))

    posterieur_clos = (
        AccFiscalYear.objects.filter(
            tenant=year.tenant,
            state=AccFiscalYear.STATE_CLOSED,
            date_start__gt=year.date_start,
        )
        .order_by("date_start")
        .first()
    )
    if posterieur_clos is not None:
        raise ValidationError(
            _(
                "L'exercice « %(posterieur)s » est clos et postérieur : le "
                "rouvrir d'abord, sinon les à-nouveaux de « %(posterieur)s » "
                "reposeraient sur un exercice en cours de modification."
            )
            % {"posterieur": posterieur_clos.code}
        )

    year.state = AccFiscalYear.STATE_OPEN
    year.save(update_fields=["state"])
    year.periods.update(state=AccPeriod.STATE_OPEN)
    log_action(
        "accounting.fiscal_year_reopened",
        actor=by,
        obj=year,
        metadata={"code": year.code, "motif": motif},
    )
    return year
