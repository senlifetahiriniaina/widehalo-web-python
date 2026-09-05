"""Garde-fou bloquant : toute commande de gestion est classee — periodique et
declaree au registre, ou ponctuelle et motivee ici.

Le defaut que cette garde ferme n'etait pas une commande mal ecrite, mais
dix-neuf commandes justes que **rien n'appelait**. Aucun ordonnanceur
n'existait dans ce depot : ni crontab, ni unite systemd, ni service dans
`docker-compose.prod.yml`, ni objet `Schedule` django-q2. Chaque commande se
declarait periodique dans sa propre docstring, et le document de deploiement
n'en nommait que trois. La consequence etait en chaine et invisible module par
module : l'entrepot analytique n'etant jamais rafraichi, BI, Forecast et
Strategy restituaient des tableaux vides en exploitation alors que chacun
passait ses tests.

Une docstring ne planifie rien. A partir de L0-3, la cadence est une donnee
declaree (`apps.core.services.scheduled_commands`) et ecrite au deploiement
(`sync_scheduled_commands`) ; cette garde interdit d'ajouter une vingtieme
commande periodique en comptant sur le meme oubli.

**Limite assumee** : la garde verifie qu'une decision a ete PRISE pour chaque
commande, pas qu'elle est la bonne. Inscrire a tort une commande periodique
sur la liste ci-dessous la fait passer — mais il faut l'ecrire, avec son
motif, et ce motif est relu. C'est le meme contrat que
`test_no_hardcoded_account_numbers.py` : la liste d'exception rend l'ecart
visible et date, elle ne l'empeche pas.
"""

from __future__ import annotations

from pathlib import Path

APPS_DIR = Path(__file__).resolve().parent.parent.parent / "apps"

_MOTIF_REFERENTIEL = (
    "Chargement de referentiel : rejoue a la main lors d'une mise a jour de la "
    "norme ou a la creation d'un tenant, jamais a cadence fixe."
)
_MOTIF_AMORCAGE = (
    "Amorcage de demonstration : cree des donnees fictives. Planifiee, elle "
    "polluerait la production a chaque passage."
)

# Commandes ponctuelles par nature. Toute commande absente du registre de
# planification ET de cette liste fait echouer la CI : c'est le point de la
# garde -- forcer une decision explicite, pas la deviner.
_ONE_SHOT_COMMANDS: dict[str, str] = {
    # --- Exploitation, invoquee par l'operateur ---
    "apply_rls": (
        "DDL d'administration (activation de la RLS). Etape de deploiement, "
        "rejouee apres une migration qui ajoute une table."
    ),
    "bootstrap_admin": "Creation du premier compte d'administration, une fois par instance.",
    "create_tenant": "Creation d'un tenant, a la demande commerciale.",
    "sync_scheduled_commands": (
        "C'est la commande qui ECRIT les planifications. Se planifier "
        "elle-meme n'aurait pas de sens : elle est appelee au deploiement."
    ),
    # --- Les deux commandes qui ne doivent SURTOUT PAS etre planifiees ---
    "check_regulatory_validation": (
        "Leve un CommandError par conception : c'est un verrou de deploiement "
        "qui refuse la mise en production tant que les parametres reglementaires "
        "ne sont pas valides par un tiers. Planifiee, elle echouerait "
        "volontairement chaque nuit et noierait les alertes reelles."
    ),
    "replay_events": (
        "Remet `attempts = 0` avant de redispatcher. Planifiee, elle boucle "
        "indefiniment sur un evenement definitivement casse -- un rejeu est une "
        "decision d'exploitation, prise apres diagnostic."
    ),
    # --- Referentiels ---
    "load_chart_of_accounts": _MOTIF_REFERENTIEL,
    "load_metric_dictionary": _MOTIF_REFERENTIEL,
    "load_customization_options": _MOTIF_REFERENTIEL,
    "load_default_journals": _MOTIF_REFERENTIEL,
    "load_default_lost_reasons": _MOTIF_REFERENTIEL,
    "load_default_pipeline": _MOTIF_REFERENTIEL,
    "load_default_product_catalog": _MOTIF_REFERENTIEL,
    "load_epi_standards": _MOTIF_REFERENTIEL,
    "load_material_references": _MOTIF_REFERENTIEL,
    "load_mg_holidays": (
        "Calendrier ferie d'une annee : charge une fois par tenant et par "
        "annee, ou a la creation d'un tenant. Une planification n'aurait "
        "rien a faire onze mois sur douze."
    ),
    "load_payroll_reference_data": _MOTIF_REFERENTIEL,
    "load_pcg2005": _MOTIF_REFERENTIEL,
    "load_roles": _MOTIF_REFERENTIEL,
    "load_sample_products": _MOTIF_AMORCAGE,
    "load_sector_certifications": _MOTIF_REFERENTIEL,
    "load_textile_benchmarks": _MOTIF_REFERENTIEL,
    "load_ticket_type_catalog": _MOTIF_REFERENTIEL,
    # --- Amorcages de demonstration ---
    "seed_accounting": _MOTIF_AMORCAGE,
    "seed_automation_flows": _MOTIF_AMORCAGE,
    "seed_catalog": _MOTIF_AMORCAGE,
    "seed_chat": _MOTIF_AMORCAGE,
    "seed_core": _MOTIF_AMORCAGE,
    "seed_crm": _MOTIF_AMORCAGE,
    "seed_logistics": _MOTIF_AMORCAGE,
    "seed_mrp": _MOTIF_AMORCAGE,
    "seed_partners": _MOTIF_AMORCAGE,
    "seed_patronage": _MOTIF_AMORCAGE,
    "seed_purchase": _MOTIF_AMORCAGE,
    "seed_sales": _MOTIF_AMORCAGE,
    "seed_stocks": _MOTIF_AMORCAGE,
}


def _commands_on_disk() -> set[str]:
    return {
        path.stem for path in APPS_DIR.glob("*/management/commands/*.py") if path.stem != "__init__"
    }


def _scheduled_commands() -> set[str]:
    from apps.core.services.scheduled_commands import list_scheduled_commands

    return {entry.command for entry in list_scheduled_commands()}


def _unclassified(commands: set[str], scheduled: set[str], allowlisted: set[str]) -> set[str]:
    return commands - scheduled - allowlisted


def test_every_management_command_is_either_scheduled_or_motivated() -> None:
    missing = _unclassified(_commands_on_disk(), _scheduled_commands(), set(_ONE_SHOT_COMMANDS))
    assert not missing, (
        "Commande(s) de gestion ni declaree(s) au registre de planification, ni "
        "inscrite(s) comme ponctuelle(s) :\n"
        + "\n".join(f"  - {name}" for name in sorted(missing))
        + "\n\nSi elle est periodique, declarez-la dans le "
        "`services/scheduling_registration.py` de son app ; sinon, ajoutez-la a "
        "`_ONE_SHOT_COMMANDS` avec son motif."
    )


def test_the_allowlist_has_no_obsolete_entry() -> None:
    """Test d'obsolescence : une exception qui survit a la commande qu'elle
    couvrait est une exception que plus personne ne relit."""
    obsolete = set(_ONE_SHOT_COMMANDS) - _commands_on_disk()
    assert not obsolete, "Exception(s) sans commande correspondante, a retirer :\n" + "\n".join(
        f"  - {name}" for name in sorted(obsolete)
    )


def test_no_command_is_both_scheduled_and_declared_one_shot() -> None:
    both = _scheduled_commands() & set(_ONE_SHOT_COMMANDS)
    assert not both, (
        "Commande(s) a la fois planifiee(s) et declaree(s) ponctuelle(s) — le "
        "motif contredit la planification :\n" + "\n".join(f"  - {name}" for name in sorted(both))
    )


def test_every_motive_is_written() -> None:
    empty = [name for name, motive in _ONE_SHOT_COMMANDS.items() if len(motive.strip()) < 20]
    assert not empty, (
        "Exception(s) sans motif utilisable — la liste ne vaut que par ce qui y "
        f"est ecrit : {sorted(empty)}"
    )


def test_the_detector_catches_an_undeclared_command() -> None:
    """Auto-test du detecteur : sans quoi le garde-fou serait un theatre de
    securite (meme discipline que
    `test_module_boundaries.py::test_forbidden_import_is_detected`)."""
    assert _unclassified(
        {"run_something_nobody_declared"}, _scheduled_commands(), set(_ONE_SHOT_COMMANDS)
    ) == {"run_something_nobody_declared"}
