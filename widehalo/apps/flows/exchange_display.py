"""T8 (bloc H, §10.2) — comment un etat d'echange se montre a un humain.

**L'exigence du cahier, mot pour mot** : « Quatre couleurs au maximum, un
libelle toujours present — **la couleur seule ne porte jamais
l'information**. »

**Pourquoi une table explicite et non le filtre generique du depot.**
`core_extras.state_badge_class` existe, il est reutilise sur tous les ecrans
metier, et il aurait ete la reponse economique. Mesure faite avant de
l'ecarter, sur les neuf etats de `FlwExchange` :

    prepare          -> b-neutral   (bon)
    en_file          -> b-neutral   (attendu : b-pending)
    emis             -> b-neutral   (attendu : b-pending)
    accepte          -> b-neutral   (attendu : b-success)
    rejete           -> b-neutral   (attendu : b-fail)
    attente_verdict  -> b-pending   (bon)
    a_reessayer      -> b-neutral   (attendu : b-pending)
    en_echec         -> b-fail      (bon)
    suspendu         -> b-neutral   (bon)

Six sur neuf. Le filtre reconnait des sous-chaines francaises et anglaises
de la Phase 1 (`paye`, `valide`, `refuse`, `echec`...) ; le vocabulaire du
hub, pose au sprint S1, n'en emploie aucune. Une soumission ACCEPTEE
s'afficherait en gris, et une soumission REJETEE aussi — c'est-a-dire le
seul etat qui appelle un geste du comptable, presente comme s'il n'appelait
rien.

**Le regroupement, et son motif.** Neuf etats vers quatre couleurs : ce sont
les quatre QUESTIONS qu'un exploitant se pose, pas quatre nuances.

- `b-success` : le tiers a tranche EN NOTRE FAVEUR — rien a faire.
- `b-fail`    : quelque chose demande un geste. `rejete` et `en_echec` sont
                regroupes ici parce que la reponse est la meme — regarder —,
                meme si la cause differe (refus motive contre panne).
- `b-pending` : c'est parti, personne n'a tranche. La difference entre « en
                file », « emis » et « a reessayer » interesse l'exploitant du
                produit, jamais le comptable : le LIBELLE la porte, la
                couleur n'a pas a la dedoubler.
- `b-neutral` : rien n'est engage (`prepare`) ou tout est arrete volontairement
                (`suspendu`). Ni attente ni probleme.
"""

from __future__ import annotations

from apps.flows.models import FlwExchange

BADGE_SUCCESS = "b-success"
BADGE_FAIL = "b-fail"
BADGE_PENDING = "b-pending"
BADGE_NEUTRAL = "b-neutral"

#: Les quatre seules classes que ce module peut rendre. « Quatre couleurs au
#: maximum » est une exigence du cahier, pas une preference : la garde
#: ci-dessous la tient.
BADGE_CLASSES = frozenset({BADGE_SUCCESS, BADGE_FAIL, BADGE_PENDING, BADGE_NEUTRAL})

#: Etats pour lesquels l'entreprise a fait sa part et attend quelqu'un
#: d'autre. C'est le seul groupe ou le §10.1 exige d'afficher « ce qui va se
#: passer ensuite et quand ».
WAITING_STATES = frozenset(
    {
        FlwExchange.STATE_QUEUED,
        FlwExchange.STATE_SENT,
        FlwExchange.STATE_AWAITING_VERDICT,
        FlwExchange.STATE_TO_RETRY,
    }
)

_BADGE_BY_STATE: dict[str, str] = {
    FlwExchange.STATE_PREPARED: BADGE_NEUTRAL,
    FlwExchange.STATE_QUEUED: BADGE_PENDING,
    FlwExchange.STATE_SENT: BADGE_PENDING,
    FlwExchange.STATE_ACCEPTED: BADGE_SUCCESS,
    FlwExchange.STATE_REJECTED: BADGE_FAIL,
    FlwExchange.STATE_AWAITING_VERDICT: BADGE_PENDING,
    FlwExchange.STATE_TO_RETRY: BADGE_PENDING,
    FlwExchange.STATE_FAILED: BADGE_FAIL,
    FlwExchange.STATE_SUSPENDED: BADGE_NEUTRAL,
}


def assert_badge_vocabulary_is_complete() -> None:
    """Appelee depuis `apps.py::ready()`, meme patron que les autres jeux
    fermes du depot.

    Un etat ajoute a `FlwExchange.STATE_CHOICES` sans entree ici tomberait
    silencieusement en `b-neutral` — c'est-a-dire qu'un dixieme etat, cree
    precisement parce qu'il dit quelque chose de neuf, s'afficherait comme
    « rien a signaler »."""
    etats = {code for code, _libelle in FlwExchange.STATE_CHOICES}
    manquants = etats - set(_BADGE_BY_STATE)
    if manquants:
        raise AssertionError(
            f"Etats d'echange sans couleur declaree : {sorted(manquants)}. "
            "Une couleur par etat, choisie, jamais deduite."
        )
    inconnus = set(_BADGE_BY_STATE) - etats
    if inconnus:
        raise AssertionError(f"Couleurs declarees pour des etats inexistants : {sorted(inconnus)}.")
    couleurs = set(_BADGE_BY_STATE.values())
    if not couleurs <= BADGE_CLASSES:
        raise AssertionError(
            f"Couleur hors du jeu ferme : {sorted(couleurs - BADGE_CLASSES)}. "
            "Le cahier §10.2 dit « quatre couleurs au maximum »."
        )
    if not etats >= WAITING_STATES:
        raise AssertionError(f"Etats d'attente inexistants : {sorted(WAITING_STATES - etats)}.")


def badge_class_for_state(state: str) -> str:
    """La classe de couleur d'un etat. Neutre pour un etat inconnu — la
    garde ci-dessus est ce qui empeche ce cas d'exister en production, et
    un ecran ne doit jamais tomber pour une valeur inattendue."""
    return _BADGE_BY_STATE.get(state, BADGE_NEUTRAL)


__all__ = [
    "BADGE_CLASSES",
    "WAITING_STATES",
    "assert_badge_vocabulary_is_complete",
    "badge_class_for_state",
]
