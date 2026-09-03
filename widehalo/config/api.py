"""API racine django-ninja (v1).

Toute fonctionnalite du socle et des futurs modules metier est exposee ici
avant de l'etre en ecran (principe API-first du cahier des charges).
Auth JWT par defaut sur tous les routers ; les endpoints publics (login,
health, meta) passent explicitement `auth=None`.
"""

from ninja import NinjaAPI
from ninja_jwt.authentication import JWTAuth

api = NinjaAPI(title="WideHalo API", version="v1", urls_namespace="api-v1", auth=JWTAuth())

from apps.accounting.api import router as accounting_router  # noqa: E402
from apps.ai.api import router as ai_router  # noqa: E402
from apps.analytics.api import router as analytics_router  # noqa: E402
from apps.automation.api import router as automation_router  # noqa: E402
from apps.bi.api import router as bi_router  # noqa: E402
from apps.catalog.api import router as catalog_router  # noqa: E402
from apps.chat.api import router as chat_router  # noqa: E402
from apps.core.api_auth import router as auth_router  # noqa: E402
from apps.core.api_backup import router as backup_router  # noqa: E402
from apps.core.api_export_import import router as export_import_router  # noqa: E402
from apps.core.api_health import router as health_router  # noqa: E402
from apps.core.api_meta import router as meta_router  # noqa: E402
from apps.core.api_notifications import router as notifications_router  # noqa: E402
from apps.core.api_quality import router as quality_router  # noqa: E402
from apps.core.api_risk import router as risk_router  # noqa: E402
from apps.core.api_search import router as search_router  # noqa: E402
from apps.core.api_tenants import router as tenants_router  # noqa: E402
from apps.core.api_workflow import router as workflow_router  # noqa: E402
from apps.core.errors import register_exception_handlers  # noqa: E402
from apps.crm.api import router as crm_router  # noqa: E402
from apps.feasibility.api import router as feasibility_router  # noqa: E402
from apps.financing.api import router as financing_router  # noqa: E402
from apps.helpdesk.api import router as helpdesk_router  # noqa: E402
from apps.logistics.api import router as logistics_router  # noqa: E402
from apps.mrp.api import router as mrp_router  # noqa: E402
from apps.partners.api import router as partners_router  # noqa: E402
from apps.patronage.api import router as patronage_router  # noqa: E402
from apps.payroll.api import router as payroll_router  # noqa: E402
from apps.pos.api import router as pos_router  # noqa: E402
from apps.presence.api import router as presence_router  # noqa: E402
from apps.projects.api import router as projects_router  # noqa: E402
from apps.purchase.api import router as purchase_router  # noqa: E402
from apps.reporting.api import router as reporting_router  # noqa: E402
from apps.sales.api import router as sales_router  # noqa: E402
from apps.simulation.api import router as simulation_router  # noqa: E402
from apps.stocks.api import router as stocks_router  # noqa: E402
from apps.strategy.api import router as strategy_router  # noqa: E402

api.add_router("/auth", auth_router)
api.add_router("/core", backup_router)
api.add_router("", accounting_router)
api.add_router("", ai_router)
api.add_router("", analytics_router)
api.add_router("", bi_router)
api.add_router("", chat_router)
api.add_router("", crm_router)
api.add_router("", logistics_router)
api.add_router("", mrp_router)
api.add_router("", partners_router)
api.add_router("", patronage_router)
api.add_router("", catalog_router)
api.add_router("", sales_router)
api.add_router("", purchase_router)
api.add_router("", stocks_router)
api.add_router("", presence_router)
api.add_router("", payroll_router)
api.add_router("", reporting_router)
api.add_router("", strategy_router)
api.add_router("", financing_router)
api.add_router("", automation_router)
api.add_router("", feasibility_router)
api.add_router("", projects_router)
api.add_router("", helpdesk_router)
api.add_router("", pos_router)
api.add_router("", simulation_router)
api.add_router("/health", health_router)
api.add_router("", meta_router)
api.add_router("", tenants_router)
api.add_router("", search_router)
api.add_router("", notifications_router)
api.add_router("", risk_router)
api.add_router("", quality_router)
api.add_router("", export_import_router)
api.add_router("", workflow_router)

register_exception_handlers(api)
