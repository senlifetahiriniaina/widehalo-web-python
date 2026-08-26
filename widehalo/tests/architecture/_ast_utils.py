"""Utilitaires d'analyse AST partages par les tests d'architecture.

Limite assumee (documentee dans le cahier des charges) : analyse statique
uniquement, pas de resolution des imports dynamiques (`importlib.import_module`
avec chaine calculee). Suffisant pour un monolithe discipline ecrit par un
seul developpeur.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

APPS_DIR = Path(__file__).resolve().parent.parent.parent / "apps"


@dataclass(frozen=True)
class ImportRecord:
    module: str
    file: Path


def discover_apps() -> list[str]:
    return sorted(
        p.name
        for p in APPS_DIR.iterdir()
        if p.is_dir() and (p / "apps.py").exists() and not p.name.startswith("__")
    )


def iter_app_python_files(app_name: str, *, exclude_tests: bool = True) -> list[Path]:
    app_dir = APPS_DIR / app_name
    files = []
    for path in app_dir.rglob("*.py"):
        if exclude_tests and ("/tests/" in str(path) or path.name.startswith("test_")):
            continue
        if "/migrations/" in str(path):
            continue
        files.append(path)
    return files


def extract_imports(path: Path) -> list[ImportRecord]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    records = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                records.append(ImportRecord(module=alias.name, file=path))
        elif isinstance(node, ast.ImportFrom) and node.module:
            records.append(ImportRecord(module=node.module, file=path))
    return records
