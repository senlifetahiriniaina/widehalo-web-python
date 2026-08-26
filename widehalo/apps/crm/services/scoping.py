"""RG-CRM-5 : portee des opportunites par role, au-dessus de
`core.services.scoping.apply_scope` (N3). Un commercial ne voit que ses
propres opportunites (par vendeur assigne, pas par createur — un admin ou
un import peut creer un lead pour un autre commercial), un resp_commercial
voit celles de son equipe (dirigee ou dont il est membre), direction/admin
voient tout."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.core.models.user import User
from apps.core.services.scoping import apply_scope
from apps.crm.models import CrmLead, CrmTeam

UNRESTRICTED_ROLES = {"direction", "admin"}
TEAM_LEAD_ROLES = {"resp_commercial"}


def scope_leads_for_user(queryset: QuerySet[CrmLead], user: User) -> QuerySet[CrmLead]:
    role_codes = set(user.groups.values_list("name", flat=True))

    if role_codes & UNRESTRICTED_ROLES:
        return apply_scope(queryset, user, "global")

    if role_codes & TEAM_LEAD_ROLES:
        team_ids = CrmTeam.objects.filter(leader=user).values_list("id", flat=True)
        member_team_ids = CrmTeam.objects.filter(members=user).values_list("id", flat=True)
        return queryset.filter(team_id__in=set(team_ids) | set(member_team_ids))

    return queryset.filter(salesperson=user)
