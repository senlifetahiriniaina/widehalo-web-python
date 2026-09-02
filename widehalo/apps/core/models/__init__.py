from apps.core.models.audit import AuditLog
from apps.core.models.backup import TenantBackupSchedule, TenantDataOperation
from apps.core.models.base import BaseModel, ReferenceMixin, TenantManager
from apps.core.models.chatter import ChatterMessage
from apps.core.models.document import Document
from apps.core.models.event import EventLog
from apps.core.models.idempotency import IdempotencyKey
from apps.core.models.notification import Notification, WhatsAppMessage
from apps.core.models.quality import QltChecklistTemplate, QltInspection
from apps.core.models.rbac import RoleProfile
from apps.core.models.regulatory import CountryDefaultsProfile, RegulatoryParameter
from apps.core.models.risk import RiskItem
from apps.core.models.search import SearchDocument
from apps.core.models.sequence import Sequence
from apps.core.models.tenant import Tenant
from apps.core.models.ui import SavedTableView
from apps.core.models.user import User, UserEmailChangeRequest, UserTenantMembership
from apps.core.models.workflow import (
    ApprovalDelegation,
    ApprovalRequest,
    ApprovalRule,
    StateTransitionLog,
)

# Modele reserve aux tests d'architecture/isolation (jamais expose en API ni
# en ecran) : importe ici uniquement pour que Django le decouvre et genere
# sa migration. `test_budget.py` l'exclut explicitement du comptage V1.
from apps.core.tests.models import SampleTenantScopedRecord  # noqa: E402

__all__ = [
    "BaseModel",
    "ReferenceMixin",
    "TenantManager",
    "AuditLog",
    "TenantBackupSchedule",
    "TenantDataOperation",
    "ChatterMessage",
    "Document",
    "EventLog",
    "IdempotencyKey",
    "Notification",
    "WhatsAppMessage",
    "RoleProfile",
    "CountryDefaultsProfile",
    "RegulatoryParameter",
    "QltChecklistTemplate",
    "QltInspection",
    "RiskItem",
    "SearchDocument",
    "Sequence",
    "SavedTableView",
    "Tenant",
    "User",
    "UserEmailChangeRequest",
    "UserTenantMembership",
    "ApprovalDelegation",
    "ApprovalRequest",
    "ApprovalRule",
    "StateTransitionLog",
    "SampleTenantScopedRecord",
]
