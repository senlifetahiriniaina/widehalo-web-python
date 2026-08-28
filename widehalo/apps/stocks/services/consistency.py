"""Cohérence production/stock (§5.8, ST6 du sous-sequencement `stocks` —
cf. plan) : RG-STK-6, controle automatique (commande de management, jamais
un job cron auto-enregistre, meme discipline que
`run_purchase_reordering`/`expire_stock_reservations`) comparant la
quantite DECLAREE produite par un ordre de fabrication a la quantite REELLEMENT
entree en stock pour cet ordre.

**Perimetre honnete retenu (3e jambe du RG-STK-6 non implementee)** : le
CDC (RG-STK-6) demande litteralement de comparer 3 nombres — quantite
declaree produite, quantite entree en stock, ET "la quantite livree au
client issue de CETTE production". Cette 3e jambe exigerait de tracer,
depuis UN `MrpOrder` precis, jusqu'A quelles livraisons clients precises la
quantite qu'il a produite a ete affectee — une vraie chaine de
tracabilite production -> vente qui N'EXISTE PAS dans ce depot au-dela
d'un simple UUID `SalesOrderLine.mrp_order_id` renseigne a la
QUALIFICATION de la ligne (RG-SAL-3), pas a chaque livraison individuelle :
un `MrpOrder` peut alimenter plusieurs lignes de vente, une ligne peut
etre livree en plusieurs fois partielles, et rien ne permet de dire quelle
PART d'une livraison provient precisement de CET ordre plutot que d'un
autre lot de stock du meme produit (le stock, une fois entre, n'est plus
distingue par ordre d'origine — c'est `StkQuant`, pas
`StkValuationLayer`/`StkMove`, qui porte la disponibilite consommee a la
livraison, et `StkQuant` ne garde aucune trace de "quel `MrpOrder` a
produit cette unite precise").

Plutot que de fabriquer une correlation approximative qui laisserait
croire a une precision qu'elle n'a pas, ce rapport se limite HONNETEMENT
aux 2 jambes reellement fiables : (a) quantite declaree (`mrp.services.
public.get_order_produced_qty`) vs (b) quantite reellement entree en
stock (`StkMove` `done` de type `production_in`, correles a l'ordre par
`source_document == order["reference"]`, cf. ci-dessous). C'est exactement
le signal exerce par l'acceptance test §5.8.7 n°4 du CDC ("un OF declarant
100 pieces avec 95 entrees en stock apparait dans le rapport de
coherence") — qui ne porte QUE sur declare vs entre en stock, jamais sur
une livraison client — donc ce perimetre restreint ne compromet en rien
la verification de cet acceptance test. `sales.services.public.
get_delivered_qty_for_order` (nouveau gap de lecture ajoute par ce meme
ST6) reste disponible pour un futur enrichissement de tracabilite complete
(ex. si une future chaine `StkMove.source_document` -> livraison precise
est construite), mais n'est PAS appele ici.

**Convention de correlation `StkMove.source_document`** : `StkMove` n'a
aucune FK vers `MrpOrder` (regle de couplage n°1, `stocks` ne fait jamais
de FK vers `apps.mrp`) — `source_document` (CharField libre, deja etabli
depuis ST2, cf. docstring `StkMove.source_document`) est la convention
retenue pour cette correlation : un mouvement `production_in` genere par
une INTEGRATION future `mrp` -> `stocks` (hors perimetre de ce lot, `mrp`
ne cree encore aucun `StkMove` lui-meme) devrait renseigner
`source_document` avec la REFERENCE de l'ordre de fabrication d'origine
(`MrpOrder.reference`, deja expose par `list_closed_orders` ci-dessous).
Cette correlation par correspondance de CHAINE (pas de FK reelle) depend
donc entierement de la discipline de l'appelant qui cree le mouvement — ce
rapport ne peut que la LIRE, jamais la garantir. Les tests de ce module
respectent cette meme convention pour exercer la logique de maniere
significative (cf. `tests/test_consistency.py`)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from django.db.models import Sum
from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.mrp.services.public import list_closed_orders
from apps.stocks.models import StkMove

# RG-STK-6 ne fixe aucune fenetre par defaut pour "les ordres clotures
# recemment" — 30 jours retenu ici comme defaut assume (coherent avec la
# cadence "controle automatique quotidien" du CDC : une fenetre glissante
# d'un mois couvre largement tout ordre qui aurait pu echapper a un
# controle quotidien manque), parametrable par appel.
DEFAULT_WINDOW_DAYS = 30


def production_consistency_report(
    tenant: Tenant, *, since: dt.date | None = None
) -> list[dict[str, Any]]:
    """RG-STK-6 : pour chaque `MrpOrder` `closed` du tenant depuis `since`
    (defaut : aujourd'hui - `DEFAULT_WINDOW_DAYS`, cf. docstring de module),
    compare la quantite declaree produite a la quantite reellement entree
    en stock via des mouvements `production_in` `done` dont
    `source_document` correspond a la reference de l'ordre.

    **Toutes les commandes de la fenetre apparaissent dans le rapport**
    (pas seulement les anomalies) — chaque ligne porte son propre flag
    `anomaly`, l'appelant (ecran/commande) filtre lui-meme s'il ne veut
    afficher que les anomalies. Choix retenu pour que le rapport reste
    consultable comme un etat complet de la fenetre (coherent avec
    `compute_abc_classification`, qui renvoie egalement toutes les lignes
    calculees, anomalie ou non), plutot qu'une liste tronquee qui masquerait
    silencieusement "aucun ordre cloture cette periode" derriere "aucune
    anomalie cette periode".

    `anomaly=True` des que `qty_declared != qty_entered_stock` (n'importe
    quel ecart, meme minime) — le CDC (RG-STK-6) ne fixe AUCUN seuil de
    tolerance pour cette regle precise, a la difference de RG-STK-4/RG-STK-9
    qui en fixent un explicitement ; ce silence est traite ici comme un
    choix delibere du CDC plutot qu'un oubli a combler par une tolerance
    inventee — tout ecart, aussi petit soit-il, est donc reportable."""
    since = since or (timezone.now().date() - dt.timedelta(days=DEFAULT_WINDOW_DAYS))
    orders = list_closed_orders(tenant, since=since)

    rows: list[dict[str, Any]] = []
    for order in orders:
        qty_declared = order["qty_produced"] or Decimal(0)
        qty_entered_stock = StkMove.objects.filter(
            tenant=tenant,
            move_type=StkMove.TYPE_PRODUCTION_IN,
            state=StkMove.STATE_DONE,
            source_document=order["reference"],
        ).aggregate(total=Sum("qty"))["total"] or Decimal(0)
        variance = qty_entered_stock - qty_declared
        rows.append(
            {
                "order_id": order["id"],
                "order_reference": order["reference"],
                "workshop_id": order["workshop_id"],
                "qty_declared": qty_declared,
                "qty_entered_stock": qty_entered_stock,
                "variance": variance,
                "anomaly": variance != 0,
            }
        )
    return rows
