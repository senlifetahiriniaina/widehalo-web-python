from django.urls import path

from apps.feasibility import views

app_name = "feasibility"

urlpatterns = [
    path("", views.study_list, name="list"),
    # `create` reste le point d'entree "Nouvelle etude" (cf. list.html) mais
    # pointe desormais vers l'etape 1 de l'assistant guide (UXR6) au lieu
    # de l'ancien ecran unique.
    path("new/", views.study_wizard_step1, name="create"),
    path("wizard/<uuid:study_id>/step2/", views.study_wizard_step2, name="wizard_step2"),
    path("wizard/<uuid:study_id>/step3/", views.study_wizard_step3, name="wizard_step3"),
    path("<uuid:study_id>/", views.study_detail, name="detail"),
]
