"""T8 (bloc H) — les routes d'ecran du hub de flux.

`apps/flows` n'en avait aucune : le socle etait construit, servi par une API
publique et par un point d'entree de webhook, et il n'avait pas d'ecran. Le
journal des echanges (CON-1) est le premier.
"""

from django.urls import path

from apps.flows import views, views_console

app_name = "flows"

urlpatterns = [
    path("", views.exchange_journal, name="journal"),
    # T9 (bloc H) — la console de gouvernance. Le rejeu est declare AVANT
    # la fiche de liaison : un prefixe litteral doit passer avant un
    # convertisseur `<uuid:...>`, sinon la route generique l'avale.
    path("links/", views_console.link_list, name="link_list"),
    path("replay/", views_console.replay_panel, name="replay_panel"),
    path("<uuid:link_id>/", views_console.link_console, name="link_console"),
]
