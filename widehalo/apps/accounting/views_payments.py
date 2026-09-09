"""T5 (bloc D, PAY-3 et PAY-5) — l'écran des encaissements mobiles.

**Le critère PAY-3** : « un paiement reçu sans correspondance est placé en
attente de rapprochement, **visible dans un écran dédié**, et ne produit
aucune écriture tant qu'il n'est pas affecté ». Les trois exigences vont
ensemble, et sans l'écran les deux autres ne servent à rien : une
notification orpheline invisible n'est pas « en attente », elle est perdue.

**Ce que cet écran rend possible et qui n'existait nulle part.**
`payment_payouts.settle_payout` produit le rapprochement de second niveau
de PAY-5 — et sans cet écran, RIEN ne l'appellerait. C'est le défaut que
ce chantier rencontre à chaque lot, et il ne se voit qu'en cherchant les
appelants : du code complet, documenté, testé, que personne n'invoque.
L'affectation manuelle d'une orpheline et le rapprochement d'un versement
sont donc ici, dans l'écran, parce que ce sont des DÉCISIONS — et le §4.3
réserve précisément les décisions à un humain quand la corrélation
automatique n'a pas abouti.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect

from apps.accounting.models import AccAggregatorPayout, AccMove, AccPaymentNotification
from apps.accounting.services.payment_payouts import settle_payout
from apps.accounting.services.payment_settlement import assign_orphan_notification
from apps.core.views.smart_table import Column, smart_table_response

NOTIFICATION_COLUMNS = [
    Column(key="external_reference", label="Référence"),
    Column(key="provider_code", label="Voie"),
    Column(key="amount", label="Montant", searchable=False),
    Column(key="fee_amount", label="Commission", searchable=False),
    Column(key="state", label="État"),
    Column(key="received_at", label="Reçue le", searchable=False),
]


@login_required
def payment_notification_list(request: HttpRequest) -> HttpResponse:
    """PAY-3 — la liste, filtrable par état.

    **Le filtre par défaut est ORPHELINE, et ce n'est pas un détail
    d'ergonomie.** L'écran existe pour ce qui attend une décision ; ouvrir
    sur l'ensemble des notifications noierait les trois qui demandent un
    geste dans les milliers qui n'en demandent aucun, et l'exigence
    « visible dans un écran dédié » serait tenue à la lettre et perdue en
    pratique."""
    etat = request.GET.get("state") or AccPaymentNotification.STATE_ORPHAN
    queryset = AccPaymentNotification.objects.all()
    if etat != "toutes":
        queryset = queryset.filter(state=etat)
    return smart_table_response(
        request,
        table_key="accounting.payment_notifications",
        columns=NOTIFICATION_COLUMNS,
        queryset=queryset.order_by("-received_at"),
        page_template="accounting/payment_notifications.html",
        page_context={
            "state_filter": etat,
            "states": AccPaymentNotification.STATE_CHOICES,
            "payouts": _pending_payouts(),
            # Les deux listes de l'action de l'écran. Sans elles, le
            # formulaire d'affectation demanderait de saisir un UUID à la
            # main — c'est-à-dire qu'il ne serait jamais utilisé, et que
            # `assign_orphan_notification` n'aurait, en pratique, pas
            # d'appelant.
            "orphans": _orphan_notifications(),
            "open_invoices": _unpaid_invoices(),
        },
    )


@login_required
def payment_notification_assign(request: HttpRequest, notification_id: str) -> HttpResponse:
    """PAY-3 — « ne produit aucune écriture **tant qu'il n'est pas affecté** ».

    C'est ici que l'affectation a lieu, et c'est un humain qui la fait : la
    corrélation automatique a échoué, et lui substituer une seconde
    heuristique — « le montant et la date correspondent » — serait
    exactement ce que l'interdit du §4.3 refuse."""
    notification = get_object_or_404(AccPaymentNotification, id=notification_id)
    if request.method != "POST":
        return redirect("accounting:payment_notifications")

    erreur = ""
    try:
        assign_orphan_notification(notification, invoice_id=request.POST.get("invoice_id", ""))
    except ValidationError as exc:
        erreur = "; ".join(exc.messages)

    return _back_to_list(erreur)


@login_required
def aggregator_payout_settle(request: HttpRequest, payout_id: str) -> HttpResponse:
    """PAY-5 — rapproche un versement groupé du lot qu'il couvre.

    Le service refuse tout seul ce qui ne tombe pas juste ; l'écran ne
    fait que porter la décision de lancer le rapprochement, et rend le
    motif quand il échoue. Refaire ici les contrôles de montants
    produirait deux vérités sur le même sujet."""
    versement = get_object_or_404(AccAggregatorPayout, id=payout_id)
    if request.method != "POST":
        return redirect("accounting:payment_notifications")

    resultat = settle_payout(versement)
    return _back_to_list("" if resultat.produced_an_entry else resultat.detail or resultat.outcome)


def _orphan_notifications() -> list[AccPaymentNotification]:
    """Ce qui attend une décision, et rien d'autre.

    Distinct de la table du haut, qui est filtrable : le formulaire ne doit
    proposer QUE des orphelines, parce qu'affecter une notification déjà
    rapprochée écrirait un second encaissement pour le même argent."""
    return list(
        AccPaymentNotification.objects.filter(state=AccPaymentNotification.STATE_ORPHAN).order_by(
            "-received_at"
        )[:50]
    )


def _unpaid_invoices() -> list[AccMove]:
    """Les factures publiées qui restent à encaisser.

    Publiées, parce que `register_payment` refuse tout le reste ; non
    soldées, parce que proposer une facture déjà payée n'aiderait qu'à
    créer un encaissement de trop."""
    return list(
        AccMove.objects.filter(
            move_type=AccMove.TYPE_CUSTOMER_INVOICE,
            state=AccMove.STATE_POSTED,
        )
        .exclude(invoice_state=AccMove.INVOICE_STATE_PAID)
        .order_by("-date")[:100]
    )


def _pending_payouts() -> list[dict[str, Any]]:
    """Les versements qui attendent d'être rapprochés.

    Rendus sur le MÊME écran que les notifications, parce que c'est la même
    question posée à deux échelles : « cet argent, à quoi correspond-il ? ».
    Deux écrans obligeraient l'exploitant à faire lui-même le lien entre le
    compte de passage qui ne se solde pas et le versement qu'il n'a pas
    rapproché."""
    return [
        {
            "id": versement.id,
            "external_reference": versement.external_reference,
            "payout_date": versement.payout_date,
            "gross_amount": versement.gross_amount,
            "fee_amount": versement.fee_amount,
            "net_amount": versement.net_amount,
            "state": versement.get_state_display(),
            "settled": versement.state == AccAggregatorPayout.STATE_SETTLED,
        }
        for versement in AccAggregatorPayout.objects.exclude(
            state=AccAggregatorPayout.STATE_SETTLED
        ).order_by("-payout_date")[:20]
    ]


def _back_to_list(erreur: str) -> HttpResponse:
    """Retour à la liste, avec le motif en clair s'il y en a un.

    Le motif passe par l'URL plutôt que par un message éphémère : un
    rapprochement refusé pour discordance de montants demande qu'on aille
    lire un relevé, ce qui prend plus longtemps qu'un rechargement de
    page."""
    cible = redirect("accounting:payment_notifications")
    if erreur:
        cible["Location"] = f"{cible['Location']}?error={erreur}"
    return cible


__all__ = [
    "aggregator_payout_settle",
    "payment_notification_assign",
    "payment_notification_list",
]
