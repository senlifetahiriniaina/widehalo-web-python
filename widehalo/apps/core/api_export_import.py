"""Squelette d'export/import generique — implementation complete a
l'etape 11 (XLSX/CSV/JSON, asynchrone au-dela de 5000 lignes, assistant
d'import en 3 phases)."""

from __future__ import annotations

from ninja import Router

router = Router(tags=["exports-imports"])


@router.get("/exports")
def list_exports(request):
    return {"results": []}
