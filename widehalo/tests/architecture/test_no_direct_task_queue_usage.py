"""Garde-fou bloquant : `django_q` ne doit jamais etre importe en dehors
de `apps/core/tasks.py::enqueue()` — seul point d'appel autorise, pour
permettre une bascule future vers un autre backend (Celery) sans modifier
le reste du code."""

from __future__ import annotations

from pathlib import Path

from tests.architecture._ast_utils import discover_apps, extract_imports, iter_app_python_files

ALLOWED_FILE = "tasks.py"


def test_django_q_is_only_imported_in_core_tasks() -> None:
    violations: list[str] = []
    for app in discover_apps():
        for file in iter_app_python_files(app, exclude_tests=False):
            if file.name == ALLOWED_FILE and app == "core":
                continue
            for record in extract_imports(file):
                if record.module == "django_q" or record.module.startswith("django_q."):
                    violations.append(f"{file}: import de '{record.module}'")
    assert not violations, "django_q importe hors de apps/core/tasks.py :\n" + "\n".join(violations)


def test_enqueue_helper_exists() -> None:
    tasks_path = Path(__file__).resolve().parent.parent.parent / "apps" / "core" / "tasks.py"
    assert tasks_path.exists()
    assert "def enqueue(" in tasks_path.read_text(encoding="utf-8")
