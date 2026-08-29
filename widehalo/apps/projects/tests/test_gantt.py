"""Tests de `services/gantt.py` (PJ2) : calcul CPM (chemin critique) et
rendu SVG.

Le test `test_compute_critical_path_matches_manual_cpm_calculation`
verifie a la main (meme discipline que les autres modules de ce projet,
ex. ACC-IMP/RG-LOG-6) le resultat attendu sur un petit graphe connu :

    A (5j, debute le 2026-01-01) --> B (3j) --\\
                                                --> D (1j)
                                --> C (2j) --/

Calcul manuel (jours calendaires simples, hypothese V1 disclosed dans
`services/gantt.py`) :
    ES(A)=01-01, EF(A)=01-06
    ES(B)=EF(A)=01-06, EF(B)=01-09
    ES(C)=EF(A)=01-06, EF(C)=01-08
    ES(D)=max(EF(B),EF(C))=max(01-09,01-08)=01-09, EF(D)=01-10
    Fin de projet = max(EF sur noeuds de sortie) = EF(D) = 01-10

    LF(D)=01-10 (noeud de sortie), LS(D)=01-10-1j=01-09
    LF(B)=LS(D)=01-09, LS(B)=01-09-3j=01-06
    LF(C)=LS(D)=01-09, LS(C)=01-09-2j=01-07
    LF(A)=min(LS(B),LS(C))=min(01-06,01-07)=01-06, LS(A)=01-06-5j=01-01

    Marge : A=0 (critique), B=0 (critique), C=1j (NON critique), D=0 (critique)
    => chemin critique = A -> B -> D (C a 1 jour de marge)."""

from __future__ import annotations

import datetime as dt

import pytest

from apps.core.tests.utils import use_tenant
from apps.projects.models import PrjTask
from apps.projects.services.dependencies import add_dependency
from apps.projects.services.gantt import compute_critical_path, render_gantt_svg
from apps.projects.services.projects import create_project
from apps.projects.services.tasks import create_task

pytestmark = pytest.mark.django_db


@pytest.fixture
def diamond_project(db):
    from apps.core.tests.factories import TenantFactory

    tenant = TenantFactory()
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet CPM")
        task_a = create_task(
            tenant, project=project, start_date=dt.date(2026, 1, 1), duration_days=5
        )
        task_b = create_task(tenant, project=project, duration_days=3)
        task_c = create_task(tenant, project=project, duration_days=2)
        task_d = create_task(tenant, project=project, duration_days=1)
        add_dependency(task_a, task_b)
        add_dependency(task_a, task_c)
        add_dependency(task_b, task_d)
        add_dependency(task_c, task_d)
    return tenant, project, task_a, task_b, task_c, task_d


def test_compute_critical_path_matches_manual_cpm_calculation(diamond_project) -> None:
    tenant, project, task_a, task_b, task_c, task_d = diamond_project

    with use_tenant(tenant.id):
        critical_ids = compute_critical_path(project)

        assert critical_ids == {task_a.id, task_b.id, task_d.id}

        task_a.refresh_from_db()
        task_b.refresh_from_db()
        task_c.refresh_from_db()
        task_d.refresh_from_db()
        assert task_a.is_critical_path is True
        assert task_b.is_critical_path is True
        assert task_c.is_critical_path is False
        assert task_d.is_critical_path is True


def test_compute_critical_path_empty_project_returns_empty_set() -> None:
    from apps.core.tests.factories import TenantFactory

    tenant = TenantFactory()
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet vide")
        assert compute_critical_path(project) == set()


def test_compute_critical_path_recomputes_after_reset(diamond_project) -> None:
    """Un second appel doit reinitialiser `is_critical_path` a False pour
    les taches qui ne sont plus critiques (pas d'accumulation d'un ancien
    calcul) — ici on prolonge C pour qu'il devienne critique a la place de B."""
    tenant, project, task_a, task_b, task_c, task_d = diamond_project

    with use_tenant(tenant.id):
        compute_critical_path(project)
        task_c.duration_days = 10
        task_c.save(update_fields=["duration_days"])
        critical_ids = compute_critical_path(project)

        task_b.refresh_from_db()
        task_c.refresh_from_db()
        assert task_c.id in critical_ids
        assert task_c.is_critical_path is True
        assert task_b.id not in critical_ids
        assert task_b.is_critical_path is False


def test_render_gantt_svg_contains_expected_elements(diamond_project) -> None:
    tenant, project, task_a, task_b, task_c, task_d = diamond_project

    with use_tenant(tenant.id):
        compute_critical_path(project)
        svg = render_gantt_svg(project)

    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert svg.count("<rect") == 4  # une barre par tache
    assert "gantt-dependency" in svg  # fleches de dependance
    assert "marker-end" in svg
    assert "gantt-task-critical" in svg  # au moins une tache critique mise en evidence
    assert "#e8590c" in svg  # couleur distincte du chemin critique
    assert "#4c6ef5" in svg  # couleur normale (C, non critique) toujours presente


def test_render_gantt_svg_empty_project_renders_placeholder() -> None:
    from apps.core.tests.factories import TenantFactory

    tenant = TenantFactory()
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet sans tache")
        svg = render_gantt_svg(project)

    assert svg.startswith("<svg")
    assert "Aucune tache" in svg


def test_render_gantt_svg_uses_task_type_not_children_hierarchy(diamond_project) -> None:
    """Verifie simplement que le SVG produit reste coherent avec le modele
    unifie epic/tache/jalon (`task_type`) et n'exige pas de champ absent."""
    tenant, project, *_ = diamond_project
    with use_tenant(tenant.id):
        assert PrjTask.TYPE_TASK == "task"
        svg = render_gantt_svg(project)
    assert "data-task-id" in svg
