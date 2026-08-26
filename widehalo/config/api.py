"""API racine django-ninja (v1).

Toute fonctionnalite du socle et des futurs modules metier est exposee ici
avant de l'etre en ecran (principe API-first du cahier des charges).
Complete a l'etape 7 (conventions RFC7807, pagination, idempotency, etc.).
"""

from ninja import NinjaAPI

api = NinjaAPI(title="WideHalo API", version="v1", urls_namespace="api-v1")

from apps.core.api_auth import router as auth_router  # noqa: E402

api.add_router("/auth", auth_router)
