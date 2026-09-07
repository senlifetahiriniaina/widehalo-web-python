from apps.forecast import views
from django.urls import path

app_name = "forecast"

urlpatterns = [
    path("", views.dashboard, name="index"),
    path("workbench/", views.workbench, name="workbench"),
    path("publish/", views.publish_now, name="publish"),
    # Le calendrier est une donnee de `core` ; l'ecran qui la saisit vit ici
    # parce que l'onglet « calendrier » y vit deja (budget ecrans a 240/240).
    path("calendrier/ajouter/", views.declare_holiday_view, name="holiday_add"),
    path("calendrier/retirer/", views.remove_holiday_view, name="holiday_remove"),
]
