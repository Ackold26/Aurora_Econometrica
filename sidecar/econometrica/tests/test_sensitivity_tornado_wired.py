"""P0.5 шаг 10-11: торнадо чувствительности подключён, не просто написан.

Корень. `engines/sensitivity.py` (673 строки) и `SensitivityTornado.svelte`
(323 строки) существовали с ноля вызывающих на каждой стороне — тот же класс
дефекта, что раньше давал в продукте сертификат и торнадо-график, которые
никто не звал. Обход дерева здесь не обходной путь ради теста — он ровно
воспроизводит зонд «вызывающих больше нуля», который и вскрыл дыру.
"""
from __future__ import annotations

import ast
from pathlib import Path

MODELER_PY = Path(__file__).parent.parent / 'engines' / 'modeler.py'


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding='utf-8'), filename=str(path))


def _calls_named(tree: ast.Module, name: str) -> list[ast.Call]:
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == name:
            out.append(node)
        elif isinstance(func, ast.Attribute) and func.attr == name:
            out.append(node)
    return out


def test_compute_sensitivity_tornado_is_called_from_modeler():
    """Движок больше не сирота: modeler.py действительно его зовёт."""
    tree = _parse(MODELER_PY)
    calls = _calls_named(tree, 'compute_sensitivity_tornado')
    assert calls, (
        'compute_sensitivity_tornado не вызывается из modeler.py – торнадо '
        'снова стал написанным, но неподключённым кодом (673 строки без '
        'единого вызывающего).'
    )


def test_sensitivity_tornado_written_into_diagnostics():
    """Результат кладётся в diagnostics['sensitivity_tornado'], не теряется локально."""
    tree = _parse(MODELER_PY)
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        if not (isinstance(node.value, ast.Name) and node.value.id == 'diagnostics'):
            continue
        sl = node.slice
        if hasattr(ast, 'Index') and isinstance(sl, ast.Index):  # py<3.9 shim
            sl = sl.value
        if isinstance(sl, ast.Constant) and sl.value == 'sensitivity_tornado':
            hits.append(node.lineno)
    assert hits, (
        "diagnostics['sensitivity_tornado'] не присваивается в modeler.py – "
        'результат посчитан, но не доедет до model-diagnostics.json (SSOT '
        'диагностики для чтения — server.py + фронт), значит клиент его не увидит.'
    )
