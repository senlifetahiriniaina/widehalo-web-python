"""T0 (axe A1) — le declencheur declare la piece qu'il filtre.

Le cahier : « Portee — quels objets partent : filtres sur des champs
declares du modele, jamais une expression libre. Un filtre non declare est
refuse a l'enregistrement. »

Jusqu'ici `FlwTrigger.condition` portait une chaine evaluee par
`safe_eval` sur la charge de l'evenement. Rien ne la validait a
l'enregistrement — ni sa syntaxe, ni les champs qu'elle nommait — parce
qu'il n'y avait AUCUN schema contre quoi la valider : la charge de
`workflow.transitioned` ne porte que cinq clefs d'enveloppe (`model`,
`object_id`, `field`, `source`, `target`), pas les champs du modele.

Ce champ apporte le referent manquant. Il vaut `app.Modele` — exactement
ce que `workflow.transitioned` porte sous `model` — et c'est lui qui
permet de retrouver le schema declare par le module
(`apps.core.services.outbound_schemas`), donc de refuser a
l'enregistrement un filtre sur un champ non declare filtrable.

**Aucune conversion de donnees, et c'est deliberé.** Les conditions
existantes portant l'ancienne clef `expression` restent en base telles
quelles et cessent simplement de declencher (`declared_filters` rend
`None` sur toute clef inconnue, et `passes_condition` refuse). Convertir
automatiquement une expression en filtres declaratifs supposerait
d'interpreter du code pour deviner l'intention de son auteur ; se tromper
elargirait la portee d'un declencheur — donc ferait sortir des pieces que
personne n'a decide d'envoyer. Ne rien envoyer est le seul sens dans
lequel une erreur d'interpretation est rattrapable.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("flows", "0007_public_api_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="flwtrigger",
            name="document_type",
            field=models.CharField(blank=True, max_length=64),
        ),
    ]
