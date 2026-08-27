from django.urls import path

from apps.partners import views

app_name = "partners"

urlpatterns = [
    path("", views.partner_list, name="list"),
    path("new/", views.partner_create_wizard, name="wizard"),
    path("duplicates/", views.duplicate_alert_list, name="duplicates"),
    path("merge/", views.partner_merge, name="merge"),
    path("<uuid:partner_id>/", views.partner_detail, name="detail"),
    path("<uuid:partner_id>/edit/", views.partner_edit, name="edit"),
]
