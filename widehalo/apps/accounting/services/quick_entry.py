"""X2 (Sprint 8 / L5, cf. docs/planning/2026-refonte-ux-sprints.md §5) :
saisie comptable rapide — l'écran multi-lignes lui-même délègue
entièrement le cycle de vie à `services/moves.py` (`create_draft_move`,
`add_line`, `post_move`, déjà construits et testés : RG-ACC-1 partie
double, RG-ACC-3 numérotation, RG-ACC-4 périodes closes) — ce module
n'ajoute qu'une seule chose réellement nouvelle : la suggestion de
contrepartie exigée par le CDC ("saisie comptable rapide avec
contreparties suggérées")."""

from __future__ import annotations

from django.db.models import Count

from apps.accounting.models import AccAccount, AccMoveLine
from apps.core.models.tenant import Tenant


def suggest_counterpart_account(*, tenant: Tenant, account: AccAccount) -> AccAccount | None:
    """Compte le plus souvent associé à `account` sur une même écriture,
    toutes écritures confondues (brouillon ou publiée) de ce tenant —
    heuristique de co-occurrence : "quel compte apparaît le plus souvent
    aux côtés de celui-ci sur une même pièce", pas une règle comptable
    figée (aucun mapping en dur, cohérent avec la discipline générale du
    module "aucun barème/compte en dur").

    Retourne `None`, jamais une exception, si `account` n'a encore jamais
    été utilisé aux côtés d'un autre compte (première saisie, aucun
    historique à apprendre) — l'appelant (l'écran) doit alors laisser le
    champ de contrepartie vide plutôt que d'imposer un choix arbitraire."""
    counterpart = (
        AccMoveLine.objects.filter(tenant=tenant, move__lines__account=account)
        .exclude(account=account)
        .values("account")
        .annotate(occurrences=Count("id"))
        .order_by("-occurrences")
        .first()
    )
    if counterpart is None:
        return None
    return AccAccount.objects.filter(tenant=tenant, id=counterpart["account"]).first()
