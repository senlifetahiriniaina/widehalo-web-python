from django.urls import path

from apps.accounting import views

app_name = "accounting"

urlpatterns = [
    path("", views.invoice_list, name="list"),
    path("new/", views.invoice_create, name="create"),
    path("<uuid:invoice_id>/", views.invoice_detail, name="detail"),
]
