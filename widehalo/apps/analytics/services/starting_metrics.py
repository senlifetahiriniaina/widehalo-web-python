"""Jeu d'indicateurs de depart du dictionnaire gouverne (L8).

**Le defaut que ce module ferme.** `AnMetricDefinition` etait la « SEULE
voie declaree d'acces aux donnees decisionnelles » — et **rien ne la
peuplait**. Aucune migration, aucune commande, aucun chemin de creation de
tenant : sur une instance neuve, le dictionnaire etait vide, donc l'ecran
du dictionnaire etait vide, donc aucun rapport BI ne pouvait nommer un
indicateur, et aucun resultat cle de `strategy` ne pouvait s'y adosser
(STR-1 refuse un `metric_code` inconnu). Une gouvernance sans catalogue ne
gouverne rien.

C'est le meme patron que ce depot a deja paye cinq fois : du code correct,
correctement documente, que rien n'invoque ni ne seme.

**D'ou vient ce jeu de depart.** Les quatre premieres entrees reprennent
exactement la table de correspondance qui vivait dans
`apps.bi.services.metric_computers.METRIC_FACTS` (supprimee par L8) : elles
etaient les seuls indicateurs que `bi` savait calculer, sans qu'aucune
n'existe jamais en base. Les quatre suivantes ouvrent les faits que
l'entrepot rafraichissait deja sans que rien ne puisse les lire.

**Chaque entree declare son fait ET ses axes**, valides a l'enregistrement
contre `services/fact_specs.py` : un indicateur de ce jeu est calculable
par construction, et le test qui les enregistre tous le prouve.

Idempotent : `register_metric` n'insere une nouvelle version que si les
valeurs changent, donc rejouer ce chargement sur un tenant deja servi ne
cree aucune ligne (meme discipline que les autres chargements de
referentiel, `load_chart_of_accounts` en tete).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.analytics.models import AnMetricDefinition
from apps.analytics.services.dictionary import register_metric

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant

# Roles decisionnaires usuels du depot (cf. `core.services.rbac_policy`).
# Une liste VIDE signifie « aucune restriction de role » (cf.
# `bi.services.query::_is_metric_authorized`), ce qui n'est jamais le
# defaut ici : un indicateur du jeu de depart nomme toujours ses roles.
_COMMERCE = ["admin", "direction", "commercial"]
_COMPTA = ["admin", "direction", "comptable"]
_PAIE = ["admin", "direction", "rh"]
_PRODUCTION = ["admin", "direction", "production"]
_LOGISTIQUE = ["admin", "direction", "magasinier"]

STARTING_METRICS: list[dict[str, Any]] = [
    {
        "code": "sales.ca_ht",
        "libelle": "Chiffre d'affaires HT",
        "module_source": "sales",
        "fait_source": "vente",
        "unite": "MGA",
        "axes_autorises": ["temps", "tiers", "article"],
        "roles_autorises": _COMMERCE,
        "formule": "Somme des montants hors taxe des lignes de commande de vente.",
    },
    {
        "code": "pos.ca_ttc",
        "libelle": "Chiffre d'affaires TTC au comptoir",
        "module_source": "pos",
        "fait_source": "ticket_pos",
        "unite": "MGA",
        "axes_autorises": ["temps", "tiers", "article", "point_vente"],
        "roles_autorises": _COMMERCE,
        "formule": "Somme des montants TTC des lignes de ticket de caisse.",
    },
    {
        "code": "accounting.encaissements",
        "libelle": "Encaissements",
        "module_source": "accounting",
        "fait_source": "encaissement",
        "unite": "MGA",
        "axes_autorises": ["temps", "tiers"],
        "roles_autorises": _COMPTA,
        "formule": "Somme des reglements entrants.",
    },
    {
        "code": "accounting.solde_compte",
        "libelle": "Solde par compte",
        "module_source": "accounting",
        "fait_source": "ecriture",
        "unite": "MGA",
        "axes_autorises": ["temps", "tiers", "compte"],
        "roles_autorises": _COMPTA,
        "formule": "Solde (debit - credit) des lignes d'ecriture publiees.",
    },
    {
        "code": "stocks.valeur_mouvementee",
        "libelle": "Valeur mouvementee en stock",
        "module_source": "stocks",
        "fait_source": "mouvement_stock",
        "unite": "MGA",
        "axes_autorises": [
            "temps",
            "article",
            "nature",
            "entrepot_origine",
            "entrepot_destination",
        ],
        "roles_autorises": _LOGISTIQUE,
        "formule": "Somme des valeurs des mouvements de stock valides.",
    },
    {
        "code": "purchase.qte_receptionnee",
        "libelle": "Quantite receptionnee",
        "module_source": "purchase",
        "fait_source": "reception",
        "unite": "unite",
        "axes_autorises": ["temps", "tiers", "article"],
        "roles_autorises": _LOGISTIQUE,
        "formule": "Somme des quantites receptionnees sur commande d'achat.",
    },
    {
        "code": "mrp.ecart_cout_production",
        "libelle": "Ecart de cout de production",
        "module_source": "mrp",
        "fait_source": "ordre_fabrication",
        "unite": "MGA",
        "axes_autorises": ["temps", "article", "atelier"],
        "roles_autorises": _PRODUCTION,
        "formule": "Cout reel moins cout planifie des ordres de fabrication clotures.",
    },
    {
        # `maille_minimale` volontairement posee alors qu'aucun axe
        # `employe` n'existe sur le fait : elle bloque AUSSI le detail
        # (`bi.services.query::drill_down` refuse tout acces au detail des
        # qu'elle est renseignee), et le detail d'un fait de paie est
        # nominatif par construction. Cloisonnement P5/RG-PAY-9, la meme
        # raison pour laquelle `AnFactPaie` exclut deja `net_to_pay`.
        "code": "payroll.masse_salariale_brute",
        "libelle": "Masse salariale brute",
        "module_source": "payroll",
        "fait_source": "paie",
        "unite": "MGA",
        "axes_autorises": ["temps", "periode"],
        "roles_autorises": _PAIE,
        "maille_minimale": "employe",
        "formule": (
            "Somme des salaires bruts des bulletins publies. Jamais ventilable "
            "par employe : cout employeur agrege uniquement."
        ),
    },
]

# Un indicateur descriptif (sans fait rattache) est un etat legitime du
# dictionnaire, mais aucun n'est livre dans ce jeu : un catalogue de depart
# ENTIEREMENT calculable est ce qui rend l'ecran utile des la premiere
# connexion. `test_starting_metrics.py` le verifie plutot qu'une assertion
# au chargement du module.


def load_metric_dictionary(tenant: Tenant) -> int:
    """Enregistre le jeu de depart pour `tenant`, PUBLIE.

    Retourne le nombre d'indicateurs presents apres chargement (pas le
    nombre de lignes creees) : l'appel est idempotent, et un compte de
    creations serait nul au second passage sans rien dire de l'etat reel.

    Publie et non brouillon : un indicateur en brouillon n'est visible ni
    de `list_metrics_for_user`, ni de `bi`, ni de `strategy` — le charger
    en brouillon reproduirait exactement le vide que ce module comble."""
    for entry in STARTING_METRICS:
        register_metric(
            tenant,
            statut=AnMetricDefinition.STATUT_PUBLIE,
            **entry,
        )
    return AnMetricDefinition.objects.filter(tenant=tenant, is_current=True).count()
