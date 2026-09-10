"""T9 (bloc H) — la console de gouvernance des flux.

**Quatre écrans, et pour trois d'entre eux le moteur existait déjà sans
appelant.** C'est le motif que ce chantier rencontre à chaque lot, et il
est ici particulièrement net :

- **Consentement de sortie (CON-2)** — le registre de schémas du §9.2
  existait depuis le lot T0 ; il manquait le modèle, la dérivation des
  catégories, la garde d'activation et l'écran.
- **Révocation (CON-3)** — la purge de charge utile (FLX-5) et le filtre
  `active` de la vidange existaient ; il manquait l'état « révoquée »
  distinct de « suspendue », la proposition de purge et l'écran.
- **Panneau de rejeu (CON-4)** — `estimate_replay` existe depuis le sprint
  S4, et sa docstring dit littéralement « ce que l'écran doit afficher
  AVANT que quiconque ne confirme ». **C'est l'écran qui manquait**, depuis
  ce jour-là.
- **Jauge de plafond (CON-5)** — `cost_total` calculait le total d'une
  période sans aucun appelant ; il manquait le plafond lui-même, son alerte
  anticipée et la jauge.

**Qui y a accès.** `flows.change_flwlink` — et non `view` : ces écrans
DÉCIDENT (on consent, on révoque, on rejoue, on plafonne). Le journal, lui,
se contente de `view`. `rbac_policy` accorde déjà les deux à `admin` et
`direction`, et à eux seuls.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.user import User
from apps.core.views.tenant_web import resolve_tenant
from apps.flows.models import FlwExchange, FlwLink
from apps.flows.pricing_regimes import requires_a_cap
from apps.flows.services.consent import (
    consent_covers_current_scope,
    current_consent,
    describe_consent,
    record_consent,
)
from apps.flows.services.cost_cap import budget_for
from apps.flows.services.public import activate_link
from apps.flows.services.replay import estimate_replay, replay_selection
from apps.flows.services.revocation import (
    purge_remaining_payloads,
    remaining_payload_count,
    revoke_link,
)

#: Le panneau n'affiche pas tout : une console qui rendrait dix mille
#: lignes serait inutilisable, et le §10.2 la veut filtrable. Le plafond est
#: DIT à l'écran plutôt que silencieux — une troncature muette ferait croire
#: qu'il n'y a rien de plus à rejouer.
REJOUABLES_AFFICHES = 200


def _refuse_sans_droit(request: HttpRequest) -> HttpResponse | None:
    """Même forme que `core.views.admin_users`, seul autre écran du dépôt
    gardé par une permission : `require_permission` est conçu pour un
    endpoint django-ninja et rendrait du JSON à un navigateur."""
    if not request.user.has_perm("flows.change_flwlink"):
        return HttpResponse(status=403)
    return None


def _erreur(exc: Exception) -> str:
    return "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


@login_required
def link_list(request: HttpRequest) -> HttpResponse:
    """La liste des raccordements — **et c'est elle qui rend la console
    atteignable**.

    Sans elle, la fiche de gouvernance existerait à une URL que personne ne
    connaît : le motif « rien de décoratif » que ce lot corrige justement
    sur quatre mécanismes. Elle est volontairement minimale — le catalogue
    de connecteurs et la fiche de liaison complète du §10.2 ne sont couverts
    par aucun critère CON, et les construire ici élargirait le lot sans
    qu'aucune exigence ne le demande."""
    denied = _refuse_sans_droit(request)
    if denied is not None:
        return denied

    liaisons = FlwLink.objects.select_related("connector").order_by("connector__code", "name").all()
    moment = timezone.now()
    lignes = [
        {
            "link": liaison,
            "budget": budget_for(liaison, now=moment),
            "consent": current_consent(liaison),
        }
        for liaison in liaisons
    ]
    return render(request, "flows/link_list.html", {"rows": lignes})


@login_required
def link_console(request: HttpRequest, link_id: str) -> HttpResponse:
    """La fiche de gouvernance d'une liaison : ce qui sortirait, ce qui a
    été consenti, où en est le plafond, et les deux décisions possibles.

    **Un seul écran pour les quatre critères**, et ce n'est pas une
    économie de gabarits : consentir, plafonner et révoquer sont trois
    faces d'une même question — « qu'est-ce que j'autorise à sortir, et
    jusqu'où ». Les séparer obligerait l'exploitant à recoller lui-même ce
    que le cahier présente ensemble au §9.1."""
    denied = _refuse_sans_droit(request)
    if denied is not None:
        return denied

    link = get_object_or_404(FlwLink.objects.select_related("connector"), id=link_id)
    user = cast(User, request.user)
    erreur = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "consent":
                record_consent(link, granted_by=user)
            elif action == "set_cap":
                link.monthly_cost_cap_ariary = _lire_plafond(request.POST.get("cap", ""))
                link.cost_alert_threshold_pct = _lire_seuil(
                    request.POST.get("threshold", ""), link.cost_alert_threshold_pct
                )
                link.save(update_fields=["monthly_cost_cap_ariary", "cost_alert_threshold_pct"])
            elif action == "activate":
                activate_link(link.tenant, connector_code=link.connector.code)
            elif action == "revoke":
                revoke_link(link, revoked_by=user, reason=request.POST.get("reason", ""))
            elif action == "purge":
                # CON-3, seconde décision : PROPOSER la purge, jamais la
                # faire d'office. Le contenu échangé peut encore servir à
                # une réclamation ou à un contrôle.
                purge_remaining_payloads(link)
        except (ValidationError, ValueError, InvalidOperation) as exc:
            erreur = _erreur(exc)
        else:
            return redirect("flows:link_console", link_id=link.id)

    link.refresh_from_db()
    budget = budget_for(link, now=timezone.now())
    consentement = current_consent(link)

    return render(
        request,
        "flows/link_console.html",
        {
            "link": link,
            "connector": link.connector,
            "error": erreur,
            # CON-2 : les quatre informations du §9.1, dérivées et jamais
            # rédigées à la main.
            "consent_preview": describe_consent(link),
            "consent": consentement,
            "consent_covers_scope": consent_covers_current_scope(link),
            "cap_required": requires_a_cap(link.connector.pricing_regime),
            # CON-5 : la jauge.
            "budget": budget,
            # CON-3 : le chiffre qui rend la proposition de purge
            # intelligible — « 0 » dispense de la poser.
            "remaining_payloads": remaining_payload_count(link),
            "states": FlwLink.STATE_CHOICES,
        },
    )


def _lire_plafond(brut: str) -> Decimal | None:
    """Une saisie vide vaut « aucun plafond », jamais « zéro ».

    Les confondre bloquerait tout envoi sur une liaison dont quelqu'un a
    effacé le champ par mégarde."""
    valeur = (brut or "").strip()
    if not valeur:
        return None
    montant = Decimal(valeur.replace(",", "."))
    if montant < 0:
        raise ValidationError(_("Un plafond négatif n'a pas de sens."))
    return montant


def _lire_seuil(brut: str, defaut: int) -> int:
    valeur = (brut or "").strip()
    if not valeur:
        return defaut
    seuil = int(valeur)
    if not 1 <= seuil <= 99:
        raise ValidationError(
            _(
                "Le seuil d'alerte s'exprime entre 1 et 99 %% du plafond : "
                "à 100 %% l'alerte ne serait plus « avant l'atteinte »."
            )
        )
    return seuil


@login_required
def replay_panel(request: HttpRequest) -> HttpResponse:
    """CON-4 — « le panneau de rejeu affiche volume et coût estimé avant
    confirmation ; aucun rejeu de masse n'est déclenchable sans cette
    estimation ».

    **Deux temps, et le second porte le premier.** L'écran estime, puis
    confirme en REPASSANT l'estimation vue. `replay_selection` la confronte
    à l'estimation courante et refuse si la sélection a changé entre les
    deux : c'est ce qui distingue une estimation opposable d'un chiffre
    affiché. Faire porter la règle à l'écran seul l'aurait rendue
    contournable en appelant le service — la faiblesse déjà refusée pour la
    garde d'activation."""
    denied = _refuse_sans_droit(request)
    if denied is not None:
        return denied

    tenant = resolve_tenant(request)
    ids = [i for i in request.POST.getlist("ids") if i]
    estimation = None
    rejoues = None
    erreur = None

    if request.method == "POST" and ids:
        try:
            estimation = estimate_replay(tenant, ids=ids)
            if request.POST.get("action") == "confirm":
                rejoues = len(replay_selection(tenant, ids=ids, acknowledged=estimation))
        except (ValidationError, ValueError) as exc:
            erreur = _erreur(exc)

    rejouables = FlwExchange.objects.filter(
        tenant=tenant,
        state__in=[FlwExchange.STATE_FAILED, FlwExchange.STATE_REJECTED],
    ).select_related("link__connector")[:REJOUABLES_AFFICHES]

    return render(
        request,
        "flows/replay_panel.html",
        {
            "exchanges": rejouables,
            "estimate": estimation,
            "selected_ids": ids,
            "replayed": rejoues,
            "error": erreur,
            "shown_limit": REJOUABLES_AFFICHES,
        },
    )


__all__: list[str] = ["link_console", "replay_panel"]
