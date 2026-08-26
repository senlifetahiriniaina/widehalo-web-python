from apps.core.models.base import BaseModel, ReferenceMixin, TenantManager
from apps.core.models.sequence import Sequence
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership

# Modele reserve aux tests d'architecture/isolation (jamais expose en API ni
# en ecran) : importe ici uniquement pour que Django le decouvre et genere
# sa migration. `test_budget.py` l'exclut explicitement du comptage V1.
from apps.core.tests.models import SampleTenantScopedRecord  # noqa: E402

__all__ = [
    "BaseModel",
    "ReferenceMixin",
    "TenantManager",
    "Sequence",
    "Tenant",
    "User",
    "UserTenantMembership",
    "SampleTenantScopedRecord",
]
