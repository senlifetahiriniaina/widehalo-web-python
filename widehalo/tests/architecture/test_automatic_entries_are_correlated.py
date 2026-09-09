"""Garde-fou bloquant (T5, PAY-2 contre l'interdit §4.3) : aucune écriture
comptable automatique sans corrélation réussie.

**La ligne que ce fichier défend, et pourquoi elle est fine.** L'interdit
du cahier (l.385) dit : « aucune automatisation ne crée ou ne modifie une
pièce comptable. Un flux entrant propose, un humain **ou une règle métier
déjà éprouvée** dispose. **Un relevé bancaire ingéré** produit des
propositions de lettrage, pas des écritures. » Le critère PAY-2 dit
l'inverse en apparence : une notification de paiement « produit l'écriture
d'encaissement **sans intervention comptable** ».

Les deux tiennent ensemble sur une distinction, et une seule : une
notification authentifiée portant une référence **que nous avons
nous-mêmes émise** est la règle éprouvée que l'interdit autorise ; une
ligne de relevé rapprochée par ressemblance ne l'est pas. Tout le lot T5
repose là-dessus, et la docstring de `payment_settlement` annonce depuis
le premier jour une garde qui n'existait pas.

**Ce que ce fichier mesure, et ce qu'il ne peut pas mesurer.** Il ne
prouve pas qu'une corrélation est correcte — c'est le travail du test de
bout en bout (`apps/accounting/tests/test_t5_encaissement.py`). Il prouve
la propriété STRUCTURELLE qu'aucun test de comportement ne peut tenir dans
la durée : **qu'il n'existe qu'un seul chemin automatique**, et que ce
chemin passe par la corrélation. Un module futur qui appellerait
`register_payment` depuis un abonné, une commande périodique ou un
ingesteur de relevé produirait des écritures automatiques sans référence
émise — et aucun test de comportement existant ne rougirait, puisqu'il ne
connaîtrait pas ce module.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.architecture._ast_utils import discover_apps, extract_imports, iter_app_python_files

#: Le module qui sait écrire un encaissement. L'importer, c'est pouvoir
#: produire une pièce comptable qui solde une créance.
_SETTLEMENT_MODULE = "apps.accounting.services.payments"
_SETTLEMENT_NAME = "register_payment"

#: Les voies autorisées, relatives à `apps/`. Chacune est motivée, et la
#: distinction qui compte est : cette voie est-elle déclenchée par un
#: HUMAIN, ou par un événement ?
#:
#: 1. `accounting/api.py` et `accounting/views.py` — un comptable saisit un
#:    règlement. C'est l'humain que l'interdit nomme, et il dispose.
#: 2. `accounting/management/commands/seed_accounting.py` — le jeu de
#:    démonstration. Un opérateur lance la commande ; rien n'est déclenché
#:    par un tiers.
#: 3. `accounting/services/payment_settlement.py` — LE chemin automatique,
#:    et le seul. Sa forme est vérifiée séparément ci-dessous : l'écriture
#:    n'y est atteignable qu'après qu'une intention a été retrouvée.
#:
#: Une quatrième entrée ajoutée ici sans motif du même ordre est une
#: régression de gouvernance : c'est l'interdit du §4.3 qui tombe, pas une
#: liste qui s'allonge.
_ALLOWED_PATHS = {
    "accounting/api.py",
    "accounting/views.py",
    "accounting/management/commands/seed_accounting.py",
    "accounting/services/payment_settlement.py",
}

#: Qui a le droit d'appeler quoi, dans `payment_settlement`. Les
#: ensembles sont EXACTS : un appelant de plus fait rougir, un de moins
#: aussi.
#:
#: **Deux portes mènent à l'écriture, et elles ne se valent pas.**
#: `_settle` est la porte AUTOMATIQUE : elle n'est atteignable qu'après
#: qu'une intention émise par nous a été retrouvée.
#: `assign_orphan_notification` est la porte HUMAINE de PAY-3 — « ne
#: produit aucune écriture tant qu'il n'est pas affecté » — où quelqu'un
#: DÉSIGNE la facture. Les deux écrivent ; une seule est déclenchée par un
#: tiers, et `test_the_manual_assignment_is_never_reachable_from_the_bus`
#: vérifie que la seconde ne le devient jamais.
_REQUIRED_CALLERS = {
    "_settle": {"receive_payment_notification"},
    "_register": {"_settle", "assign_orphan_notification"},
    "register_payment": {"_register"},
}

#: Le module abonné au bus. Il ne doit jamais pouvoir atteindre la porte
#: humaine : un abonné qui l'appellerait produirait des écritures
#: automatiques sur des notifications que rien n'a corrélées, en entrant
#: par la porte prévue pour une décision.
_SUBSCRIBER_FILE = "apps/accounting/services/payment_registration.py"
_MANUAL_DOOR = "assign_orphan_notification"

_SETTLEMENT_FILE = "apps/accounting/services/payment_settlement.py"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _relative_app_path(path: Path) -> str:
    parts = path.parts
    return "/".join(parts[parts.index("apps") + 1 :])


def _callers_of(tree: ast.AST) -> dict[str, set[str]]:
    """Pour chaque fonction appelée, l'ensemble des fonctions qui l'appellent.

    Le nom de la fonction ENGLOBANTE est celui du dernier `FunctionDef`
    traversé — suffisant ici, où le module n'imbrique aucune définition."""
    callers: dict[str, set[str]] = {}

    class _Visiteur(ast.NodeVisitor):
        def __init__(self) -> None:
            self.courante = "<module>"

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            precedente, self.courante = self.courante, node.name
            self.generic_visit(node)
            self.courante = precedente

        def visit_Call(self, node: ast.Call) -> None:
            cible = node.func
            if isinstance(cible, ast.Name):
                callers.setdefault(cible.id, set()).add(self.courante)
            self.generic_visit(node)

    _Visiteur().visit(tree)
    return callers


def test_only_the_correlated_path_can_write_a_payment_entry() -> None:
    """Aucun module hors liste ne sait produire un encaissement."""
    violations: list[str] = []
    for app in discover_apps():
        for file in iter_app_python_files(app, exclude_tests=True):
            relative = _relative_app_path(file)
            if relative in _ALLOWED_PATHS:
                continue
            source = file.read_text(encoding="utf-8")
            for record in extract_imports(file):
                if record.module == _SETTLEMENT_MODULE and _SETTLEMENT_NAME in source:
                    violations.append(f"{relative} : importe '{_SETTLEMENT_NAME}'")

    assert not violations, (
        "§4.3 : voie(s) capables d'écrire une pièce comptable d'encaissement hors "
        "du chemin corrélé :\n" + "\n".join(violations) + "\n\n"
        "Une notification qui n'a pas retrouvé une intention émise par nous "
        "PROPOSE ; elle n'écrit pas. Passer par "
        "`payment_settlement.receive_payment_notification`, ou motiver l'exception "
        "dans la docstring de ce module."
    )


def test_the_automatic_path_goes_through_correlation() -> None:
    """L'écriture n'est atteignable qu'au bout de la chaîne de corrélation.

    **C'est la moitié que la liste d'autorisation ne peut pas tenir.**
    `payment_settlement` a le droit d'écrire — mais si demain quelqu'un
    appelait `_register` directement depuis `receive_payment_notification`,
    en sautant `_settle`, l'écriture se produirait sans qu'aucune intention
    n'ait été retrouvée. Le module resterait dans la liste, et la propriété
    serait perdue."""
    tree = ast.parse((_repo_root() / _SETTLEMENT_FILE).read_text(encoding="utf-8"))
    callers = _callers_of(tree)

    ecarts: list[str] = []
    for appele, attendus in _REQUIRED_CALLERS.items():
        appelants = callers.get(appele, set())
        if not appelants:
            ecarts.append(f"'{appele}' n'est appelée par personne")
        elif appelants != attendus:
            ecarts.append(
                f"'{appele}' est appelée par {sorted(appelants)} ; "
                f"attendu exactement {sorted(attendus)}"
            )

    assert not ecarts, (
        "PAY-2 : la chaîne qui mène à l'écriture automatique a changé de forme :\n"
        + "\n".join(ecarts)
        + "\n\nL'écriture doit rester inatteignable sans être passée par la "
        "corrélation d'une référence que nous avons émise."
    )


def test_the_manual_assignment_is_never_reachable_from_the_bus() -> None:
    """La porte HUMAINE de PAY-3 reste hors de portée d'un abonné.

    **C'est le contournement que la liste d'autorisation ne verrait pas.**
    `payment_settlement` a le droit d'écrire, et `assign_orphan_notification`
    y vit légitimement : un abonné qui l'appellerait produirait donc des
    écritures automatiques sur des notifications que rien n'a corrélées,
    sans qu'aucune des autres gardes ne rougisse. « Un humain a cliqué »
    est ce qui distingue cette porte de l'autre ; le bus ne clique
    jamais."""
    source = (_repo_root() / _SUBSCRIBER_FILE).read_text(encoding="utf-8")
    assert _MANUAL_DOOR not in source, (
        f"{_SUBSCRIBER_FILE} nomme '{_MANUAL_DOOR}' : la porte réservée à une "
        "décision humaine (PAY-3) devient atteignable depuis le bus, donc "
        "depuis un tiers."
    )


def test_the_correlation_lookup_stands_between_the_reference_and_the_entry() -> None:
    """Une référence sans intention retrouvée ne descend jamais vers `_settle`.

    La forme exigée est celle qu'`ast` peut lire sans deviner : la fonction
    d'entrée cherche une `AccPaymentIntent`, et elle contient un retour
    ANTICIPÉ quand la recherche ne rend rien. Retirer ce retour ferait
    passer une notification orpheline dans le chemin qui écrit."""
    tree = ast.parse((_repo_root() / _SETTLEMENT_FILE).read_text(encoding="utf-8"))
    entree = next(
        noeud
        for noeud in ast.walk(tree)
        if isinstance(noeud, ast.FunctionDef) and noeud.name == "receive_payment_notification"
    )
    source_entree = ast.unparse(entree)

    assert "AccPaymentIntent.objects.filter" in source_entree, (
        "La fonction d'entrée ne cherche plus d'intention : la corrélation "
        "n'existe plus, et l'écriture reposerait sur autre chose qu'une "
        "référence émise par nous."
    )
    assert "if intention is None" in source_entree, (
        "Le refus explicite d'une notification sans intention a disparu. Sans "
        "lui, une référence inconnue — donc un rapprochement que nous ne "
        "pouvons pas justifier — descend vers le chemin qui écrit."
    )


def test_only_one_outcome_can_claim_to_have_written() -> None:
    """`produced_an_entry` est vrai pour EXACTEMENT un dénouement.

    La garde interroge cette propriété plutôt que la valeur de la chaîne :
    ajouter demain un `OUTCOME_PROBABLE` qui la rendrait vraie ferait
    tomber ce test, ce qu'une comparaison de chaînes ne ferait pas."""
    from apps.accounting.services import payment_settlement as module

    denouements = [
        valeur
        for nom, valeur in vars(module).items()
        if nom.startswith("OUTCOME_") and isinstance(valeur, str)
    ]
    assert len(denouements) >= 4, (
        "Les dénouements ont été réduits : le module en déclarait quatre, "
        "chacun appelant un écran et une action différents."
    )

    ecrivent = [
        denouement
        for denouement in denouements
        if module.SettlementResult(outcome=denouement).produced_an_entry
    ]
    assert ecrivent == [module.OUTCOME_SETTLED], (
        f"{ecrivent} prétend(ent) avoir produit une écriture. Seule une "
        "corrélation réussie le peut : orpheline, doublon et référence "
        "inconnue PROPOSENT, elles n'écrivent pas (PAY-3)."
    )


def test_the_allowlist_has_no_obsolete_entry() -> None:
    """Une exemption qui survit au fichier qu'elle exemptait autoriserait à
    recréer ce chemin plus tard sans que personne ne rejoue la décision."""
    apps_dir = _repo_root() / "apps"
    manquants = [chemin for chemin in sorted(_ALLOWED_PATHS) if not (apps_dir / chemin).exists()]
    assert not manquants, "Entrée(s) obsolète(s) dans `_ALLOWED_PATHS` : " + ", ".join(manquants)
