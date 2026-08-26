from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.core.models.audit import AuditLog
from apps.core.models.document import Document
from apps.core.models.rbac import RoleProfile
from apps.core.models.regulatory import CountryDefaultsProfile, RegulatoryParameter
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


@admin.register(RoleProfile)
class RoleProfileAdmin(ModelAdmin):
    list_display = ("code", "group", "simple_mode_default")


@admin.register(Document)
class DocumentAdmin(ModelAdmin):
    list_display = ("original_name", "tenant", "size", "av_scan_status", "reference_count")
    search_fields = ("original_name", "sha256")


@admin.register(AuditLog)
class AuditLogAdmin(ModelAdmin):
    list_display = ("action", "actor", "content_type", "object_id", "created_at")
    search_fields = ("action", "object_id")
    list_filter = ("action",)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RegulatoryParameter)
class RegulatoryParameterAdmin(ModelAdmin):
    list_display = ("code", "tenant", "valid_from", "valid_to")
    search_fields = ("code",)


@admin.register(CountryDefaultsProfile)
class CountryDefaultsProfileAdmin(ModelAdmin):
    list_display = ("country_code", "base_currency", "default_language", "vat_rate")
