"""BI-3 (L9) — budget de rapports, verifie en CI.

**Ce que ce garde-fou ferme, et ce qu'il ne ferme pas.** Le critere BI-3
demande de reconstruire « les rapports retenus a l'issue de la
rationalisation » du catalogue HERITE et de les rapprocher a l'ariary pres
de leur version d'origine. Ce catalogue — 91 rapports du systeme existant
du client — **n'est pas dans le depot** : aucun code ne peut fermer ce
critere seul, et produire un arbitrage « conserver / fusionner /
parametrer / supprimer » sur un inventaire qu'on n'a jamais vu serait un
faux. Le critere reste donc ouvert, avec son motif ecrit dans l'audit.

Ce qui est faisable sans le catalogue d'origine, le cahier le demande dans
le meme paragraphe (H6, et le risque P2-R2 « porter le catalogue tel quel
industrialise l'incoherence ») : **borner la derive**. C'est l'objet de ce
test.

Il ne dit pas que le catalogue est coherent. Il dit qu'il ne grossit pas
sans decision — ce qui est exactement la moitie du risque qu'on peut
tenir.

**Pourquoi le comptage exclut les enregistrements de test.** `_REGISTRY`
est un dictionnaire de module, peuple une fois au demarrage de Django et
JAMAIS reinitialise (c'est sa conception, cf. sa docstring). Les tests de
`apps/reporting/tests/` y ecrivent leurs propres rapports factices, qui y
restent pour toute la session. Une premiere version de ce garde-fou
comptait le registre brut : elle passait a 63 en isolation et echouait a
81/80 dans la suite complete. Un budget dont le resultat depend de l'ordre
des tests ne mesure rien — il rougit au hasard, et on finit par relever le
plafond pour le faire taire, ce qui est exactement le contraire de ce
qu'un budget sert a faire.

Le filtre applique est celui que `test_budget.py` emploie deja pour les
modeles (`if ".tests." in model.__module__: continue`) : un rapport est
compte comme livre si son renderer est defini dans du code de production.
Meme probleme, meme remede."""

from __future__ import annotations

from apps.core.services.reports_registry import RegisteredReport, list_registered_reports
from django.conf import settings


def _is_test_registration(report: RegisteredReport) -> bool:
    """`True` si ce rapport a ete enregistre par un test.

    Le registre ne memorise pas son appelant ; le renderer, lui, sait ou il
    est defini. Un rapport SANS aucun renderer ne peut pas etre enregistre
    (`register_report` leve `ValueError`), donc ce test ne peut jamais etre
    pris en defaut par une entree sans renderer."""
    for renderer in (report.render_pdf, report.render_rows):
        if renderer is not None:
            module = getattr(renderer, "__module__", "")
            return ".tests." in module or module.split(".")[-1].startswith("test_")
    return False


def _delivered_reports() -> list[RegisteredReport]:
    return [r for r in list_registered_reports() if not _is_test_registration(r)]


def test_report_budget_not_exceeded() -> None:
    reports = _delivered_reports()
    assert len(reports) <= settings.BUDGET_MAX_REPORTS, (
        f"Plafond de rapports depasse : {len(reports)}/{settings.BUDGET_MAX_REPORTS}. "
        "Rationaliser le catalogue, ou relever le plafond avec un motif ecrit "
        "(meme discipline que les budgets de modeles/ecrans/endpoints)."
    )


def test_the_registry_is_actually_populated() -> None:
    """Sans cette assertion, le budget passerait sur un catalogue VIDE le
    jour ou la decouverte des modules casserait — une garde qui n'inspecte
    rien est verte par construction (meme precaution que
    `test_ai_tools_are_read_only`)."""
    assert len(_delivered_reports()) >= 50


def test_the_test_registration_filter_actually_filters() -> None:
    """Auto-test du detecteur. Sans lui, `_is_test_registration` pourrait
    renvoyer `False` pour tout (une faute de frappe dans `".tests."`
    suffit) et le budget redeviendrait dependant de l'ordre des tests —
    en silence, puisqu'il serait alors simplement plus permissif.

    On enregistre ici un rapport depuis CE fichier de test : il doit etre
    reconnu comme tel, et donc exclu du comptage."""
    from apps.core.services.reports_registry import get_registered_report, register_report

    def _rows(params, user):  # noqa: ANN001, ANN202 — renderer factice
        return []

    register_report(
        code="RPT-BUDGET-SELFTEST",
        module="core",
        label="Auto-test du detecteur de budget",
        permission="core.view_tenant",
        owner_role="admin",
        description="Enregistrement factice servant a l'auto-test du filtre ci-dessus.",
        render_rows=_rows,
    )
    registered = get_registered_report("RPT-BUDGET-SELFTEST")
    assert registered is not None

    assert _is_test_registration(registered), (
        "Le detecteur ne reconnait pas un enregistrement fait depuis un test : "
        "le budget recompte les rapports factices et redevient dependant de "
        "l'ordre d'execution."
    )
    assert registered not in _delivered_reports()


def test_every_registered_report_declares_its_owner_module_and_label() -> None:
    """Le volet « catalogue avec domaine, description, proprietaire » du
    cahier (Phase 2, sprint S6).

    **Ce test MENTAIT.** Sa docstring annonçait « domaine, description,
    propriétaire » et son assertion vérifiait module, libellé et
    permission — trois champs qui existaient déjà, et dont aucun n'est le
    propriétaire. `RegisteredReport` n'avait ni `owner_role` ni
    `description` : le test ne pouvait donc pas vérifier ce qu'il
    annonçait, et il est resté vert pendant tout ce temps.

    Le domaine, lui, EST `module` — ajouter un second champ qui le
    duplique aurait été pire que de ne rien faire. C'est écrit ici plutôt
    que laissé à deviner.

    Le contrôle réel vit désormais dans `register_report`, qui REFUSE un
    enregistrement incomplet : un refus à l'écriture nomme le rapport
    fautif au moment où on l'écrit, là où un test dit « il en manque
    trois » à la fin de la construction. Ce test garde la propriété au
    niveau du catalogue entier, pour le cas où quelqu'un contournerait le
    constructeur."""
    incomplets = [
        report.code
        for report in _delivered_reports()
        if not report.module
        or not report.label
        or not report.permission
        or not report.owner_role
        or not report.description
    ]
    assert not incomplets, (
        f"Rapport(s) sans module, libelle, permission, proprietaire ou description : {incomplets}"
    )


def test_the_registry_refuses_an_incomplete_report() -> None:
    """Auto-test du refus. Sans lui, `register_report` pourrait cesser de
    controler et le test precedent resterait vert tant que personne
    n'ajoute de rapport — c'est-a-dire longtemps."""
    import pytest
    from apps.core.services.reports_registry import register_report

    def _rows(params, actor):
        return []

    with pytest.raises(ValueError, match="owner_role"):
        register_report(
            code="RPT-SANS-PROPRIETAIRE",
            module="core",
            label="Essai",
            permission="core.view_tenant",
            owner_role="",
            description="Une description parfaitement valable et suffisamment longue.",
            render_rows=_rows,
        )

    with pytest.raises(ValueError, match="description"):
        register_report(
            code="RPT-SANS-DESCRIPTION",
            module="core",
            label="Essai",
            permission="core.view_tenant",
            owner_role="admin",
            description="",
            render_rows=_rows,
        )


def test_an_owner_role_is_a_role_the_repository_actually_knows() -> None:
    """Un proprietaire designe par un code de role inexistant ne designe
    personne. La verification se fait contre le referentiel de roles, pas
    contre une liste recopiee ici — c'est le seul cas ou recopier serait
    faux, puisque c'est justement l'adherence entre les deux qu'on
    verifie."""
    from apps.core.services.rbac_policy import ROLE_APP_PERMISSIONS

    inconnus = {
        report.code: report.owner_role
        for report in _delivered_reports()
        if report.owner_role not in ROLE_APP_PERMISSIONS
    }
    assert not inconnus, (
        f"Proprietaire(s) designant un role inexistant : {inconnus}. "
        f"Roles connus : {sorted(ROLE_APP_PERMISSIONS)}."
    )


def test_a_description_says_what_the_report_shows_not_what_it_computes() -> None:
    """Verification grossiere, et c'est assume : elle n'attrape pas une
    mauvaise phrase, elle attrape une phrase VIDE — le cas ou quelqu'un
    remplit le champ de trois mots pour faire passer le refus a
    l'enregistrement.

    Le seuil de quarante caracteres est celui d'une phrase complete. Un
    libelle recopie (« Balance generale ») n'y arrive pas, et c'est
    exactement ce qu'on veut ecarter : la description doit ajouter quelque
    chose au libelle, sinon elle ne sert a rien dans un inventaire."""
    trop_courtes = {
        report.code: report.description
        for report in _delivered_reports()
        if len(report.description) < 40
    }
    assert not trop_courtes, (
        f"Description(s) trop courtes pour dire ce que le rapport montre : {sorted(trop_courtes)}"
    )

    recopiees = {
        report.code
        for report in _delivered_reports()
        if report.description.strip().lower() == report.label.strip().lower()
    }
    assert not recopiees, f"Description(s) recopiant le libelle : {sorted(recopiees)}"
