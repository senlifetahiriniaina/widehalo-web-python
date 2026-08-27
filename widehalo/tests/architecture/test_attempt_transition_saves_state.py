"""Garde-fou bloquant contre la regression reelle rencontree dans le module
`mrp` : `apps.core.services.workflow.attempt_transition()` modifie le champ
FSM sur l'objet Python en memoire mais n'appelle JAMAIS `.save()` lui-meme —
chaque fonction de service appelante DOIT explicitement rappeler
`instance.save(update_fields=[...])` (en incluant le champ d'etat) juste
apres, sous peine de voir la transition disparaitre silencieusement des que
l'objet est recharge depuis la base (seul un test de bout en bout avec deux
requetes HTTP separees, chacune rechargeant l'objet, l'avait detectee —
jamais un test unitaire reutilisant le meme objet Python entre deux appels).

Meme patron (scan AST simple de `apps/*/services/*.py`) que
`tests/i18n/test_no_hardcoded_strings.py`.

Limite assumee : analyse AST + introspection du modele Django (pas d'acces
BDD requis, juste le registre d'apps deja charge par pytest-django) pour
resoudre le nom du champ FSM depuis l'annotation de type du parametre
transitionne. Ne couvre que le cas — le seul rencontre dans ce depot — ou le
premier argument de `attempt_transition(...)` est une simple reference
locale (parametre de fonction) annotee avec un modele concret ; un appel
dont le premier argument n'est pas une reference simple, ou dont le
parametre n'est pas annote, est considere comme une violation par prudence
(mieux vaut un faux positif qui force une revue manuelle qu'un faux
negatif silencieux comme le bug reel)."""

from __future__ import annotations

import ast
from pathlib import Path

from django.apps import apps as django_apps
from django_fsm import FSMField

APPS_DIR = Path(__file__).resolve().parent.parent.parent / "apps"


def _iter_service_files() -> list[Path]:
    files = []
    for services_dir in APPS_DIR.glob("*/services"):
        files.extend(services_dir.glob("*.py"))
    return [f for f in files if "/tests/" not in str(f) and f.name != "public.py"]


def _app_label(path: Path) -> str:
    # apps/<app>/services/<file>.py
    return path.parent.parent.name


def _fsm_field_name(app_label: str, model_name: str | None) -> str | None:
    if not model_name:
        return None
    try:
        model = django_apps.get_model(app_label, model_name)
    except LookupError:
        return None
    for field in model._meta.get_fields():
        if isinstance(field, FSMField):
            return field.name
    return None


def _param_annotation_name(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return None


def _ordered_calls(func: ast.AST) -> list[ast.Call]:
    calls = [n for n in ast.walk(func) if isinstance(n, ast.Call)]
    return sorted(calls, key=lambda n: (n.lineno, n.col_offset))


def _is_attempt_transition_call(call: ast.Call) -> bool:
    if isinstance(call.func, ast.Name):
        return call.func.id == "attempt_transition"
    if isinstance(call.func, ast.Attribute):
        return call.func.attr == "attempt_transition"
    return False


def _save_call_target(call: ast.Call) -> str | None:
    """Retourne le nom de variable sur laquelle `.save(...)` est appele, ou
    None si ce n'est pas un appel `.save()` sur une reference simple."""
    if (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "save"
        and isinstance(call.func.value, ast.Name)
    ):
        return call.func.value.id
    return None


def _save_persists_field(call: ast.Call, field_name: str | None) -> bool:
    """Un `.save()` sans `update_fields` persiste tout (suffisant). Un
    `.save(update_fields=[...])` doit explicitement inclure le champ FSM."""
    update_fields_kw = next((kw for kw in call.keywords if kw.arg == "update_fields"), None)
    if update_fields_kw is None:
        return True
    if field_name is None:
        return False
    if isinstance(update_fields_kw.value, (ast.List, ast.Tuple)):
        names = [
            elt.value
            for elt in update_fields_kw.value.elts
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        ]
        return field_name in names
    # update_fields calcule dynamiquement (pas une liste litterale) : on ne
    # peut pas prouver que le champ y figure, on considere donc que ce n'est
    # pas une preuve suffisante.
    return False


def _find_violations_in_function(func: ast.AST, app_label: str, file_path: Path) -> list[str]:
    param_types: dict[str, str | None] = {}
    args = getattr(func, "args", None)
    if args is not None:
        for arg in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
            param_types[arg.arg] = _param_annotation_name(arg.annotation)

    violations: list[str] = []
    calls = _ordered_calls(func)
    for idx, call in enumerate(calls):
        if not _is_attempt_transition_call(call):
            continue
        if len(call.args) < 2:
            continue  # appel malforme, hors perimetre de cette analyse
        instance_arg = call.args[0]
        var_name = instance_arg.id if isinstance(instance_arg, ast.Name) else None
        model_name = param_types.get(var_name) if var_name else None
        field_name = _fsm_field_name(app_label, model_name)

        found_save = False
        if var_name is not None:
            for later_call in calls[idx:]:
                if later_call is call:
                    continue
                if _save_call_target(later_call) == var_name and _save_persists_field(
                    later_call, field_name
                ):
                    found_save = True
                    break

        if not found_save:
            violations.append(
                f"{file_path}:{call.lineno}: attempt_transition(...) sans "
                ".save(update_fields=[...]) incluant le champ FSM (ou .save() "
                "nu) dans la meme fonction — la transition ne sera jamais "
                "persistee (regression du bug mrp reel : etat perdu au "
                "rechargement depuis la base)."
            )
    return violations


def _find_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    app_label = _app_label(path)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            violations.extend(_find_violations_in_function(node, app_label, path))
    return violations


def test_attempt_transition_always_followed_by_state_save() -> None:
    violations: list[str] = []
    for path in _iter_service_files():
        violations.extend(_find_violations(path))
    assert not violations, (
        "attempt_transition() sans sauvegarde de l'etat qui suit (bug reel "
        "deja rencontre dans mrp) :\n" + "\n".join(violations)
    )


def test_detects_a_missing_save_after_attempt_transition(tmp_path) -> None:
    services_dir = tmp_path / "apps" / "mrp" / "services"
    services_dir.mkdir(parents=True)
    sample = services_dir / "sample.py"
    sample.write_text(
        "from apps.core.services.workflow import attempt_transition\n"
        "from apps.mrp.models import MrpOrder\n\n\n"
        "def confirm_order(order: MrpOrder, user) -> MrpOrder:\n"
        "    attempt_transition(order, 'confirm', user)\n"
        "    return order\n",
        encoding="utf-8",
    )
    violations = _find_violations(sample)
    assert violations, "Le detecteur doit reperer un attempt_transition() sans .save() qui suit"


def test_does_not_flag_a_correct_save_with_update_fields(tmp_path) -> None:
    services_dir = tmp_path / "apps" / "mrp" / "services"
    services_dir.mkdir(parents=True)
    sample = services_dir / "sample.py"
    sample.write_text(
        "from apps.core.services.workflow import attempt_transition\n"
        "from apps.mrp.models import MrpOrder\n\n\n"
        "def confirm_order(order: MrpOrder, user) -> MrpOrder:\n"
        "    attempt_transition(order, 'confirm', user)\n"
        "    order.save(update_fields=['state'])\n"
        "    return order\n",
        encoding="utf-8",
    )
    violations = _find_violations(sample)
    assert not violations, "Un .save(update_fields=['state']) correct ne doit pas etre signale"


def test_does_not_flag_a_bare_save(tmp_path) -> None:
    services_dir = tmp_path / "apps" / "mrp" / "services"
    services_dir.mkdir(parents=True)
    sample = services_dir / "sample.py"
    sample.write_text(
        "from apps.core.services.workflow import attempt_transition\n"
        "from apps.mrp.models import MrpOrder\n\n\n"
        "def confirm_order(order: MrpOrder, user) -> MrpOrder:\n"
        "    attempt_transition(order, 'confirm', user)\n"
        "    order.save()\n"
        "    return order\n",
        encoding="utf-8",
    )
    violations = _find_violations(sample)
    assert not violations, "Un .save() nu (persiste tout) ne doit pas etre signale"


def test_flags_save_with_update_fields_missing_the_state_field(tmp_path) -> None:
    services_dir = tmp_path / "apps" / "mrp" / "services"
    services_dir.mkdir(parents=True)
    sample = services_dir / "sample.py"
    sample.write_text(
        "from apps.core.services.workflow import attempt_transition\n"
        "from apps.mrp.models import MrpOrder\n\n\n"
        "def confirm_order(order: MrpOrder, user) -> MrpOrder:\n"
        "    attempt_transition(order, 'confirm', user)\n"
        "    order.save(update_fields=['qty_produced'])\n"
        "    return order\n",
        encoding="utf-8",
    )
    violations = _find_violations(sample)
    assert violations, (
        "Un .save(update_fields=[...]) qui n'inclut pas le champ FSM ne "
        "persiste pas la transition et doit etre signale"
    )
