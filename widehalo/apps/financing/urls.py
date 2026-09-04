from django.urls import path

from apps.financing import views

app_name = "financing"

urlpatterns = [
    path("", views.loan_application_list, name="list"),
    path("new/", views.loan_application_create, name="create"),
    path("<uuid:application_id>/", views.loan_application_detail, name="detail"),
    path("credocs/", views.credoc_list, name="credoc-list"),
    path("credocs/new/", views.credoc_create, name="credoc-create"),
    path("credocs/<uuid:credoc_id>/", views.credoc_detail, name="credoc-detail"),
    path(
        "credocs/<uuid:credoc_id>/dossier/",
        views.credoc_dossier_timeline,
        name="credoc-dossier-timeline",
    ),
]
