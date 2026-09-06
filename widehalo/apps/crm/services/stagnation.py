"""CRM-4 (L4) — « opportunite sans activite depuis plus de N jours ».

Une seule definition, deux consommateurs : le detecteur d'anomalies du
copilote (`services.ai_anomaly_registration`, qui la portait jusqu'ici en
constante de module) et la tuile « relances en retard » du launchpad, que
le critere exige et qui n'existait pas.

**Pourquoi une definition partagee plutot qu'un second calcul.** Le
critere nomme UNE population : celle qui apparait dans la tuile. Si la
tuile comptait autrement que le detecteur, l'exploitant verrait un chiffre
au launchpad et une autre liste dans le copilote — exactement le defaut
que BI-1 interdit ailleurs dans ce produit (« deux ecrans affichant le
meme indicateur sur le meme perimetre renvoient la meme valeur »).

**Deviation assumee, heritee et redite ici** : le critere dit « sans
activite PLANIFIEE », la mesure retenue est « sans activite
ENREGISTREE ». `CrmLead` ne porte aucun horodatage d'entree d'etape, et
`CrmActivity.due_at` est facultatif — compter les seules activites
planifiees ferait disparaitre de la tuile une opportunite suivie par
appels non planifies, c'est-a-dire la majorite. La reference est donc la
derniere activite enregistree, ou a defaut la creation de l'opportunite.
"""

from __future__ import annotations

import datetime as dt

from django.db.models import Max
from django.utils import timezone

from apps.crm.models import CrmLead

# Repli quand l'opportunite n'a pas de pipeline resolvable — ne devrait pas
# arriver (`CrmLead.pipeline` est une FK non nulle), mais un `getattr` sur
# un pipeline absent renverrait `None` et ferait echouer la soustraction.
# Meme valeur que la constante qui vivait dans
# `services/ai_anomaly_registration`, pour que le comportement par defaut
# soit strictement inchange.
DEFAULT_STAGNANT_WINDOW_DAYS = 21


def stagnant_leads(tenant_id: str) -> list[tuple[CrmLead, int, int]]:
    """`[(lead, jours_sans_activite, fenetre_du_pipeline), ...]`.

    Renvoie la fenetre a cote du nombre de jours : l'appelant en a besoin
    pour graduer une severite (le detecteur d'anomalies double le seuil
    pour passer en « haute ») sans avoir a relire le pipeline lui-meme."""
    now = timezone.now()
    leads = (
        CrmLead.objects.filter(tenant_id=tenant_id, is_active=True)
        .filter(won_at__isnull=True, lost_at__isnull=True)
        .select_related("stage", "pipeline")
        .annotate(last_activity_at=Max("activities__created_at"))
    )

    rows: list[tuple[CrmLead, int, int]] = []
    for lead in leads:
        window = getattr(lead.pipeline, "stagnant_after_days", None) or (
            DEFAULT_STAGNANT_WINDOW_DAYS
        )
        reference_date = lead.last_activity_at or lead.created_at
        if reference_date > now - dt.timedelta(days=window):
            continue
        rows.append((lead, (now - reference_date).days, window))
    return rows


def count_stagnant_leads(tenant_id: str) -> int:
    """Compteur pour la tuile « relances en retard » du launchpad."""
    return len(stagnant_leads(tenant_id))
