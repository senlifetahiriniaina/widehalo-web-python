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
    list_display = (
        "code",
        "tenant",
        "version",
        "valid_from",
        "valid_to",
        "statut_validation",
        "valide_par",
        "valide_le",
    )
    list_filter = ("statut_validation",)
    search_fields = ("code",)
    actions = ["validate_oecfm"]

    @admin.action(description="Valider (expert-comptable OECFM)")
    def validate_oecfm(self, request, queryset):
        # ACC-8/ACC-9 (cahier des charges Phase 1 §13.3) : seule action qui
        # fait passer statut_validation a VALIDE_OECFM — jamais un defaut,
        # jamais automatique. `mark_validated` journalise via le signal
        # `_on_regulatory_parameter_save` (cf. apps.core.audit_signals).
        count = 0
        for parameter in queryset:
            parameter.mark_validated(request.user)
            count += 1
        self.message_user(request, f"{count} paramètre(s) marqué(s) validé(s) OECFM.")


@admin.register(CountryDefaultsProfile)
class CountryDefaultsProfileAdmin(ModelAdmin):
    list_display = ("country_code", "base_currency", "default_language", "vat_rate")
