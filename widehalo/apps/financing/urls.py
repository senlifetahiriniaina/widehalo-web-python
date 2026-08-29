from django.urls import path

from apps.financing import views

app_name = "financing"

urlpatterns = [
    path("", views.loan_application_list, name="list"),
    path("new/", views.loan_application_create, name="create"),
    path("<uuid:application_id>/", views.loan_application_detail, name="detail"),
]
