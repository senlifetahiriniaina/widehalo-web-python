"""C-3 — « quelle est la suite ? », pour un objet et pour un utilisateur.

**Ce que ce module rend possible.** Le cahier demande que l'utilisateur
sache facilement quelle est l'etape suivante, sur tous les ecrans, et que
le kanban soit lie au processus en cours. Les deux ont besoin de la MEME
reponse : pour cet objet, dans son etat, et pour cette personne, quelles
suites sont possibles ? Ce module la calcule ; C-4 l'affiche.

**Pourquoi un registre plutot qu'une introspection.** Trois mecanismes
d'etat coexistent dans les quatre modules prioritaires, et aucune lecture
unique ne les couvre :

- `django_fsm` — `SalesOrder.state`, `AccMove.invoice_state`,
  `LogShipment.state`. Introspectable : la machine sait ce que l'etat
  courant autorise.
- un `CharField` ordinaire plus des fonctions de service —
  `SalesQuotation.state`, `LogTrip.status`. Rien a introspecter : les
  suites vivent dans le code des vues.
- un pipeline CONFIGURABLE par societe — `CrmLead` via `CrmStage`. Les
  etapes ne sont pas dans le code du tout, elles sont en base et changent
  d'un client a l'autre.

Chaque module declare donc son resolveur depuis `apps.py::ready()`, comme
le registre d'ecrans de T8 : `core` ne depend d'aucun module metier.

**La correction qui a decide de la conception.** `django_fsm` expose
`get_available_user_FIELD_transitions(user)`, presente dans la
bibliotheque installee et appelee NULLE PART dans ce depot. Elle paraissait
etre la reponse complete. Elle ne l'est pas : elle filtre sur le
`permission=` declare par chaque transition, or le depot compte **112
transitions dont 3 seulement en declarent un** — la docstring
d'`attempt_transition` le reconnait elle-meme. Employee seule, elle
proposerait donc a un `controleur_gestion`, qui n'a que la LECTURE sur
`sales` et `accounting`, de confirmer une commande.

D'ou la regle de ce module : **une suite n'est proposee que si
l'utilisateur a le droit d'ECRITURE** de C-1 sur l'objet. Le droit ferme
la porte que la machine a etats ne connait pas.

**Une liste vide plutot qu'une liste grisee.** Un utilisateur sans droit
d'ecriture recoit zero suite, jamais des suites barrees : proposer ce
qu'on refusera est precisement ce que C-1d a corrige sur les boutons.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from apps.core.models.user import User


@dataclass(frozen=True)
class NextStep:
    """Une suite possible : ce qu'on peut faire, et comment le nommer.

    `label` est ce que l'humain lit — il vient TOUJOURS du module metier,
    `core` ne peut pas savoir que la transition `confirm` se dit
    « Confirmer la commande ».

    `post_data` est ce que l'ecran doit POSTER pour l'executer, et il ne se
    deduit pas du code. Trois des quatre modules postent `action=<code>`,
    mais le CRM poste `action=move_stage` PLUS `stage_id=<uuid>` : une
    structure ne portant qu'un code aurait oblige le gabarit a connaitre
    le cas particulier de chaque module, c'est-a-dire a recreer dans la
    presentation le couplage que le registre evite. Laisse a `None`, il
    vaut `{"action": code}` — la forme des trois autres."""

    code: str
    label: str
    post_data: Mapping[str, str] | None = None

    def champs(self) -> dict[str, str]:
        """Les champs de formulaire a poster pour executer cette suite."""
        return dict(self.post_data) if self.post_data is not None else {"action": self.code}


#: Resolveur declare par un module metier : (objet, utilisateur) -> suites.
Resolveur = Callable[[Any, User], list[NextStep]]

_RESOLVEURS: dict[str, Resolveur] = {}


def register_next_steps(model_label: str, resolveur: Resolveur) -> None:
    """Declare comment calculer les suites d'un modele.

    `model_label` s'ecrit `"app.Modele"`. Redeclarer le meme modele avec un
    resolveur DIFFERENT est refuse : deux reponses concurrentes a « quelle
    est la suite » donneraient deux ecrans qui se contredisent, et le
    dernier `ready()` execute gagnerait — c'est-a-dire personne en
    particulier. Meme garde que `register_document_screen` (T8)."""
    existant = _RESOLVEURS.get(model_label)
    if existant is not None and existant is not resolveur:
        raise ValueError(
            f"Deux resolveurs de suites declares pour {model_label} : "
            f"{existant!r} puis {resolveur!r}."
        )
    _RESOLVEURS[model_label] = resolveur


def next_steps_for(instance: Any, user: User) -> list[NextStep]:
    """Les suites possibles pour cet objet et cet utilisateur.

    Rend une liste vide — jamais une erreur — pour un modele sans
    resolveur declare : tous les documents n'ont pas de processus, et un
    ecran qui n'a rien a proposer doit simplement ne rien proposer."""
    resolveur = _RESOLVEURS.get(instance._meta.label)
    return resolveur(instance, user) if resolveur is not None else []


def registered_models() -> frozenset[str]:
    """Les modeles dotes d'un resolveur — lu par la garde d'architecture."""
    return frozenset(_RESOLVEURS)


def fsm_next_steps(
    instance: Any,
    user: User,
    *,
    field_name: str,
    write_codename: str,
    labels: dict[str, str],
    actions: Mapping[str, str] | None = None,
    permissions: Mapping[str, str] | None = None,
) -> list[NextStep]:
    """Les suites d'un modele `django_fsm`, filtrees par le droit d'ecriture.

    `get_available_user_FIELD_transitions` trouve ici son premier appelant
    du depot. Le droit d'ecriture est verifie EN PLUS, et d'abord : voir la
    docstring de module — la machine a etats ignore le RBAC tant que les
    transitions ne declarent pas `permission=`, ce que 109 des 112 ne font
    pas.

    **`labels` est un JEU FERME, et c'est la correction la plus importante
    de ce module.** La premiere version proposait TOUTE transition
    disponible, avec `labels.get(nom, nom)` en repli — donc deux defauts a
    la fois. D'abord une transition non libellee s'affichait a l'exploitant
    sous son nom technique. Ensuite, et c'est le grave : **une transition
    disponible n'est pas forcement une action d'ecran**. Mesure sur les
    factures : `mark_paid` et `mark_paid_partially` sont des CONSEQUENCES
    de `register_payment` (`apps/accounting/services/payments.py:131-133`)
    — les proposer en boutons aurait permis de marquer une facture reglee
    **sans aucune ecriture comptable**. Une transition absente de `labels`
    n'est donc plus proposee du tout.

    **`actions` dit ce que l'ecran attend**, quand son vocabulaire differe
    du nom de la transition. Mesure : le bandeau postait `mark_invoiced`,
    `mark_delivered` et `mark_partially_delivered` la ou la vue des
    commandes attend `invoice`, `deliver_full` et `deliver_partial`
    (`apps/sales/views.py:365-374`) — aucune branche ne correspondait, le
    `else` rendait la redirection, et **trois boutons ne faisaient rien en
    silence**. Le mapping vit ici, avec la declaration, et non dans le
    gabarit qui devrait alors connaitre chaque module.

    **`permissions` donne son droit PROPRE a une action**, quand il differe
    du droit d'ecriture general. Mesure : l'ecran des factures exige
    `accounting.validate_accmove` pour valider et `cancel_accmove` pour
    annuler (`apps/accounting/views.py:94-98`), alors que le bandeau ne
    verifiait que `change_accmove`. Un role dote de `change` mais pas de
    `validate` se voyait donc proposer un bouton que la garde refusait en
    403 — exactement le defaut que C-1d avait corrige sur les boutons de
    gabarit, refait par le socle. Un droit absent RETIRE l'etape ; il ne la
    grise pas."""
    if not user.has_perm(write_codename):
        return []
    transitions: Iterable[Any] = getattr(instance, f"get_available_user_{field_name}_transitions")(
        user
    )
    correspondance = actions or {}
    droits = permissions or {}
    disponibles = {t.name for t in transitions}
    # **L'ordre de `labels` fait l'ordre de l'ECRAN.** Mesure sur une
    # commande neuve : `get_available_user_FIELD_transitions` rendait
    # `cancel`, `confirm`, `send` — dans l'ordre de declaration de la
    # machine a etats — si bien que le bouton PRINCIPAL du bandeau, celui
    # que l'exploitant voit en premier sur une commande a envoyer, etait
    # « Annuler ». Le commanditaire demande que l'utilisateur ait
    # facilement idee de la suite a prendre ; lui proposer d'abord
    # d'abandonner est l'exact contraire. L'ordre metier n'est connu que du
    # module, et il l'exprime par l'ordre de son dictionnaire.
    return [
        NextStep(nom, labels[nom], {"action": correspondance.get(nom, nom)})
        for nom in labels
        if nom in disponibles and user.has_perm(droits.get(nom, write_codename))
    ]


def declared_next_steps(
    instance: Any,
    user: User,
    *,
    state_field: str,
    write_codename: str,
    par_etat: dict[str, list[NextStep]],
) -> list[NextStep]:
    """Les suites d'un modele dont l'etat est un `CharField` ordinaire.

    `SalesQuotation` et `LogTrip` n'ont pas de machine a etats : leurs
    transitions vivent dans des fonctions de service que rien ne declare.
    Le module fournit donc la table etat -> suites, et elle est verifiee
    par une garde (les etats cites doivent exister dans les `choices` du
    champ) pour qu'un etat renomme ne la vide pas en silence."""
    if not user.has_perm(write_codename):
        return []
    return list(par_etat.get(getattr(instance, state_field), []))
