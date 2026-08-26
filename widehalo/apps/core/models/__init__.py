from apps.core.models.base import BaseModel, ReferenceMixin, TenantManager
from apps.core.models.idempotency import IdempotencyKey
from apps.core.models.rbac import RoleProfile
from apps.core.models.sequence import Sequence
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
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
    "IdempotencyKey",
    "RoleProfile",
    "Sequence",
    "Tenant",
    "User",
    "UserTenantMembership",
    "ApprovalDelegation",
    "ApprovalRequest",
    "ApprovalRule",
    "StateTransitionLog",
    "SampleTenantScopedRecord",
]
