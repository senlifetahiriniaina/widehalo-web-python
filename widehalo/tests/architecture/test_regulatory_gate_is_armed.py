"""Garde-fou bloquant — ACC-9 : le verrou reglementaire tourne en
INTEGRATION CONTINUE, contre les donnees reellement semees.

**Le critere, mot pour mot** (Phase 1, §13.3) : « Un test d'integration
continue empeche tout deploiement en production si un parametre utilise par
un calcul actif porte le statut NON_VALIDE. La validation par un
expert-comptable membre de l'OECFM n'est donc pas une bonne pratique
documentaire : c'est une condition technique de deploiement. »

**Ce qui manquait, et l'objection qu'il faut traiter de front.** Le verrou
existait en deux morceaux : la logique (`regulatory_governance`) et une
commande de deploiement (`check_regulatory_validation`). Le test qui
l'accompagnait, `apps/core/tests/test_regulatory_deployment_gate.py`,
verifie la LOGIQUE — et il commence par une fixture qui EFFACE toutes les
lignes reellement semees, pour que ses assertions ne dependent pas d'elles.
C'est le bon choix pour lui. Mais il en decoule qu'aucun test du depot ne
regardait jamais les parametres reels. Sa docstring le disait, en renvoyant
la correction a un job « hors de portee d'un job GitHub Actions qui ne
connait pas l'etat du serveur cible ».

Cette objection est vraie pour UNE moitie de la question et fausse pour
l'autre. Vraie : la CI ne connait pas les validations saisies dans l'admin
d'une instance de production, et ne peut donc pas dire « ce serveur-ci est
deployable ». Fausse : la CI connait parfaitement les parametres SEMES par
les migrations, qui sont ceux avec lesquels toute instance neuve demarre —
et c'est la que vivent les trois defauts que ce fichier attrape :

1. **un code du registre qui n'est seme nulle part.** Le registre bloque
   alors sur rien, en silence. Le defaut n'est pas theorique : `tva.
   taux_normal` a ete reference a quatre endroits du depot et cree nulle
   part, jusqu'a ce que L3 le constate ;
2. **un parametre seme, lu par un calcul actif, et absent du registre.**
   Il echappe alors entierement au verrou. C'est ce qui est arrive a
   `tva.seuil_assujettissement`, ferme par ce meme lot ;
3. **le verrou desarme.** Si toutes les valeurs semees passaient un jour
   au statut valide sans qu'un expert soit intervenu, la commande de
   deploiement rendrait « autorise » et personne ne le verrait.

Ces trois-la se verifient sans connaitre le serveur cible. Le point 3
demande d'ecrire ce qu'on ATTEND — et c'est le sens de ce fichier : les
valeurs semees par les migrations portent toutes leur reserve OECFM, donc
le verrou DOIT bloquer sur une base neuve. Un vert ici signifierait que
quelqu'un a leve une reserve en modifiant une migration.
"""

from __future__ import annotations

import pytest
from apps.accounting.services.vat_reference import (
    VAT_LIABILITY_THRESHOLD_CODE as CODE_COTE_COMPTABILITE,
)
from apps.core.models.regulatory import RegulatoryParameter
from apps.core.services.regulatory_governance import (
    ACTIVE_CALCULATION_PARAMETER_CODES,
    GLOBAL_PARAMETER_CODES,
    PER_TENANT_PARAMETER_CODES,
    unvalidated_active_parameters,
)
from apps.core.services.regulatory_governance import (
    VAT_LIABILITY_THRESHOLD_CODE as CODE_COTE_SOCLE,
)
from apps.core.tests.factories import TenantFactory
from apps.payroll.services.seed import seed_payroll_regulatory_params
from django.core.management import call_command
from django.core.management.base import CommandError

pytestmark = pytest.mark.django_db


def test_the_threshold_code_is_the_same_string_on_both_sides() -> None:
    """`core` ne peut pas importer `accounting` (regle de couplage n1) : le
    code du seuil est donc ecrit deux fois. Ce test est le seul endroit qui
    voit les deux — sans lui, un renommage cote comptabilite ferait sortir
    le parametre du verrou sans que rien ne proteste."""
    assert CODE_COTE_SOCLE == CODE_COTE_COMPTABILITE


def test_the_vat_liability_threshold_is_under_the_gate() -> None:
    """LE critere ACC-9, sur le parametre qui lui echappait.

    « Un parametre utilise par un calcul actif » : `resolve_vat_liability_
    thresholds` decide si une societe est assujettie de plein droit, si elle
    peut opter, ou si elle releve de l'impot synthetique. C'est une decision
    fiscale, pas un affichage — et le registre ne le portait pas.

    Assertion NOMMANTE plutot que structurelle : retirer ce code du registre
    laisserait tous les autres tests de ce fichier verts, puisque
    `tva.taux_normal` suffit a les satisfaire."""
    assert CODE_COTE_SOCLE in ACTIVE_CALCULATION_PARAMETER_CODES
    assert CODE_COTE_SOCLE in GLOBAL_PARAMETER_CODES


def test_every_global_parameter_is_actually_seeded_by_a_migration() -> None:
    """Un registre qui nomme un parametre inexistant ne bloque rien.

    C'est le defaut le plus discret de la famille : tout a l'air en place,
    la commande de deploiement rend « autorise », et le parametre cense
    etre gouverne n'existe simplement pas. `tva.taux_normal` a vecu ainsi
    jusqu'a L3 — reference a quatre endroits, cree nulle part."""
    absents = [
        code
        for code in sorted(GLOBAL_PARAMETER_CODES)
        if not RegulatoryParameter.objects.filter(code=code, tenant__isnull=True).exists()
    ]
    assert not absents, (
        "Codes declares GLOBAUX et semes par aucune migration — le verrou ne "
        f"bloque sur rien pour eux : {absents}"
    )


def test_every_per_tenant_parameter_is_created_by_its_seed() -> None:
    """L'autre moitie du registre, dans les conditions qui sont les siennes.

    Les dix parametres de paie naissent d'un SEED par societe, jamais d'une
    migration : les chercher en global comme les precedents rendrait un
    rouge qui ne veut rien dire. Ce qui se verifie ici est la seule chose
    verifiable sans serveur cible, et c'est la bonne : apres le seed, chaque
    code du registre existe REELLEMENT pour cette societe. Un code ajoute au
    registre sans etre ajoute au seed est attrape ici."""
    societe = TenantFactory()
    seed_payroll_regulatory_params(societe)
    absents = [
        code
        for code in sorted(PER_TENANT_PARAMETER_CODES)
        if not RegulatoryParameter.objects.filter(code=code, tenant=societe).exists()
    ]
    assert not absents, (
        "Codes declares PER-TENANT et crees par aucun seed — le verrou ne "
        f"bloque sur rien pour eux : {absents}"
    )


def test_the_two_families_together_cover_the_whole_registry() -> None:
    """Aucun code ne doit tomber entre les deux : un code qui ne serait ni
    global ni per-tenant ne serait verifie par aucun des deux tests
    ci-dessus, et le verrou le concernant ne serait jamais mesure."""
    assert GLOBAL_PARAMETER_CODES | PER_TENANT_PARAMETER_CODES == (
        ACTIVE_CALCULATION_PARAMETER_CODES
    )
    assert not (GLOBAL_PARAMETER_CODES & PER_TENANT_PARAMETER_CODES)


def test_the_deployment_gate_blocks_on_a_freshly_migrated_database() -> None:
    """Le verrou est ARME, et il doit l'etre sur une base neuve.

    Toutes les valeurs semees portent leur reserve OECFM (« A CONFIRMER
    OECFM/DGI »), parce que le cahier pose qu'« aucune hypothese
    reglementaire ne peut etre levee par defaut au motif que le
    developpement doit avancer ». Le verrou doit donc refuser le
    deploiement. Un vert ici — c'est-a-dire un verrou qui laisse passer —
    voudrait dire qu'une migration a marque une valeur validee sans qu'un
    expert-comptable soit intervenu."""
    bloquants = unvalidated_active_parameters()
    assert bloquants, (
        "Le verrou reglementaire ne bloque plus rien sur une base neuve. "
        "Soit toutes les valeurs semees ont ete marquees validees dans une "
        "migration — ce que le cahier interdit (§13.3) — soit le registre "
        "est vide."
    )
    with pytest.raises(CommandError) as refus:
        call_command("check_regulatory_validation")
    assert "OECFM" in str(refus.value)


def test_the_gate_names_every_governed_family() -> None:
    """Le verrou doit bloquer sur les DEUX familles, pas seulement sur une.

    Sans cette assertion, retirer `tva.*` du registre laisserait le test
    precedent parfaitement vert : dix parametres de paie suffisent a le
    satisfaire. C'est exactement la maniere dont un verrou se vide de sa
    substance sans qu'un test ne rougisse.

    La societe est semee ici parce que c'est la SEULE facon de voir la
    famille per-tenant — et c'est aussi ce que fait la commande de
    deploiement, qui passe `tenants=Tenant.objects.all()`."""
    societe = TenantFactory()
    seed_payroll_regulatory_params(societe)
    codes_bloquants = {row.code for row in unvalidated_active_parameters(tenants=[societe])}
    assert any(code.startswith("payroll.") for code in codes_bloquants), (
        "Aucun parametre de paie sous le verrou alors que la societe vient "
        f"d'etre semee. Bloquants : {sorted(codes_bloquants)}"
    )
    assert any(code.startswith("tva.") for code in codes_bloquants), (
        "Aucun parametre de TVA sous le verrou : le registre ne couvre plus "
        f"que la paie. Bloquants : {sorted(codes_bloquants)}"
    )
