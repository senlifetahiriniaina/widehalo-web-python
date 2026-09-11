"""D-B — la chaine hierarchique des roles, declaree une fois.

**Pourquoi elle doit exister.** Le commanditaire demande que la reprise en
main d'une affaire, et la validation d'un geste fait par un autre service,
remontent « au responsable, ou a defaut a son superieur », et que ce
principe vaille dans TOUS les modules. Le moteur d'approbation du socle
porte deja exactement cette forme — `ApprovalRule.approver_role` et
`fallback_approver_role` (`apps/core/models/workflow.py:58,68`) — mais
**aucune chaine n'etait declaree nulle part** : chaque regle devait nommer
son secours a la main, et aucune ne le faisait.

**Ce module ne cree aucun droit.** Il dit qui est au-dessus de qui ; ce sont
les regles d'approbation qui decident ce que cela permet. Un superieur ne
voit pas plus de donnees qu'avant : il devient seulement l'approbateur de
secours quand le titulaire n'a pas decide dans le delai.

**Ce que la chaine ne sait pas, et qui est ecrit plutot que devine.** Le
depot n'a pas de role « responsable comptable » ni « responsable
logistique » : `comptable` et `magasinier` remontent donc directement a
`direction`. Ce n'est pas un choix de conception, c'est l'etat du
referentiel des roles — le jour ou ces roles existeront, ils s'inserent
ici, et nulle part ailleurs.
"""

from __future__ import annotations

ROLE_SOMMET = "admin"

#: Le superieur de chaque role. `admin` n'en a pas : c'est le sommet.
#:
#: Les quatre responsables de departement (`resp_commercial`,
#: `resp_production`, `acheteur`, `rh`) sont ceux que `strategy` identifie
#: deja comme tels (`DEPARTMENT_HEAD_ROLES`) — la chaine ne les invente pas,
#: elle reprend la seule liste que le depot porte deja.
SUPERIEUR_DE: dict[str, str] = {
    "direction": ROLE_SOMMET,
    "resp_commercial": "direction",
    "resp_production": "direction",
    "acheteur": "direction",
    "rh": "direction",
    "commercial": "resp_commercial",
    "chef_atelier": "resp_production",
    # Faute d'un role de responsable dedie dans le referentiel, ces
    # quatre-la remontent a la direction. Reserve ecrite plutot que
    # hierarchie inventee.
    "comptable": "direction",
    "magasinier": "direction",
    "caissier": "direction",
    "controleur_gestion": "direction",
    "collaborateur": "direction",
}


def superieur_de(role: str) -> str | None:
    """Le role immediatement au-dessus, ou `None` au sommet."""
    return SUPERIEUR_DE.get(role)


def chaine_de(role: str) -> list[str]:
    """La remontee complete, du superieur direct jusqu'au sommet.

    Protege contre un cycle : une chaine mal declaree boucle sinon a
    l'infini dans une vue, et le defaut ne se verrait qu'en production."""
    chaine: list[str] = []
    courant = superieur_de(role)
    while courant is not None and courant not in chaine:
        chaine.append(courant)
        courant = superieur_de(courant)
    return chaine
