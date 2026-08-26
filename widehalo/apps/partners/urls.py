from django.urls import path

from apps.partners import views

app_name = "partners"

urlpatterns = [
    path("", views.partner_list, name="list"),
    path("new/", views.partner_create_wizard, name="wizard"),
    path("<uuid:partner_id>/", views.partner_detail, name="detail"),
]
