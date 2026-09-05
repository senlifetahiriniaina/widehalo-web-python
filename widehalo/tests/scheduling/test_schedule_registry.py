"""L0-3 — la planification devient une donnée déclarée.

Aucun ordonnanceur n'existait dans ce dépôt : ni crontab, ni unité systemd,
ni service dans `docker-compose.prod.yml`, ni objet `Schedule` django-q2.
Dix-neuf commandes se déclarent pourtant périodiques dans leur propre
docstring, et le document de déploiement n'en nommait que trois.

Ces tests couvrent les deux moitiés du mécanisme : le registre, qui déclare,
et `apps.core.tasks.sync_schedules`, qui écrit. Le second est le seul endroit
du dépôt autorisé à importer `django_q` — ce fichier de test l'importe aussi,
pour vérifier ce qui est réellement écrit en base ; la garde
`tests/architecture/test_no_direct_task_queue_usage.py` ne scanne que
`apps/`, et vérifier l'adaptateur sans regarder derrière lui ne prouverait
rien.
"""

from __future__ import annotations

import pytest
from apps.core.services.scheduled_commands import (
    FREQUENCY_CHOICES,
    FREQUENCY_DAILY,
    get_scheduled_command,
    list_scheduled_commands,
    register_scheduled_command,
)
from apps.core.tasks import _SCHEDULE_NAME_PREFIX, run_scheduled_command, sync_schedules
from django.core.management import call_command, get_commands
from django_q.models import Schedule

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# Le registre
# --------------------------------------------------------------------------


def test_registry_is_populated_by_app_ready() -> None:
    """Le registre est peuplé par les `ready()` des apps, pas par ce test.

    Un registre vide signifierait qu'aucun `ready()` n'appelle son
    `register_scheduled_commands()` — le défaut exact que L0-3 corrige, et
    qui laisserait l'ordonnanceur sans rien à planifier."""
    entries = list_scheduled_commands()
    assert len(entries) >= 19, f"Registre incomplet : {len(entries)} commande(s) déclarée(s)."


def test_every_declared_command_actually_exists() -> None:
    """Une commande déclarée mais absente ne se découvrirait qu'à 2 h du matin,
    dans les journaux du worker."""
    available = set(get_commands())
    missing = [
        f"{entry.code} → {entry.command}"
        for entry in list_scheduled_commands()
        if entry.command not in available
    ]
    assert not missing, "Commandes déclarées mais introuvables :\n" + "\n".join(missing)


def test_declarations_are_consistent() -> None:
    seen_commands: dict[str, str] = {}
    for entry in list_scheduled_commands():
        assert entry.frequency in FREQUENCY_CHOICES, f"{entry.code} : cadence {entry.frequency!r}."
        assert 0 <= entry.hour <= 23, f"{entry.code} : heure {entry.hour!r}."
        assert entry.label, f"{entry.code} : libellé manquant."
        # Une commande planifiée deux fois tournerait deux fois par nuit —
        # le doublon que L0-1 vient précisément d'éliminer côté effets.
        assert entry.command not in seen_commands, (
            f"{entry.command} déclarée deux fois : {seen_commands.get(entry.command)} "
            f"et {entry.code}."
        )
        seen_commands[entry.command] = entry.code


def test_the_two_commands_that_must_never_be_scheduled_are_absent() -> None:
    """`check_regulatory_validation` lève un `CommandError` par conception —
    c'est un verrou de déploiement, un run récurrent échouerait volontairement
    chaque nuit. `replay_events` remet `attempts = 0` avant de redispatcher :
    planifiée, elle boucle indéfiniment sur un évènement définitivement
    cassé."""
    declared = {entry.command for entry in list_scheduled_commands()}
    assert "check_regulatory_validation" not in declared
    assert "replay_events" not in declared


def test_registration_refuses_an_unknown_frequency() -> None:
    with pytest.raises(ValueError):
        register_scheduled_command(
            "test.invalid_frequency",
            command="load_roles",
            module="core",
            label="Test",
            frequency="fortnightly",
        )
    assert get_scheduled_command("test.invalid_frequency") is None


def test_registration_refuses_an_impossible_hour() -> None:
    with pytest.raises(ValueError):
        register_scheduled_command(
            "test.invalid_hour",
            command="load_roles",
            module="core",
            label="Test",
            frequency=FREQUENCY_DAILY,
            hour=25,
        )
    assert get_scheduled_command("test.invalid_hour") is None


# --------------------------------------------------------------------------
# La synchronisation
# --------------------------------------------------------------------------


def test_sync_creates_one_schedule_per_declaration() -> None:
    result = sync_schedules()
    entries = list_scheduled_commands()

    assert result["created"] == len(entries)
    assert Schedule.objects.filter(name__startswith=_SCHEDULE_NAME_PREFIX).count() == len(entries)

    schedule = Schedule.objects.get(name=f"{_SCHEDULE_NAME_PREFIX}{entries[0].code}")
    # Le nom de la commande n'est jamais figé dans l'objet `Schedule` : la
    # planification porte un code, le registre porte la définition. Une
    # commande retirée du registre cesse d'être exécutée même si sa
    # planification survit en base.
    assert schedule.func == "apps.core.tasks.run_scheduled_command"
    assert entries[0].code in schedule.args
    assert schedule.repeats == -1


def test_sync_is_idempotent() -> None:
    """Deux exécutions consécutives, une seule planification par commande.

    Le déploiement rejoue cette commande à chaque livraison ; si elle
    dupliquait, chaque livraison ajouterait un passage nocturne de plus."""
    first = sync_schedules()
    second = sync_schedules()

    assert second["created"] == 0
    assert second["updated"] == first["created"]
    assert Schedule.objects.filter(name__startswith=_SCHEDULE_NAME_PREFIX).count() == len(
        list_scheduled_commands()
    )


def test_sync_deletes_an_orphaned_schedule_but_spares_a_hand_made_one() -> None:
    """Le registre est la source de vérité pour ce qu'il possède, et rien
    d'autre : une planification créée à la main par un exploitant ne porte pas
    le préfixe et ne doit jamais être emportée."""
    sync_schedules()
    orphan = Schedule.objects.create(
        name=f"{_SCHEDULE_NAME_PREFIX}module.commande_supprimee",
        func="apps.core.tasks.run_scheduled_command",
        args=repr(("module.commande_supprimee",)),
        schedule_type=Schedule.DAILY,
        repeats=-1,
    )
    hand_made = Schedule.objects.create(
        name="maintenance-ponctuelle-exploitant",
        func="apps.core.tasks.run_scheduled_command",
        args=repr(("core.tenant_backups",)),
        schedule_type=Schedule.DAILY,
        repeats=-1,
    )

    result = sync_schedules()

    assert result["deleted"] == 1
    assert not Schedule.objects.filter(pk=orphan.pk).exists()
    assert Schedule.objects.filter(pk=hand_made.pk).exists()


def test_next_run_is_set_at_the_declared_hour() -> None:
    sync_schedules()
    entry = get_scheduled_command("core.tenant_backups")
    assert entry is not None
    schedule = Schedule.objects.get(name=f"{_SCHEDULE_NAME_PREFIX}{entry.code}")
    assert schedule.next_run is not None
    from django.utils import timezone

    assert timezone.localtime(schedule.next_run).hour == entry.hour


# --------------------------------------------------------------------------
# Le point d'entrée d'exécution
# --------------------------------------------------------------------------


def test_run_scheduled_command_invokes_the_registered_command(monkeypatch) -> None:
    called: list[str] = []
    monkeypatch.setattr(
        "django.core.management.call_command",
        lambda name, *args, **kwargs: called.append(name),
    )
    run_scheduled_command("core.purge_expired_sandboxes")
    assert called == ["purge_expired_sandboxes"]


def test_run_scheduled_command_ignores_a_code_no_longer_registered(caplog) -> None:
    """Une planification orpheline peut survivre entre le déploiement du code
    et la synchronisation : elle doit être ignorée avec un avertissement, pas
    faire échouer le worker."""
    with caplog.at_level("WARNING"):
        run_scheduled_command("module.disparu")
    assert "module.disparu" in caplog.text


# --------------------------------------------------------------------------
# La commande de déploiement
# --------------------------------------------------------------------------


def test_deployment_command_synchronises_and_reports(capsys) -> None:
    call_command("sync_scheduled_commands")
    out = capsys.readouterr().out
    assert f"{len(list_scheduled_commands())} commande(s) périodique(s)" in out
    assert Schedule.objects.filter(name__startswith=_SCHEDULE_NAME_PREFIX).exists()


def test_deployment_command_list_writes_nothing(capsys) -> None:
    call_command("sync_scheduled_commands", "--list")
    out = capsys.readouterr().out
    assert "core.tenant_backups" in out
    assert not Schedule.objects.filter(name__startswith=_SCHEDULE_NAME_PREFIX).exists()
