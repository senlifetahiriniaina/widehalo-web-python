from django.urls import path

from apps.crm import views

app_name = "crm"

urlpatterns = [
    path("", views.lead_list, name="list"),
    path("new/", views.lead_create, name="create"),
    path("<uuid:lead_id>/", views.lead_detail, name="detail"),
]
