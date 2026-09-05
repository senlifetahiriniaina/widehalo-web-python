from django.urls import path

from apps.core.views import (
    backup_admin,
    chatter,
    dashboard,
    pages,
    quality,
    risk,
    scheduling,
    smart_table,
)

urlpatterns = [
    path("dashboard/", dashboard.dashboard, name="dashboard"),
    path("search/", pages.search_page, name="search"),
    path("search/instant/", pages.instant_search_fragment, name="instant_search"),
    path("documents/", pages.documents_list, name="documents"),
    path(
        "documents/bulk-archive/",
        pages.documents_bulk_archive,
        name="documents_bulk_archive",
    ),
    path("settings/", pages.settings_page, name="settings"),
    path(
        "settings/design-system/",
        pages.design_system_preview,
        name="design_system_preview",
    ),
    path("settings/company-profile/", pages.company_profile_view, name="company_profile"),
    path("settings/shell/toggle/", pages.toggle_shell, name="toggle_shell"),
    path(
        "smart-table/save-view/",
        smart_table.save_current_view,
        name="smart_table_save_view",
    ),
    path(
        "chatter/<str:app_label>/<str:model>/<str:object_id>/",
        chatter.chatter_thread,
        name="chatter_thread",
    ),
    path("launchpad/", pages.launchpad, name="launchpad"),
    path("notifications/bell/", pages.notifications_bell_fragment, name="notifications_bell"),
    path(
        "notifications/<uuid:notification_id>/read/",
        pages.notification_mark_read,
        name="notification_mark_read",
    ),
    path("backups/", backup_admin.backup_list, name="backup_list"),
    path(
        "backups/<uuid:document_id>/download/",
        backup_admin.backup_download,
        name="backup_download",
    ),
    path("backups/schedule/", backup_admin.backup_schedule_view, name="backup_schedule"),
    path("backups/reset/", backup_admin.reset_company_data, name="reset_company_data"),
    path(
        "settings/scheduled-commands/",
        scheduling.scheduled_commands_view,
        name="scheduled_commands",
    ),
    path("risks/", risk.risk_list, name="risk_list"),
    path("risks/new/", risk.risk_create, name="risk_create"),
    path("risks/<uuid:risk_id>/", risk.risk_detail, name="risk_detail"),
    path("quality/templates/", quality.template_list, name="qlt_template_list"),
    path("quality/templates/new/", quality.template_create, name="qlt_template_create"),
    path(
        "quality/templates/<uuid:template_id>/",
        quality.template_detail,
        name="qlt_template_detail",
    ),
    path("quality/inspections/", quality.inspection_list, name="qlt_inspection_list"),
    path("quality/inspections/new/", quality.inspection_create, name="qlt_inspection_create"),
    path(
        "quality/inspections/<uuid:inspection_id>/",
        quality.inspection_detail,
        name="qlt_inspection_detail",
    ),
]
