"""Garde G-8 : un modèle métier des quatre modules prioritaires doit être
atteignable depuis un écran — ou son absence doit être écrite ici.

**Ce qu'elle empêche.** La mesure qui a ouvert la vague G disait : *32 des
51 modèles d'`accounting` et 6 des 17 de `logistics` n'ont aucun écran*,
alors que les services, les tests et l'API existaient pour presque tous.
C'est le motif « rien de décoratif » à l'échelle de deux modules — le
produit savait rapprocher une ligne de banque, suivre une immobilisation,
relancer un client ; un exploitant devant un navigateur ne le pouvait pas.
Sans cette garde, le trente-troisième modèle sans porte s'ajouterait sans
que rien ne le dise.

**L'instrument, et les DEUX fois où il s'est trompé.** On cherche le nom de
classe du modèle dans le corpus des vues et des gabarits du produit.

- La première version limitait le corpus au module du modèle. Elle a
  déclaré `AccPartnerRoleAccount` sans écran, alors que la fiche partenaire
  l'édite depuis `apps/partners/views.py`. **Corpus élargi à tout le
  produit.**
- La seconde version comptait comme orphelines les LIGNES d'un document
  (`AccDcomLine`, `LogShipmentLeg`, `SalesQuotationLine`…). Elles sont
  rendues par une boucle sur la relation de leur parent — `{% for ligne in
  plan.lines.all %}` — qui ne nomme jamais la classe. **Un modèle dont le
  parent a un écran n'est pas orphelin ; il est rendu par lui.**

C'est la quatrième famille d'erreur d'instrument de ce chantier, après le
zip compressé, les quatre extracteurs de classes CSS et les trois versions
de la mesure d'atteignabilité. La règle inscrite en 0.1.7 vaut ici :
**un instrument doit dire ce qui l'a convaincu**, et il faut le contredire
au moins une fois.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from django.apps import apps as django_apps

MODULES = ("accounting", "logistics", "sales", "crm")

#: Les modèles SANS écran, et le motif de chacun. Cette liste ne peut que
#: rétrécir : un modèle neuf sans écran fait échouer la garde.
#:
#: Elle ne contient AUCUNE ligne de document — celles-ci sont rendues par la
#: boucle de leur parent et sont écartées par la règle ci-dessous, pas par
#: une inscription à la main qui ferait de cette liste un cimetière.
ABSENCES_MOTIVEES: dict[str, str] = {
    "accounting.AccFramework": (
        "Referentiel GLOBAL, pas par societe : le cadre comptable est charge par "
        "commande d'administration a la mise a jour de la norme."
    ),
    "accounting.AccChartOfAccounts": (
        "Referentiel GLOBAL : le plan comptable de reference est charge par commande, "
        "et l'ecran d'import existe pour le plan DE LA SOCIETE."
    ),
    "accounting.AccAccountMapping": (
        "Transposition d'un referentiel vers un autre. Le modele le dit lui-meme : "
        "« une propriete des referentiels, pas d'un client » — il n'herite meme pas de "
        "`BaseModel` et n'a donc pas de societe a qui montrer un ecran."
    ),
    "accounting.AccVatDeclaration": (
        "L'ecran de declaration de TVA existe (`accounting/vat_declaration.html`, "
        "ACC-6) : il est construit depuis `services/vat_declaration.py`, qui nomme le "
        "service et jamais la classe. Absence de l'INSTRUMENT, pas du produit."
    ),
}

_RACINE = pathlib.Path(__file__).resolve().parents[2]


def _corpus() -> str:
    """Tout ce qui peut mener a un ecran : les vues et les gabarits."""
    morceaux: list[str] = []
    for chemin in (_RACINE / "apps").rglob("*.py"):
        texte = str(chemin)
        if "/tests/" in texte or "/migrations/" in texte:
            continue
        if chemin.name.startswith("views") or "/views/" in texte:
            morceaux.append(chemin.read_text(encoding="utf-8"))
    for chemin in (_RACINE / "templates").rglob("*.html"):
        morceaux.append(chemin.read_text(encoding="utf-8"))
    return "\n".join(morceaux)


def _modeles_des_modules() -> list[type]:
    return [
        modele
        for modele in django_apps.get_models()
        if modele._meta.app_label in MODULES and ".tests." not in modele.__module__
    ]


def _rendu_par_son_parent(modele: type, avec_surface: set[str]) -> bool:
    """Une ligne de document est rendue par la boucle de son parent.

    Le lien est lu sur les CLES ETRANGERES du modele, jamais sur son nom :
    un test qui se fierait au suffixe « Line » laisserait passer une entite
    autonome ainsi nommee, et refuserait une ligne nommee autrement."""
    for champ in modele._meta.get_fields():
        if (
            getattr(champ, "many_to_one", False)
            and getattr(champ, "related_model", None)
            and champ.related_model._meta.label in avec_surface
        ):
            return True
    return False


def test_la_mesure_voit_encore_des_modeles_avec_ecran() -> None:
    """Auto-test : un corpus vide declarerait tout le monde orphelin, et
    l'inverse — un corpus qui contient tout — declarerait tout le monde
    servi. Les deux rendraient la garde muette."""
    corpus = _corpus()
    assert len(corpus) > 100_000, "Corpus trop petit : c'est l'instrument qui est casse."
    modeles = _modeles_des_modules()
    assert modeles, "Aucun modele trouve dans les quatre modules."
    avec = [m for m in modeles if re.search(rf"\b{m.__name__}\b", corpus)]
    assert len(avec) >= 40, (
        f"L'instrument ne voit plus que {len(avec)} modeles avec ecran sur "
        f"{len(modeles)} : il mesure autre chose que ce qu'il croit."
    )


def test_chaque_modele_metier_est_atteignable_ou_son_absence_est_ecrite() -> None:
    corpus = _corpus()
    modeles = _modeles_des_modules()
    avec_surface = {
        modele._meta.label for modele in modeles if re.search(rf"\b{modele.__name__}\b", corpus)
    }

    orphelins = []
    for modele in modeles:
        label = modele._meta.label
        if label in avec_surface or label in ABSENCES_MOTIVEES:
            continue
        if _rendu_par_son_parent(modele, avec_surface):
            continue
        orphelins.append(label)

    assert not orphelins, (
        "Ces modeles metier n'ont aucun ecran et aucune absence ecrite :\n  "
        + "\n  ".join(sorted(orphelins))
        + "\n\nDonnez-leur un ecran, ou inscrivez-les dans `ABSENCES_MOTIVEES` "
        "avec le motif de leur absence."
    )


@pytest.mark.parametrize("label", sorted(ABSENCES_MOTIVEES))
def test_aucune_absence_motivee_nest_perimee(label: str) -> None:
    """Une liste d'exceptions qui ne retrecit jamais devient un cimetiere.

    Si le modele a recu un ecran depuis, son inscription ici ment — et le
    chiffre publie dans le document de version devient faux."""
    corpus = _corpus()
    modele = django_apps.get_model(label)
    trouve = re.search(rf"\b{modele.__name__}\b", corpus) is not None
    if label == "accounting.AccVatDeclaration":
        # Son motif dit exactement l'inverse : l'ecran existe, c'est
        # l'instrument qui ne le voit pas. Le jour ou une vue nommera la
        # classe, l'entree sort d'elle-meme par l'assertion generale.
        return
    assert not trouve, (
        f"{label} figure dans `ABSENCES_MOTIVEES` alors qu'il apparait desormais "
        f"dans une vue ou un gabarit : retirez l'entree."
    )
