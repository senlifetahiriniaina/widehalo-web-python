"""Garde C-1 : une vue d'ecran sans droit est une porte ouverte.

**Ce qu'elle empeche.** Avant C-1, les 82 vues de `crm`, `sales`,
`accounting` et `logistics` portaient `@login_required` et rien d'autre :
tout utilisateur authentifie, quel que soit son role, lisait et ecrivait
le plan comptable, le referentiel fiscal, les tournees et les devis.
L'API des memes modules appliquait pourtant deja le RBAC N2. Cette garde
empeche la 83e vue d'arriver sans droit.

**L'instrument, et ce qui l'a convaincu.** Il ne cherche PAS `has_perm`
dans le texte de la vue : il lit l'attribut `screen_permission_codename`
que le decorateur pose sur la fonction. Un attribut ne se confond avec
rien, la ou une recherche textuelle confondrait un commentaire, une
docstring ou une chaine.

**Deux pieges de cette famille d'instruments, payes tous les deux dans
cette vague** :

1. `inspect.getsourcefile` sur une vue DECOREE rend
   `django/contrib/auth/decorators.py`, pas le fichier du depot. Il faut
   DEBALLER `__wrapped__` AVANT de filtrer par fichier — sans quoi
   l'instrument ne voit aucune vue et declare tout sain. C'est arrive ici
   meme, pendant l'ecriture de C-1.
2. Deux modules peuvent porter le meme nom de vue (`risk_create` et
   `template_create` existent chacun deux fois dans ce depot). On
   n'indexe donc jamais par nom seul.

**Le jeu ferme se verifie contre une liste independante** (lecon F60) :
les codenames autorises sont recalcules depuis les `ContentType` de
Django, jamais depuis le code des vues qu'ils sont censes surveiller.
"""

from __future__ import annotations

import inspect

from django.apps import apps as django_apps
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver

#: Les modules que C-1 a dotes d'une garde. Y ajouter un module signifie
#: qu'on s'engage a garder TOUTES ses vues.
MODULES_GARDES = ("crm", "sales", "accounting", "logistics")


def _deballer(vue):
    """Rend la fonction REELLE derriere les decorateurs.

    `@login_required` enveloppe la vue ; sans ce deballage, le fichier
    source rendu est celui de Django et le filtre par module ne retient
    plus rien."""
    while hasattr(vue, "__wrapped__"):
        vue = vue.__wrapped__
    return vue


def _vues_des_modules_gardes() -> list[tuple[str, str, object]]:
    """(chemin, nom, vue) de chaque route servie par un module garde."""
    trouvees: list[tuple[str, str, object]] = []

    def marcher(noeud, chemin: str) -> None:
        for entree in noeud.url_patterns:
            if isinstance(entree, URLResolver):
                marcher(entree, chemin + str(entree.pattern))
            elif isinstance(entree, URLPattern) and entree.name:
                reelle = _deballer(entree.callback)
                try:
                    fichier = inspect.getsourcefile(reelle) or ""
                except TypeError:
                    continue
                if any(f"/apps/{m}/views" in fichier for m in MODULES_GARDES):
                    trouvees.append(
                        ("/" + chemin + str(entree.pattern), entree.name, entree.callback)
                    )

    marcher(get_resolver(), "")
    return trouvees


def _codenames_reels() -> set[str]:
    """Recalcule depuis les modeles — jamais lu dans le code des vues."""
    reels: set[str] = set()
    for module in MODULES_GARDES:
        for modele in django_apps.get_app_config(module).get_models():
            nom = modele.__name__.lower()
            for verbe in ("view", "add", "change", "delete"):
                reels.add(f"{module}.{verbe}_{nom}")
            for codename, _libelle in modele._meta.permissions:
                reels.add(f"{module}.{codename}")
    return reels


def test_the_measurement_still_finds_views() -> None:
    """Un instrument qui ne trouve plus rien declare tout sain.

    C'est la panne silencieuse de cette famille de gardes, et elle s'est
    produite pendant l'ecriture meme de C-1 : en filtrant par fichier
    AVANT de deballer les decorateurs, l'instrument voyait zero vue."""
    vues = _vues_des_modules_gardes()
    assert len(vues) >= 70, (
        f"L'instrument ne voit plus que {len(vues)} vues (82 a la mesure C-1) : "
        f"c'est l'instrument qui est casse, pas le depot qui a maigri."
    )
    assert _codenames_reels(), "Aucun codename recalcule : la liste de reference est vide."


def test_every_screen_view_declares_a_permission() -> None:
    """Chaque vue de ces quatre modules porte un droit de LECTURE."""
    sans_droit = sorted(
        f"{nom} ({chemin})"
        for chemin, nom, vue in _vues_des_modules_gardes()
        if getattr(vue, "screen_permission_codename", None) is None
    )
    assert not sans_droit, (
        f"Ces vues ne declarent aucun droit d'acces : {sans_droit}. Ajoutez "
        f'`@screen_permission("<app>.view_<modele>")` sous `@login_required` — '
        f"avec le MEME codename que porte l'endpoint d'API homologue."
    )


def test_declared_permissions_exist_and_belong_to_their_module() -> None:
    """Un codename errone refuserait TOUT LE MONDE, en silence.

    `has_perm` rend `False` pour une permission qui n'existe pas : une
    faute de frappe ne leve rien, elle ferme l'ecran a tous les roles, y
    compris `admin`. Et un codename emprunte a un AUTRE module (copier-
    coller entre vues) donnerait un refus juste par accident."""
    reels = _codenames_reels()
    fautifs: list[str] = []
    for chemin, nom, vue in _vues_des_modules_gardes():
        codename = getattr(vue, "screen_permission_codename", None)
        if codename is None:
            continue
        module_de_la_vue = next(
            m
            for m in MODULES_GARDES
            if f"/apps/{m}/views" in (inspect.getsourcefile(_deballer(vue)) or "")
        )
        if codename not in reels:
            fautifs.append(f"{nom} ({chemin}) declare `{codename}`, qui n'existe pas")
        elif not codename.startswith(f"{module_de_la_vue}."):
            fautifs.append(
                f"{nom} ({chemin}) vit dans `{module_de_la_vue}` mais declare `{codename}`"
            )
    assert not fautifs, "\n".join(fautifs)


#: Les prefixes de codename qui designent une ECRITURE. Ecrits ici, jamais
#: lus d'un registre du code teste — un jeu ferme ne se verifie pas contre
#: sa propre source (lecon F60).
_ACTIONS_D_ECRITURE = frozenset({"add", "change", "delete", "validate", "cancel"})


def test_every_view_that_writes_also_guards_the_write() -> None:
    """Lire n'est pas ecrire : une vue qui traite un POST doit verifier un
    droit d'ECRITURE en plus de son droit de lecture.

    Sans cela, un role en lecture seule — `controleur_gestion` sur `sales`
    et `accounting`, par la matrice — passerait le decorateur et ecrirait."""
    sans_garde: list[str] = []
    for chemin, nom, vue in _vues_des_modules_gardes():
        source = inspect.getsource(_deballer(vue))
        if "request.method" not in source:
            continue
        if "screen_forbidden" in source:
            continue
        # **Un ecran dont le DECORATEUR porte deja un droit d'ecriture n'a
        # rien a re-verifier dans son corps** — et il protege meme plus : le
        # decorateur refuse aussi le GET, donc un role en lecture seule ne
        # voit jamais le formulaire, au lieu de le remplir pour se le faire
        # refuser a l'envoi. C'est la regle posee en C-1d pour les huit
        # ecrans de creation.
        #
        # Cette branche a ete ajoutee parce que la garde a refuse deux vues
        # justes (`crm.imports`, `accounting.payout_announce`). La croire
        # sur parole aurait fait ajouter un `screen_forbidden` redondant ;
        # la lire a montre que c'est la garde qui ne connaissait qu'une des
        # deux formes correctes.
        codename = getattr(vue, "screen_permission_codename", "") or ""
        action = codename.split(".")[-1].split("_")[0] if "." in codename else ""
        if action in _ACTIONS_D_ECRITURE:
            continue
        sans_garde.append(f"{nom} ({chemin})")
    assert not sans_garde, (
        f"Ces vues traitent un POST sans verifier de droit d'ecriture : "
        f"{sorted(sans_garde)}. Ajoutez `screen_forbidden(request, "
        f'"<app>.add_<modele>")` (ou `change_`) avant le traitement.'
    )
