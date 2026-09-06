"""S3 — le compteur d'échecs consécutifs sous accès concurrent.

**Pourquoi ce test existe.** `services/incidents.py` incrémente
`occurrence_count` par `F()` et sa docstring dit pourquoi : deux workers qui
échouent au même instant liraient tous deux la même valeur et écriraient
tous deux la suivante, perdant une occurrence par collision. Le premier jet
de `record_call_failure` faisait exactement ce que cette docstring
condamne — lecture, incrément en mémoire, écriture — sur le compteur qui
porte le critère FLX-3.

La conséquence n'est pas cosmétique. Le compteur sous-estime d'autant plus
que les collisions sont nombreuses, c'est-à-dire quand la panne est massive
et que plusieurs passes de vidange échouent en parallèle : **le disjoncteur
s'ouvrirait le plus tard au moment où il sert le plus.**

Deuxième test de concurrence du dépôt — le premier est
`apps/core/tests/test_sal6_sequence_concurrency.py`, dont ce fichier reprend
le patron : `transaction=True`, une barrière pour que les fils partent
ensemble, et `connection.close()` dans le `finally` de chaque fil (sans
quoi les connexions restent ouvertes et la destruction de la base de test
se bloque).
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connection

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.flows.models import FlwIncident, FlwLink
from apps.flows.services.queue import record_call_failure
from apps.flows.tests.factories import FlwConnectorFactory, FlwLinkFactory

pytestmark = pytest.mark.django_db(transaction=True)

CONCURRENCE = 8


def test_concurrent_failures_lose_no_count_and_open_the_breaker_once() -> None:
    """Huit échecs simultanés sur une même liaison.

    Trois choses vérifiées ensemble, parce qu'elles se tiennent :
    le compteur vaut exactement huit (aucun incrément perdu), le
    disjoncteur est ouvert (le seuil de trois est franchi), et il n'y a
    qu'**un seul** incident — c'est FLX-3 sous la seule condition qui le
    met vraiment à l'épreuve."""
    tenant = Tenant.objects.create(code="S3-CONC", name="Flux concurrent SARL")
    with use_tenant(tenant.id):
        connector = FlwConnectorFactory(tenant=tenant, code="dgi")
        link = FlwLinkFactory(
            tenant=tenant,
            connector=connector,
            state=FlwLink.STATE_ACTIVE,
            breaker_threshold=3,
        )

    barriere = threading.Barrier(CONCURRENCE)
    erreurs: list[BaseException] = []

    def echouer() -> None:
        try:
            with use_tenant(tenant.id):
                # Chaque fil relit SA propre instance : deux fils qui
                # partageraient l'objet Python ne prouveraient rien de la
                # concurrence en base.
                sien = FlwLink.objects.get(pk=link.pk)
                barriere.wait(timeout=30)
                record_call_failure(sien, family=FlwIncident.FAMILY_UNAVAILABLE)
        except BaseException as exc:  # noqa: BLE001 - collecté puis relevé dans le fil principal
            erreurs.append(exc)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=CONCURRENCE) as pool:
        for future in [pool.submit(echouer) for _ in range(CONCURRENCE)]:
            future.result()

    assert not erreurs, f"Échecs dans les fils : {erreurs!r}"

    # Toute relecture reste DANS le contexte tenant : la sécurité au niveau
    # des lignes est active sur `flw_link`, et hors contexte la ligne
    # n'existe tout simplement pas — `DoesNotExist`, sans que le message ne
    # nomme la cause. Même piège que les sous-factories sans
    # `SelfAttribute("..tenant")`, documenté dans `tests/factories.py`.
    with use_tenant(tenant.id):
        link.refresh_from_db()
        assert link.consecutive_failures == CONCURRENCE, (
            f"{link.consecutive_failures} échecs comptés sur {CONCURRENCE} réels : des "
            "incréments ont été perdus par collision, et le disjoncteur s'ouvrira "
            "d'autant plus tard que la panne est massive."
        )
        assert link.breaker_state == FlwLink.BREAKER_OPEN

        incidents = FlwIncident.objects.filter(link=link)
        assert incidents.count() == 1, (
            f"{incidents.count()} incidents pour une seule panne : « un incident "
            "unique » ne tient pas sous accès concurrent."
        )
        assert incidents.get().occurrence_count == CONCURRENCE
