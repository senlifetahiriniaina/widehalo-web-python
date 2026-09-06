"""SAL-6 (L5, reliquat) — la numérotation résiste-t-elle à deux utilisateurs
qui valident au même instant ?

**L'audit citait une preuve qui n'en était pas une.** Il donnait
`accounting/migrations/0005_*` comme « numérotation par trigger DB » : cette
migration est en réalité l'immuabilité fine RG-ACC-2, et **aucune** des dix
migrations à trigger du dépôt ne numérote quoi que ce soit. L'attribution
est intégralement en Python — `apps/core/services/sequences.py`, dix-huit
lignes, un `select_for_update()` dans un `transaction.atomic()`.

**Le point qui rend ce test intéressant plutôt que décoratif.**
`select_for_update()` est combiné à `get_or_create()`, or un
`SELECT … FOR UPDATE` **ne peut pas verrouiller une ligne qui n'existe pas
encore**. La toute première génération pour un triplet (tenant, code,
exercice) n'est donc pas protégée par le verrou : elle l'est par le
`unique_together` du modèle et par la reprise sur `IntegrityError` que
`get_or_create` effectue dans un point de sauvegarde. Deux chemins
différents, deux régimes de protection différents, et un seul des deux
était nommé dans le code. Ce fichier exerce **les deux**.

Il n'existait aucun test de concurrence dans ce dépôt (zéro `threading`,
zéro `ThreadPoolExecutor`) ni aucun test de `sequences.py`. Une facture qui
porte deux fois le même numéro est un défaut comptable irrattrapable après
coup.

**Ce que la barrière apporte, mesuré et pas supposé.** Elle fait entrer les
threads dans la section critique ensemble. J'avais d'abord écrit que sans
elle le test serait vert sans rien prouver — c'est faux, et la
falsification l'a dit : verrou retiré ET barrière retirée, le test rougit
quand même sur cette machine. Ce qu'elle apporte réellement est donc plus
modeste et plus utile : elle rend la course **déterministe** au lieu de la
laisser dépendre de l'ordonnancement des threads, d'une machine plus lente
ou d'un runner CI moins chargé. Un test de concurrence qui ne mord qu'une
fois sur deux est un test qu'on finit par croire quand il est vert.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connection

from apps.core.models.sequence import Sequence
from apps.core.models.tenant import Tenant
from apps.core.services.sequences import next_reference

pytestmark = pytest.mark.django_db(transaction=True)

CONCURRENCY = 8


def _run_concurrently(fn, count: int = CONCURRENCY) -> list:
    """Lance `count` appels de `fn(i)` qui entrent dans la section critique
    au même instant.

    La barrière est le cœur du test : sans elle, huit threads lancés à la
    suite ont toutes les chances de se sérialiser d'eux-mêmes, et le test
    resterait vert même en retirant le verrou — il ne prouverait alors que
    la capacité de Python à appeler une fonction huit fois.

    Chaque thread ferme sa connexion : sous `transaction=True`, chacun
    ouvre la sienne, et une connexion laissée ouverte fait échouer le
    nettoyage de la base entre deux tests."""
    barrier = threading.Barrier(count)

    def worker(index: int):
        try:
            barrier.wait(timeout=30)
            return fn(index)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=count) as pool:
        return [future.result() for future in [pool.submit(worker, i) for i in range(count)]]


@pytest.fixture
def tenant():
    return Tenant.objects.create(code="SAL6", name="Numérotation SARL")


def test_the_very_first_generation_is_race_free(tenant) -> None:
    """**Le cas que le verrou ne couvre pas.** Aucune ligne `Sequence`
    n'existe encore pour ce triplet : les huit transactions font toutes un
    `SELECT … FOR UPDATE` qui ne verrouille rien (on ne verrouille pas une
    ligne absente), puis tentent toutes l'INSERT. Ce qui les départage est
    le `unique_together`, pas le verrou.

    C'est le cas le plus dangereux en exploitation : il se produit au
    premier document de chaque exercice — précisément le moment où
    plusieurs personnes reprennent le travail en même temps."""
    references = _run_concurrently(lambda _i: next_reference(tenant, "FAC", 2026))

    assert len(set(references)) == CONCURRENCY, (
        f"Références en double lors de la toute première génération : {sorted(references)}"
    )
    assert sorted(references) == [f"FAC-2026-{n:04d}" for n in range(1, CONCURRENCY + 1)], (
        f"La séquence saute ou répète des numéros : {sorted(references)}"
    )
    sequence = Sequence.objects.get(tenant=tenant, code="FAC", fiscal_year=2026)
    assert sequence.last_number == CONCURRENCY


def test_subsequent_generations_are_serialised_by_the_lock(tenant) -> None:
    """**Le cas que le verrou couvre.** La ligne existe : c'est ici que
    `select_for_update()` travaille réellement. Sans lui, huit transactions
    liraient toutes `last_number = 5` et écriraient toutes 6 — une mise à
    jour perdue, donc des numéros répétés."""
    Sequence.objects.create(tenant=tenant, code="FAC", fiscal_year=2026, last_number=5)

    references = _run_concurrently(lambda _i: next_reference(tenant, "FAC", 2026))

    assert len(set(references)) == CONCURRENCY, f"Mise à jour perdue : {sorted(references)}"
    assert sorted(references) == [f"FAC-2026-{n:04d}" for n in range(6, 6 + CONCURRENCY)]
    sequence = Sequence.objects.get(tenant=tenant, code="FAC", fiscal_year=2026)
    assert sequence.last_number == 5 + CONCURRENCY


def test_the_counter_is_per_code_and_per_fiscal_year(tenant) -> None:
    """Les deux dimensions du triplet, exercées **en concurrence** et pas
    seulement l'une après l'autre : un verrou trop large (posé sur le
    tenant plutôt que sur le triplet) sérialiserait des compteurs qui n'ont
    rien à voir, et un verrou trop étroit les mélangerait. Ce sont les deux
    dimensions que `post_move` utilise réellement — le préfixe vient du
    JOURNAL et l'exercice de la PÉRIODE."""

    def generate(index: int) -> str:
        # Quatre compteurs distincts, deux appels concurrents sur chacun.
        code = "FAC" if index % 2 == 0 else "AVO"
        year = 2026 if index % 4 < 2 else 2027
        return next_reference(tenant, code, year)

    references = _run_concurrently(generate)

    assert sorted(references) == sorted(
        [
            "FAC-2026-0001",
            "FAC-2026-0002",
            "AVO-2026-0001",
            "AVO-2026-0002",
            "FAC-2027-0001",
            "FAC-2027-0002",
            "AVO-2027-0001",
            "AVO-2027-0002",
        ]
    ), f"Les compteurs se mélangent entre codes ou exercices : {sorted(references)}"


def test_two_tenants_never_share_a_counter(tenant) -> None:
    """Un compteur partagé entre sociétés ferait sauter des numéros dans la
    facturation de chacune — un trou dans une séquence de factures est un
    problème d'administration fiscale, pas un détail esthétique."""
    other = Tenant.objects.create(code="SAL6-B", name="Autre SARL")

    def generate(index: int) -> str:
        return next_reference(tenant if index % 2 == 0 else other, "FAC", 2026)

    references = _run_concurrently(generate)

    assert (
        sorted(references)
        == ["FAC-2026-0001"] * 2
        + ["FAC-2026-0002"] * 2
        + ["FAC-2026-0003"] * 2
        + ["FAC-2026-0004"] * 2
    ), f"Les deux sociétés ne tirent pas leurs numéros de compteurs séparés : {sorted(references)}"
    assert (
        Sequence.objects.get(tenant=tenant, code="FAC", fiscal_year=2026).last_number
        == CONCURRENCY // 2
    )
    assert (
        Sequence.objects.get(tenant=other, code="FAC", fiscal_year=2026).last_number
        == CONCURRENCY // 2
    )
