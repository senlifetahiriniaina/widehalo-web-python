"""Preferences d'ecran persistees par utilisateur — vues sauvegardees du
composant SmartTable (colonnes visibles, filtre, tri) pour un `table_key`
donne (ex. "partners.list").

`shared_with_role` (§5.11 RPT-SAVE1, chantier `reporting`) : audit mene au
cadrage de ce module — RPT-GRID1 (SmartTable) etait deja pleinement
satisfait, mais RPT-SAVE1 ("vues sauvegardees, partageables PAR ROLE") ne
l'etait qu'a moitie : `SavedTableView` ne portait qu'un partage personnel
(`owner`), aucun mecanisme de partage par role n'existait. Champ ajoute
(vide = personnelle, code de role = partagee avec tout utilisateur de ce
role) — combler ce vrai manque plutot que de le documenter comme deja
satisfait."""

from __future__ import annotations

from django.db import models

from apps.core.models.base import BaseModel


class SavedTableView(BaseModel):
    table_key = models.CharField(max_length=100, db_index=True)
    name = models.CharField(max_length=100)
    owner = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="+")
    columns = models.JSONField(default=list, blank=True)
    filters = models.JSONField(default=dict, blank=True)
    sort = models.CharField(max_length=64, blank=True)
    is_default = models.BooleanField(default=False)
    shared_with_role = models.CharField(max_length=32, blank=True)

    class Meta:
        db_table = "core_saved_table_view"
        constraints = [
            models.UniqueConstraint(fields=["owner", "table_key", "name"], name="uniq_saved_view")
        ]

    def __str__(self) -> str:
        return f"{self.table_key}:{self.name}"


class ScreenPreference(BaseModel):
    """Comment CET utilisateur regarde CET ecran : liste ou kanban.

    **Pourquoi un modele distinct de `SavedTableView`.** Celui-ci est
    unique sur `(owner, table_key, name)` : c'est une vue NOMMEE, un jeu de
    filtres et de colonnes qu'on enregistre et qu'on partage par role
    (RPT-SAVE1). Y greffer la presentation confondrait « la vue *Clients du
    Nord* » et « comment je regarde cet ecran ». Et `User.theme`/
    `User.density` sont des preferences GLOBALES, pas par ecran.

    La presentation par defaut, elle, n'est pas stockee : elle se DERIVE du
    processus (un document qui declare un tableau s'ouvre en kanban). Cette
    table ne porte que la SURCHARGE explicite de l'utilisateur — rien tant
    qu'il n'a pas bascule, ce qui evite d'ecrire une ligne par utilisateur
    et par ecran pour enregistrer le defaut."""

    PRESENTATION_LISTE = "liste"
    PRESENTATION_KANBAN = "kanban"
    PRESENTATION_CHOICES = [
        (PRESENTATION_LISTE, "Liste"),
        (PRESENTATION_KANBAN, "Kanban"),
    ]

    owner = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="+")
    table_key = models.CharField(max_length=100, db_index=True)
    presentation = models.CharField(max_length=8, choices=PRESENTATION_CHOICES)

    class Meta:
        db_table = "core_screen_preference"
        constraints = [
            models.UniqueConstraint(
                # `tenant` fait partie de la clef : un utilisateur peut
                # travailler dans plusieurs societes, et rien n'impose qu'il
                # regarde le meme ecran de la meme facon dans chacune. Sans
                # lui, sa preference dans l'une ecraserait celle de l'autre.
                fields=["tenant", "owner", "table_key"],
                name="uniq_screen_preference",
            )
        ]

    def __str__(self) -> str:
        return f"{self.table_key}:{self.presentation}"
