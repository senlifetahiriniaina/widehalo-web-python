"""UXR1 — ecran admin de gestion des utilisateurs (SmartTable + edition
roles/societes/e-mail), garde par la permission personnalisee
`core.manage_users` (cf. `apps.core.services.rbac_policy`, restreinte a
`admin`/`direction`). Meme patron que les autres ecrans de liste/edition de
ce depot (ex. `apps.partners.views`) : `smart_table_response` pour la
liste, `full_clean()`/`save()` manuel pour l'edition (aucun `forms.py` dans
ce depot, cf. docstring de `apps.core.views.auth_web.profile_view`).

**Changement d'e-mail** : jamais une ecriture directe de `User.email`
depuis cet ecran — un email different dans le POST declenche
`apps.core.services.email_change.request_email_change` (lien de
confirmation envoye a la NOUVELLE adresse), cf. sa docstring pour la
justification complete."""

from __future__ import annotations

from typing import cast

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.db.models import F
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.models.tenant import Tenant
from apps.core.models.user import PREFERRED_LANGUAGE_CHOICES, User, UserTenantMembership
from apps.core.services.email_change import request_email_change
from apps.core.views.smart_table import Column, smart_table_response

COLUMNS = [
    Column(key="email", label="E-mail"),
    Column(key="first_name", label="Prénom"),
    Column(key="last_name", label="Nom"),
    Column(key="phone", label="Téléphone"),
]


def _forbidden_unless_can_manage_users(request: HttpRequest) -> HttpResponse | None:
    if not request.user.has_perm("core.manage_users"):
        return HttpResponse(status=403)
    return None


@login_required
def admin_user_list(request: HttpRequest) -> HttpResponse:
    denied = _forbidden_unless_can_manage_users(request)
    if denied is not None:
        return denied
    # `User` n'herite pas de `BaseModel` (compte global, jamais tenant-scope)
    # et n'a donc pas de champ `created_at` — `smart_table_response` trie
    # dessus par defaut (`-created_at`) tant qu'aucun `sort` n'est soumis en
    # GET. Alias via `date_joined` (equivalent le plus proche disponible sur
    # `AbstractUser`) plutot que de modifier le composant transversal pour
    # ce seul appelant.
    queryset = User.objects.filter(is_active=True).annotate(created_at=F("date_joined"))
    return smart_table_response(
        request,
        table_key="core.admin_users",
        columns=COLUMNS,
        queryset=queryset,
        page_template="admin_users_list.html",
        page_context={"row_url_name": "admin_user_edit"},
    )


@login_required
def admin_user_edit(request: HttpRequest, user_id: str) -> HttpResponse:
    denied = _forbidden_unless_can_manage_users(request)
    if denied is not None:
        return denied

    target_user = get_object_or_404(User, id=user_id)
    error = None
    email_change_pending = request.GET.get("email_change_pending") == "1"

    if request.method == "POST":
        target_user.first_name = request.POST.get("first_name", "").strip()
        target_user.last_name = request.POST.get("last_name", "").strip()
        target_user.phone = request.POST.get("phone", "").strip()
        preferred_language = request.POST.get("preferred_language", "").strip()
        valid_languages = {code for code, _label in PREFERRED_LANGUAGE_CHOICES}
        target_user.preferred_language = (
            preferred_language if preferred_language in valid_languages else "fr"
        )

        new_email = request.POST.get("email", "").strip()
        triggers_email_change = bool(new_email) and new_email != target_user.email

        target_user.save(update_fields=["first_name", "last_name", "phone", "preferred_language"])

        group_ids = request.POST.getlist("groups")
        target_user.groups.set(Group.objects.filter(id__in=group_ids))

        submitted_tenant_ids = set(request.POST.getlist("tenants"))
        current_memberships = UserTenantMembership.objects.filter(user=target_user)
        current_tenant_ids = {str(m.tenant_id) for m in current_memberships}
        for tenant_id in submitted_tenant_ids - current_tenant_ids:
            UserTenantMembership.objects.create(user=target_user, tenant_id=tenant_id)
        removed_tenant_ids = current_tenant_ids - submitted_tenant_ids
        if removed_tenant_ids:
            current_memberships.filter(tenant_id__in=removed_tenant_ids).delete()

        if triggers_email_change:
            request_email_change(target_user, new_email, requested_by=cast(User, request.user))
            return redirect(f"{request.path}?email_change_pending=1")
        return redirect("admin_user_edit", user_id=target_user.id)

    return render(
        request,
        "admin_users_edit.html",
        {
            "target_user": target_user,
            "error": error,
            "email_change_pending": email_change_pending,
            "language_choices": PREFERRED_LANGUAGE_CHOICES,
            "all_groups": Group.objects.order_by("name"),
            "user_group_ids": set(target_user.groups.values_list("id", flat=True)),
            "all_tenants": Tenant.objects.order_by("name"),
            "user_tenant_ids": set(
                UserTenantMembership.objects.filter(user=target_user).values_list(
                    "tenant_id", flat=True
                )
            ),
        },
    )
