"""API racine django-ninja (v1).

Toute fonctionnalite du socle et des futurs modules metier est exposee ici
avant de l'etre en ecran (principe API-first du cahier des charges).
Auth JWT par defaut sur tous les routers ; les endpoints publics (login,
health, meta) passent explicitement `auth=None`.
"""

from ninja import NinjaAPI
from ninja_jwt.authentication import JWTAuth

api = NinjaAPI(title="WideHalo API", version="v1", urls_namespace="api-v1", auth=JWTAuth())

from apps.catalog.api import router as catalog_router  # noqa: E402
from apps.chat.api import router as chat_router  # noqa: E402
from apps.core.api_auth import router as auth_router  # noqa: E402
from apps.core.api_export_import import router as export_import_router  # noqa: E402
from apps.core.api_health import router as health_router  # noqa: E402
from apps.core.api_meta import router as meta_router  # noqa: E402
from apps.core.api_notifications import router as notifications_router  # noqa: E402
from apps.core.api_search import router as search_router  # noqa: E402
from apps.core.api_tenants import router as tenants_router  # noqa: E402
from apps.core.api_workflow import router as workflow_router  # noqa: E402
from apps.core.errors import register_exception_handlers  # noqa: E402
from apps.partners.api import router as partners_router  # noqa: E402

api.add_router("/auth", auth_router)
api.add_router("", chat_router)
api.add_router("", partners_router)
api.add_router("", catalog_router)
api.add_router("/health", health_router)
api.add_router("", meta_router)
api.add_router("", tenants_router)
api.add_router("", search_router)
api.add_router("", notifications_router)
api.add_router("", export_import_router)
api.add_router("", workflow_router)

register_exception_handlers(api)
