"""Service CSAT `helpdesk` (HD4, cf. plan section modeles ->
`HlpCsatResponse`) : `submit_csat_response(ticket, ...)` — enquete de
satisfaction post-resolution SIMPLE, jamais de prediction CSAT/NPS, jamais
de campagne planifiee (decision de perimetre n°2 actee au cadrage, cf.
`models.py::HlpCsatResponse`)."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.helpdesk.models import HlpCsatResponse, HlpTicket

# Etats a partir desquels une enquete CSAT a un sens : le ticket doit avoir
# ete traite jusqu'a sa resolution (au moins) avant qu'on demande au
# demandeur d'evaluer le service rendu.
_SURVEYABLE_STATES = (HlpTicket.STATE_RESOLVED, HlpTicket.STATE_CLOSED)


def submit_csat_response(ticket: HlpTicket, *, score: int, comment: str = "") -> HlpCsatResponse:
    """Enregistre la reponse CSAT d'un ticket. Refuse (leve
    `ValidationError`, meme convention que le reste du depot, cf.
    `apps.projects.services.billing`) si :
    - `score` hors de l'intervalle metier `[1, 5]` ;
    - le ticket n'est pas encore `resolved`/`closed` (une enquete de
      satisfaction n'a de sens qu'apres traitement) ;
    - une reponse existe deja pour ce ticket — verification EXPLICITE en
      amont (`.exists()`) plutot que de laisser remonter l'`IntegrityError`
      brute du `OneToOneField`, meme patron exact que la garde
      anti-double-facturation de `PrjInvoicingRecord` (PJ5, cf. docstring
      `HlpCsatResponse`)."""
    if not (1 <= score <= 5):
        raise ValidationError(_("La note CSAT doit être comprise entre 1 et 5."))
    if ticket.state not in _SURVEYABLE_STATES:
        raise ValidationError(
            _("L'enquête de satisfaction n'est disponible qu'une fois le ticket résolu ou cloture.")
        )
    if HlpCsatResponse.objects.filter(ticket=ticket).exists():
        raise ValidationError(_("Ce ticket a déjà reçu une réponse CSAT."))

    return HlpCsatResponse.objects.create(
        tenant=ticket.tenant,
        ticket=ticket,
        score=score,
        comment=comment,
    )
