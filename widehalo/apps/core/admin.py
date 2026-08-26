from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership


@admin.register(Tenant)
class TenantAdmin(ModelAdmin):
    list_display = ("code", "name", "country_code", "base_currency", "is_active")
    search_fields = ("code", "name", "nif")


@admin.register(User)
class UserAdmin(ModelAdmin):
    list_display = ("email", "first_name", "last_name", "is_active", "is_staff")
    search_fields = ("email", "first_name", "last_name")


@admin.register(UserTenantMembership)
class UserTenantMembershipAdmin(ModelAdmin):
    list_display = ("user", "tenant", "is_default")
