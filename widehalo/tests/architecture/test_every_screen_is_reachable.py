"""Garde T10 : un ecran que personne ne peut atteindre n'existe pas.

**Ce qu'elle empeche.** Une route nommee, une vue ecrite, un gabarit rendu,
des tests qui passent — et aucun lien nulle part. L'ecran est parfaitement
fonctionnel et parfaitement invisible. C'est la variante d'ECRAN du motif
« rien de decoratif » qui traverse toute cette vague, et elle s'est deja
produite deux fois : `flows` n'appartenait a aucun groupe de menu avant T8
(le journal aurait existe sans porte), et la mesure de T10 a trouve le
module `ai` dans le meme etat — sept ecrans, aucune entree, pas meme une
route racine.

**L'instrument, et les deux fois ou il s'est trompe.** On cherche, pour
chaque ecran, un lien LA OU UN LIEN PEUT EXISTER : un `{% url %}` ou un
`href`/`hx-get` de gabarit, un `reverse`/`redirect` de vue, un chemin dans
le JS livre.

- Une premiere version ne cherchait que les NOMS de routes. Elle declarait
  orphelin `/mfa/`, que le middleware atteint par `redirect("/mfa/")` en
  dur, et l'ecran de recherche, atteint par un `hx-get` litteral. Elle
  comptait 20 orphelins, dont 4 faux. **D'ou la recherche par CHEMIN.**
- Une seconde acceptait n'importe quelle occurrence du chemin — y compris
  sa DECLARATION dans `urls.py`, et les routes d'API homonymes
  (`@router.get("/ai/anomalies")`, qui rend du JSON et n'est pas un ecran).
  Elle tombait a 5, dont plusieurs faux dans l'autre sens. **D'ou
  `FICHIERS_QUI_NE_MENENT_NULLE_PART`.**

Le chiffre juste est 13, et quatre ont ete verifies a la main avant d'etre
inscrits ci-dessous.

**Ce que cette garde NE prouve PAS, et il faut l'ecrire.** Elle verifie
qu'un lien EXISTE, pas qu'un chemin mene depuis l'accueil : un ecran cite
par un ecran lui-meme inatteignable passerait. La fermeture transitive
demanderait de savoir quelles entrees de menu le RBAC rend visibles a quel
role, ce qui n'est pas une propriete statique. Le complement est le test de
bout en bout, qui parcourt reellement.

**La dette est declaree et DECROISSANTE.** `DETTE_CONNUE` gele la mesure du
jour ; un ecran neuf sans lien echoue immediatement. Le second test refuse
qu'une entree y reste apres avoir ete cablee — sans quoi la liste
deviendrait un cimetiere et la garde s'endormirait.
"""

from __future__ import annotations

import inspect
import pathlib
import re

from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver

#: Espaces de noms qui ne sont pas des ecrans du produit : l'administration
#: Django et la barre de deboguage ont leur propre navigation, que nous ne
#: cablons pas.
NAMESPACES_TIERS = ("admin:", "djdt:")

#: `urls.py` DECLARE une route, il n'y mene pas ; les modules d'API servent
#: du JSON, et une route d'API homonyme d'un ecran n'est pas un lien vers
#: cet ecran. Les compter serait exactement l'erreur de la version 2 de
#: l'instrument.
FICHIERS_QUI_NE_MENENT_NULLE_PART = (
    "urls.py",
    "api.py",
    "api_search.py",
    "api_auth.py",
    "api_webhooks.py",
    "api_keys.py",
)

#: Mesure T10, gelee. **Cette liste ne peut que retrecir.**
#:
#: **Les sept `ai:*` en sont sortis** : ils formaient un module entier hors
#: navigation — `ai` dans aucun groupe de `_MENU_GROUPS`, pas de route
#: racine, donc `/ai/` en 404 — et T10 leur a donne une porte
#: (`ai:index`) et une entree de barre laterale.
#:
#: **Les cinq sous-ecrans en sont sortis aussi** : `payroll:regularization`,
#: `presence:reports_index`, `projects:config_custom_fields`,
#: `projects:user_capacity_heatmap` et `strategy:capacity_outlook` avaient
#: chacun une entree de module dans la barre laterale, mais l'accueil de
#: leur module ne les citait pas. Chacun a recu son lien.
#:
#: **Il ne reste qu'une entree, et elle est deliberee.** L'ecran de preuve
#: du socle graphique est un outil de developpement : sa vue ecrit
#: elle-meme « isole du reste de l'application (pas dans la sidebar) », et
#: elle refuse 403 a qui n'est pas admin/direction/superutilisateur. Le
#: cabler contredirait la decision prise au sprint 0 de la refonte UX. Il
#: reste donc ici, avec son motif, plutot que d'etre efface de la mesure.
DETTE_CONNUE = {
    "design_system_preview",
}

_RACINE = pathlib.Path(__file__).resolve().parents[2]

#: Un gabarit prefixe `_` est un fragment htmx, pas un ecran — meme
#: convention que `_counted_screens` du test de budget.
_GABARIT = re.compile(r"['\"]([\w./-]+\.html)['\"]")
#: La partie VARIABLE d'un motif d'URL : on ne garde que le prefixe fixe.
_PARAMETRE = re.compile(r"<[^>]+>|\(\?P<.*")


def _routes(resolveur, prefixe: str = "", chemin: str = ""):
    """Chaque route nommee, avec sa vue et son chemin complet."""
    for motif in resolveur.url_patterns:
        morceau = str(motif.pattern)
        if isinstance(motif, URLResolver):
            espace = motif.namespace
            yield from _routes(
                motif, f"{prefixe}{espace}:" if espace else prefixe, chemin + morceau
            )
        elif isinstance(motif, URLPattern) and motif.name:
            yield f"{prefixe}{motif.name}", motif.callback, chemin + morceau


def _corpus() -> list[tuple[str, str]]:
    """Les fichiers ou un lien vers un ecran peut exister."""
    fichiers: list[tuple[str, str]] = []
    for dossier, glob in (
        ("templates", "*.html"),
        ("apps", "*.py"),
        ("config", "*.py"),
        ("static/js", "*.js"),
    ):
        for f in (_RACINE / dossier).rglob(glob):
            if "/tests/" in str(f) or "/migrations/" in str(f):
                continue
            if f.name in FICHIERS_QUI_NE_MENENT_NULLE_PART:
                continue
            fichiers.append(
                (str(f.relative_to(_RACINE)), f.read_text(encoding="utf-8", errors="replace"))
            )
    return fichiers


def _ecrans() -> dict[str, str]:
    """Les routes du produit qui rendent un ecran, et leur chemin fixe."""
    trouves: dict[str, str] = {}
    for nom, vue, motif in _routes(get_resolver()):
        if nom.startswith(NAMESPACES_TIERS):
            continue
        try:
            source = inspect.getsource(vue)
        except (OSError, TypeError):
            continue
        rendus = {g for g in _GABARIT.findall(source) if not pathlib.Path(g).name.startswith("_")}
        if rendus:
            trouves[nom] = "/" + _PARAMETRE.split(motif)[0]
    return trouves


def _orphelins() -> set[str]:
    corpus = _corpus()
    sans_lien: set[str] = set()
    for nom, chemin in _ecrans().items():
        par_nom = re.compile(rf"""["']{re.escape(nom)}["']""")
        cherche_chemin = len(chemin) > 3
        if not any(
            par_nom.search(texte) or (cherche_chemin and chemin in texte) for _, texte in corpus
        ):
            sans_lien.add(nom)
    return sans_lien


def test_the_measurement_still_finds_screens() -> None:
    """Un instrument qui ne trouve plus rien a mesurer declare tout sain.

    C'est la panne silencieuse de cette famille de gardes : si
    `inspect.getsource` echouait partout, ou si la convention de nommage des
    gabarits changeait, `_ecrans()` rendrait un dictionnaire vide et les
    deux tests suivants passeraient sur zero ecran. Le seuil est tres en
    dessous de la mesure (256 ecrans du produit) : il attrape l'instrument
    casse, jamais une evolution normale du depot."""
    ecrans = _ecrans()
    assert len(ecrans) > 150, (
        f"L'instrument ne voit plus que {len(ecrans)} ecrans (256 a la mesure T10) : "
        f"c'est l'instrument qui est casse, pas le depot qui a maigri."
    )
    assert _corpus(), "Aucun fichier lu : le corpus de recherche est vide."


def test_no_new_screen_is_unreachable() -> None:
    """Un ecran neuf que rien ne cite est un ecran que personne n'ouvrira."""
    nouveaux = _orphelins() - DETTE_CONNUE
    assert not nouveaux, (
        f"Ces ecrans ne sont cites par aucun gabarit, aucune vue et aucun script : "
        f"{sorted(nouveaux)}. Un ecran sans lien existe sans que personne puisse "
        f"l'atteindre — ajoutez une entree de menu, ou un lien depuis l'accueil de "
        f"son module. Si l'ecran est volontairement hors navigation, inscrivez-le "
        f"dans DETTE_CONNUE avec son motif ecrit."
    )


def test_the_debt_list_shrinks_and_never_lies() -> None:
    """Une entree cablee doit sortir de la liste, sinon la garde s'endort.

    Sans ce test, `DETTE_CONNUE` deviendrait un cimetiere : on y ajouterait
    sans jamais en retirer, et une regression sur un ecran deja repare ne
    serait plus vue."""
    ecrans = set(_ecrans())
    perimes = DETTE_CONNUE & ecrans - _orphelins()
    assert not perimes, (
        f"Ces ecrans sont desormais atteignables et doivent sortir de DETTE_CONNUE : "
        f"{sorted(perimes)}."
    )
    disparus = DETTE_CONNUE - ecrans
    assert not disparus, (
        f"Ces entrees de DETTE_CONNUE ne designent plus aucun ecran : {sorted(disparus)}. "
        f"Route renommee ou supprimee — retirez-les."
    )
