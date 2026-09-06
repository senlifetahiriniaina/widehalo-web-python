"""S3 — la file de worker dédiée du cahier (§7.6), et son défaut silencieux.

**Ce que le cahier demande repose sur une prémisse fausse ici.** §7.6 :
« Une troisième file de worker est ajoutée, dédiée aux échanges, isolée des
deux existantes. » Il n'y a jamais eu qu'UNE file dans ce dépôt : un seul
`Q_CLUSTER`, un seul service `worker`. La Phase 2 annonçait le
dédoublement, la Phase 3 écrit que « les deux files de worker introduites
en Phase 2 suffisent » — aucune des deux n'a été écrite. La troisième file
est donc la seconde, et c'est dit ici plutôt que passé sous silence.

**Le risque, lui, est réel.** Deux workers en tout (`Q_CLUSTER["workers"]
= 2`) : deux passes de vidange bloquées sur une plateforme fiscale en
difficulté arrêtent toutes les tâches de fond de l'ERP.

**Le défaut que ces tests empêchent.** Le planificateur de Django-Q ne
prend une planification que si son `cluster` correspond au sien. Une
commande liée à `widehalo-flux` alors qu'aucun worker ne porte ce nom n'est
exécutée par personne — et sans la moindre erreur. C'est pourquoi le
réglage est vide par défaut, et pourquoi ce défaut est vérifié plutôt que
supposé.

**Ce fichier vit dans `tests/scheduling/` et non dans `apps/core/tests/`**
parce qu'il importe `django_q.models` pour lire la planification écrite. La
garde `test_no_direct_task_queue_usage.py` interdit cet import partout dans
`apps/` sauf dans `apps/core/tasks.py`, et elle a refusé ce fichier au
premier jet — correctement. `tests/scheduling/test_schedule_registry.py`
avait déjà rencontré la même contrainte et y a répondu de la même manière :
sortir du périmètre plutôt qu'élargir l'exception.
"""

from __future__ import annotations

import pytest
from apps.core.services.scheduled_commands import (
    FREQUENCY_DAILY,
    list_scheduled_commands,
    register_scheduled_command,
)
from apps.core.tasks import sync_schedules
from django.conf import settings
from django.test import override_settings

pytestmark = pytest.mark.django_db


def test_the_dedicated_cluster_is_off_by_default() -> None:
    """Le défaut sûr. Une isolation activée sans le worker correspondant
    transformerait la file de sortie en trou noir : les échanges
    s'accumuleraient, aucune erreur n'apparaîtrait, et personne ne
    saurait avant qu'un client ne demande où est sa facture."""
    assert settings.FLOWS_QUEUE_CLUSTER_NAME == "", (
        "La file dédiée est activée par défaut. Elle ne doit l'être que sur un "
        "déploiement qui fait tourner le service `worker-flux` : sinon la commande "
        "de vidange n'est exécutée par personne, en silence."
    )


def test_an_unassigned_command_keeps_a_null_cluster() -> None:
    """`None`, pas la chaîne vide, et la nuance est structurante : le
    planificateur du cluster par défaut prend les planifications
    `cluster__isnull=True`. Une chaîne vide ne satisferait pas ce filtre,
    et TOUTES les commandes périodiques du dépôt cesseraient de
    s'exécuter."""
    from django_q.models import Schedule

    sync_schedules()
    ligne = Schedule.objects.get(name="widehalo:core.tenant_backups")
    assert ligne.cluster is None, (
        f"Cluster {ligne.cluster!r} au lieu de NULL : le planificateur par défaut "
        "filtre sur `cluster__isnull=True` et cesserait de prendre cette commande."
    )


def test_a_command_bound_to_a_cluster_carries_it_to_the_schedule() -> None:
    """L'amorçage : sans adhérence entre le registre et la planification,
    le champ `cluster` serait écrit dans un dataclass que personne ne lit,
    et l'isolation ne serait qu'une intention."""
    from django_q.models import Schedule

    register_scheduled_command(
        "core.essai_cluster_dedie",
        command="check_quant_consistency",
        module="core",
        label="Essai de routage",
        frequency=FREQUENCY_DAILY,
        cluster="widehalo-flux",
    )
    try:
        sync_schedules()
        ligne = Schedule.objects.get(name="widehalo:core.essai_cluster_dedie")
        assert ligne.cluster == "widehalo-flux"
    finally:
        from apps.core.services.scheduled_commands import _SCHEDULE_REGISTRY

        _SCHEDULE_REGISTRY.pop("core.essai_cluster_dedie", None)
        Schedule.objects.filter(name="widehalo:core.essai_cluster_dedie").delete()


def test_the_flows_queue_follows_the_setting() -> None:
    """Le réglage n'est pas décoratif : c'est lui qui décide, et la
    déclaration le relit à chaque enregistrement."""
    from apps.flows.services.scheduling_registration import register_scheduled_commands

    with override_settings(FLOWS_QUEUE_CLUSTER_NAME="widehalo-flux"):
        register_scheduled_commands()
        entree = next(c for c in list_scheduled_commands() if c.code == "flows.outbound_queue")
        assert entree.cluster == "widehalo-flux"

    # Et on rend le registre à son état d'origine — c'est un global de
    # processus, le même piège qu'un budget de rapports ordre-dépendant.
    register_scheduled_commands()
    entree = next(c for c in list_scheduled_commands() if c.code == "flows.outbound_queue")
    assert entree.cluster == ""
