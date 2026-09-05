"""L0-2 — un tenant en échec ne prive jamais les suivants de leur traitement.

Une seule des dix-neuf commandes périodiques isolait les erreurs par tenant
(`run_analytics_refresh`) ; les dix-huit autres laissaient l'exception
remonter et **interrompaient la boucle**. Un seul tenant mal configuré
annulait donc le traitement de tous ceux qui le suivaient dans l'ordre de la
table.

Le défaut était invisible tant que rien n'ordonnançait ces commandes. Il
devient une panne silencieuse le jour où elles tournent chaque nuit — et la
plus coûteuse serait la sauvegarde, dont l'absence ne se découvre que le jour
où l'on en a besoin.
"""

from __future__ import annotations

import pytest
from apps.core.services.scheduled_commands import tenant_step
from apps.core.tests.factories import TenantFactory
from django.core.management.base import BaseCommand

pytestmark = pytest.mark.django_db


class _RecordingCommand(BaseCommand):
    """Commande minimale : capture ce qui est écrit plutôt que de l'afficher."""

    def __init__(self) -> None:
        super().__init__()
        self.written: list[str] = []
        self.stdout = self  # type: ignore[assignment]

    def write(self, message: str, *args: object, **kwargs: object) -> None:
        self.written.append(str(message))


def test_a_failing_tenant_does_not_stop_the_loop() -> None:
    command = _RecordingCommand()
    tenants = [TenantFactory(), TenantFactory(), TenantFactory()]
    processed: list[str] = []

    for index, tenant in enumerate(tenants):
        with tenant_step(command, tenant):
            if index == 0:
                raise RuntimeError("configuration comptable absente")
            processed.append(tenant.code)

    # Les deux tenants suivants sont traites malgre l'echec du premier.
    assert processed == [tenants[1].code, tenants[2].code]


def test_the_failure_is_reported_rather_than_swallowed_silently() -> None:
    """Absorber n'est pas masquer : l'echec est ecrit, tenant par tenant."""
    command = _RecordingCommand()
    tenant = TenantFactory()

    with tenant_step(command, tenant):
        raise RuntimeError("configuration comptable absente")

    assert any(tenant.code in line for line in command.written)
    assert any("configuration comptable absente" in line for line in command.written)


def test_a_successful_step_writes_nothing() -> None:
    command = _RecordingCommand()
    with tenant_step(command, TenantFactory()):
        pass
    assert command.written == []
