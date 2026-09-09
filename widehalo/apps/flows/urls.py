"""T8 (bloc H) — les routes d'ecran du hub de flux.

`apps/flows` n'en avait aucune : le socle etait construit, servi par une API
publique et par un point d'entree de webhook, et il n'avait pas d'ecran. Le
journal des echanges (CON-1) est le premier.
"""

from django.urls import path

from apps.flows import views

app_name = "flows"

urlpatterns = [
    path("", views.exchange_journal, name="journal"),
]
