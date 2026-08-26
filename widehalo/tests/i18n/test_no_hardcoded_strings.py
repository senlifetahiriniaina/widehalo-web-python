"""Garde-fou i18n : detecte les chaines "phrase" (plusieurs mots) passees
en argument de JsonResponse/ValidationError/ValueError dans les fichiers
API/vues/services du socle, sans etre enveloppees par gettext (`_`,
`gettext`, `gettext_lazy`).

Limite assumee : analyse AST simple, ne couvre que les appels directs a
un nombre restreint de fonctions "sensibles" (celles qui produisent des
messages utilisateur) dans apps/*/api*.py, apps/*/views.py et
apps/*/services/*.py — pas une detection exhaustive de toute chaine en
dur du projet (ce serait trop de faux positifs sur les cles techniques,
noms de champs, etc.).
"""

from __future__ import annotations

import ast
from pathlib import Path

APPS_DIR = Path(__file__).resolve().parent.parent.parent / "apps"

MESSAGE_PRODUCING_CALLS = {"ValidationError", "ValueError"}
GETTEXT_NAMES = {"_", "gettext", "gettext_lazy", "ngettext", "ngettext_lazy"}


def _is_translated(node: ast.expr) -> bool:
    return isinstance(node, ast.Call) and (
        (isinstance(node.func, ast.Name) and node.func.id in GETTEXT_NAMES)
        or (isinstance(node.func, ast.Attribute) and node.func.attr in GETTEXT_NAMES)
    )


def _looks_like_sentence(value: str) -> bool:
    return len(value.split()) >= 3 and value[0].isalpha()


def _iter_target_files() -> list[Path]:
    files = []
    for pattern in ("api*.py", "views.py"):
        files.extend(APPS_DIR.glob(f"*/{pattern}"))
    for services_dir in APPS_DIR.glob("*/services"):
        files.extend(services_dir.glob("*.py"))
    return [f for f in files if "/tests/" not in str(f) and f.name != "public.py"]


def _find_untranslated_messages(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name in MESSAGE_PRODUCING_CALLS and node.args:
                first_arg = node.args[0]
                if (
                    isinstance(first_arg, ast.Constant)
                    and isinstance(first_arg.value, str)
                    and _looks_like_sentence(first_arg.value)
                    and not _is_translated(first_arg)
                ):
                    violations.append(f"{path}:{node.lineno}: {func_name}({first_arg.value!r})")
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=False):
                if (
                    isinstance(key, ast.Constant)
                    and key.value in {"detail", "message"}
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and _looks_like_sentence(value.value)
                ):
                    violations.append(f"{path}:{value.lineno}: {{'{key.value}': {value.value!r}}}")
    return violations


def test_no_hardcoded_user_facing_messages() -> None:
    violations: list[str] = []
    for path in _iter_target_files():
        violations.extend(_find_untranslated_messages(path))
    assert not violations, "Messages utilisateur non traduits (gettext manquant) :\n" + "\n".join(
        violations
    )


def test_detects_a_hardcoded_message_when_present(tmp_path) -> None:
    sample = tmp_path / "views.py"
    sample.write_text(
        'def f(request):\n    return {"detail": "ceci est un message en dur"}\n',
        encoding="utf-8",
    )
    violations = _find_untranslated_messages(sample)
    assert violations, "Le detecteur doit repérer un message litteral non traduit"
