from django.urls import path

from apps.partners import views, views_imports

app_name = "partners"

urlpatterns = [
    path("", views.partner_list, name="list"),
    path("new/", views.partner_create_wizard, name="wizard"),
    path("instant-picker/", views.partner_instant_picker, name="instant_picker"),
    path("duplicates/", views.duplicate_alert_list, name="duplicates"),
    path("merge/", views.partner_merge, name="merge"),
    path("imports/", views_imports.imports_partners, name="imports"),
    path(
        "imports/template.xlsx",
        views_imports.download_partner_template,
        name="imports_template",
    ),
    path("<uuid:partner_id>/", views.partner_detail, name="detail"),
    path("<uuid:partner_id>/edit/", views.partner_edit, name="edit"),
]
