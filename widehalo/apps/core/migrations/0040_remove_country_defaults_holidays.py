"""Le troisieme calendrier ferie disparait — il n'avait jamais servi.

`CountryDefaultsProfile.holidays` (JSONField) n'avait, dans tout le depot,
**ni lecteur ni ecrivain ni test**. Il ne pouvait pas devenir la reference :
porte par le profil PAYS, il ne sait pas representer une journee chomee
decidee par une entreprise, ni un scrutin, ni un deuil national — ce que
`core.Holiday` fait, par societe.

Le garder etait un piege : le prochain developpeur qui chercherait « ou sont
les jours feries » aurait trouve deux reponses, dont une fausse. Aucun code
n'est a modifier avec cette migration — c'est la definition meme d'un champ
mort.

Le second calendrier mort, `apps/presence/services/calendar.py`, est
supprime dans le meme lot. Il portait en plus une valeur FAUSSE : un ferie
travaille y valait 150 %, la ou la paie applique 2,00 — soit 200 %.
"""

from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("core", "0039_approvals_under_row_level_security")]

    operations = [
        migrations.RemoveField(model_name="countrydefaultsprofile", name="holidays"),
    ]
