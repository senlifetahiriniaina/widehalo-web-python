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
    meme sprint : un rapport sans module ni libelle est inexploitable dans
    un inventaire — et c'est un inventaire exploitable qui manquait pour
    rationaliser."""
    incomplete = [
        report.code
        for report in _delivered_reports()
        if not report.module or not report.label or not report.permission
    ]
    assert not incomplete, f"Rapport(s) sans module, libelle ou permission : {incomplete}"
