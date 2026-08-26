"""Squelette de notifications — implementation complete a l'etape 11
(modele generique, regroupement horaire par e-mail)."""

from __future__ import annotations

from ninja import Router

router = Router(tags=["notifications"])


@router.get("/notifications")
def list_notifications(request):
    return {"results": []}
