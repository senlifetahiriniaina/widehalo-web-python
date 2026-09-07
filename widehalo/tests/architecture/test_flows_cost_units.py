"""Garde-fou bloquant — le jeu d'unités de coût reste fermé, et partagé.

**Ce que cette garde protège, et pourquoi c'est un garde-fou et non une
relecture.** L'hypothèse H26 du cahier prévoit que l'unité de facturation
de la messagerie puisse basculer, et pose en repli que « deux unités
coexistent, avec une date de bascule ». La réponse retenue est de faire de
l'unité une donnée portée par chaque ligne de coût — de sorte que ni la
branche optimiste ni la branche de repli ne conditionnent la conception.

Cela ne tient qu'à deux conditions, et aucune des deux ne se relit :

1. **Les deux compteurs parlent la même langue.** `WhatsAppMessage` et
   `FlwExchange` portent chacun un `cost_ariary` ; s'ils tiraient leurs
   unités de deux énumérations distinctes, un total transverse mélangerait
   deux vocabulaires et personne ne s'en apercevrait avant le premier
   rapport de coûts.
2. **Le jeu reste fermé.** Une troisième unité ajoutée sans que la règle
   d'imputation correspondante soit écrite produirait des montants faux et
   silencieux — `impute_cost` retomberait sur sa dernière branche et
   facturerait chaque message, quelle que soit l'unité déclarée.
"""

from __future__ import annotations

from apps.core.cost_units import COST_UNIT_CHOICES, KNOWN_COST_UNITS
from apps.core.models.notification import WhatsAppMessage
from apps.flows.models import FlwExchange

#: Les deux unités que le cahier nomme, recopiées ICI depuis l'hypothèse
#: H26 et non importées du module vérifié. C'est le mécanisme, pas un
#: oubli : un test qui lirait l'énumération qu'il contrôle serait vert quel
#: que soit son contenu.
UNITES_DU_CAHIER = {"conversation", "message"}


def test_the_cost_unit_set_is_exactly_the_one_the_cahier_names() -> None:
    assert KNOWN_COST_UNITS == UNITES_DU_CAHIER, (
        "Le jeu d'unités de coût a changé.\n"
        f"En trop : {sorted(KNOWN_COST_UNITS - UNITES_DU_CAHIER)}\n"
        f"Manquantes : {sorted(UNITES_DU_CAHIER - KNOWN_COST_UNITS)}\n"
        "Une unité de plus demande d'écrire sa règle d'imputation dans "
        "`apps.whatsapp.services.pricing.impute_cost` : sans elle, la fonction "
        "retombe sur sa dernière branche et facture chaque message quelle que soit "
        "l'unité déclarée — des montants faux et silencieux."
    )


def test_both_cost_counters_share_one_vocabulary() -> None:
    """Deux énumérations distinctes rendraient un total transverse
    ininterprétable, et rien ne le signalerait avant le premier rapport de
    coûts par connecteur."""
    messagerie = {code for code, _label in WhatsAppMessage._meta.get_field("cost_unit").choices}
    flux = {code for code, _label in FlwExchange._meta.get_field("cost_unit").choices}
    reference = {code for code, _label in COST_UNIT_CHOICES}

    assert messagerie == reference == flux, (
        "Les deux compteurs de coût ne partagent plus le même vocabulaire :\n"
        f"  messagerie : {sorted(messagerie)}\n"
        f"  flux       : {sorted(flux)}\n"
        f"  référence  : {sorted(reference)}"
    )


def test_a_cost_bearing_row_can_always_say_under_which_unit_it_was_priced() -> None:
    """Le champ doit exister sur TOUT modèle porteur d'un `cost_ariary`.

    Vérifié par introspection plutôt que par une liste écrite à la main :
    le troisième compteur de coût — celui du paiement mobile, au bloc D —
    sera attrapé par cette garde le jour où il sera écrit, sans que
    personne ait à penser à l'ajouter ici."""
    from django.apps import apps as django_apps

    manquants = []
    for model in django_apps.get_models():
        champs = {f.name for f in model._meta.get_fields()}
        if "cost_ariary" in champs and "cost_unit" not in champs:
            manquants.append(f"{model._meta.app_label}.{model.__name__}")

    assert not manquants, (
        "Modèles portant un coût sans son unité : "
        f"{sorted(manquants)}.\n"
        "Un montant sans unité rend un total à cheval sur une bascule exact à "
        "l'ariary et pourtant incomparable à la période précédente, sans que rien "
        "ne le signale (hypothèse H26)."
    )
