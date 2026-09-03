"""Contrat public de l'app `pos` — seule surface que les autres apps
metier auraient le droit d'importer (cf. tests/architecture/
test_module_boundaries.py). Aucun consommateur reel dans ce lot (le POS
est un canal de vente autonome, cf. `module.py`) — expose neanmoins des
primitives d'etat de session, meme discipline que le reste du depot
(chaque app publie un `services/public.py`, meme vide de consommateur
reel a sa livraison initiale — ex. `logistics`/`helpdesk` a leur premier
lot). Point d'accroche naturel pour un futur outil IA `etat_caisse`
(cahier §13.4, deja nomme dans la liste blanche d'outils du copilote —
"Sessions de caisse ouvertes, encaissements du jour par moyen de
paiement, écarts constatés, ventes en attente de synchronisation")."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db.models import Sum

from apps.pos.models import PosOrder, PosPayment, PosSession

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant


def list_open_sessions(tenant: Tenant) -> list[dict[str, Any]]:
    """Primitives uniquement (jamais `PosSession`), pour un futur widget
    de tableau de bord/outil IA — jamais l'objet ORM (regle de couplage
    n1)."""
    return [
        {
            "id": str(session.id),
            "register_code": session.register.code,
            "cashier_id": session.cashier_id,
            "opened_at": session.opened_at,
        }
        for session in PosSession.objects.filter(tenant=tenant, state=PosSession.STATE_OPEN)
        .select_related("register")
        .order_by("opened_at")
    ]


def get_session_cash_summary(session_id: UUID) -> dict[str, Any] | None:
    """État de caisse d'une session : encaissements du jour par moyen de
    paiement, ventes en attente de synchronisation (`PosOrder` en
    `DRAFT`, source hors ligne pas encore validée). Retourne `None`,
    jamais une exception, si la session n'existe pas."""
    session = PosSession.objects.filter(id=session_id).select_related("register").first()
    if session is None:
        return None

    payments_by_method = list(
        PosPayment.objects.filter(order__session=session, order__state=PosOrder.STATE_VALIDATED)
        .values("method__name")
        .annotate(total=Sum("amount"))
        .order_by("method__name")
    )
    pending_orders = PosOrder.objects.filter(
        session=session, state=PosOrder.STATE_DRAFT, source=PosOrder.SOURCE_OFFLINE
    ).count()

    return {
        "session_id": str(session.id),
        "register_code": session.register.code,
        "state": session.state,
        "payments_by_method": [
            {"method": row["method__name"], "total": row["total"] or Decimal(0)}
            for row in payments_by_method
        ],
        "pending_offline_orders": pending_orders,
        "cash_variance": session.cash_variance,
    }
