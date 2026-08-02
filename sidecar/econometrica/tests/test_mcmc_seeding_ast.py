"""Сторож воспроизводимости MCMC (P0.2) – проверка обходом дерева, без PyMC.

Зачем нужен именно AST-разбор, а не импорт движка и не прогон обучения:
тест обязан жить в CI, где PyMC не установлен (тяжёлая зависимость, дорогой
образ). Импортировать ``engines.modeler`` или ``pm.sample`` напрямую нельзя –
любой такой импорт тянет за собой pymc/pytensor и падает уже на уровне
``import``, а не на проверяемом инварианте. Поэтому здесь – только
``ast`` + stdlib: файлы читаются как текст, разбираются в дерево синтаксиса,
инварианты проверяются по форме кода.

Что стережём (P0.2, ``utils/seeding.py``):

1. Каждый вызов ``pm.sample(...)`` в ``engines/modeler.py`` несёт именованный
   аргумент ``random_seed`` – иначе два обучения на одних данных дают разные
   апостериорные интервалы, и клиент видит "поехавшие" цифры при повторном
   расчёте (регресс P0.2).
2. Вызовов ``pm.sample`` найдено не меньше трёх (Tier-1 NumPyro, Tier-2
   PyTensor с колбэком, Tier-2 без колбэка на старых версиях PyMC) – если
   обход дерева вдруг находит ноль, это тест сломан (модуль переехал, идиому
   вызова сменили), а не "всё обучение исчезло и стеречь нечего".
3. В движке (``engines/**.py``, ``utils/**.py``) нет ни одного вызова
   глобального засева ``np.random.seed(...)`` / ``numpy.random.seed(...)``.
   Явный ``random_seed=`` в ``pm.sample`` – единственный канал засева MCMC
   намеренно: в движке уже есть независимо засеянные пути со своими
   генераторами (``utils/reliability_a4.py``, ``utils/conformal.py``,
   ``utils/ols_bootstrap.py``, ``engines/causal/_panel_data.py`` – везде
   ``np.random.default_rng(42)``). Глобальный засев сдвинул бы их выдачу, а
   с ней и уже выпущенные клиентам интервалы.
4. ``engines/backtest.py`` кладёт зерно в конфиг переобучения не меньше двух
   раз – проверка на отложенном периоде и перепроверка окон на истории
   обязаны переобучаться тем же зерном, что и исходная модель (иначе разброс
   между прогонами проверки смешается с разбросом самой модели).

Защита от тихого нуля выдержана на каждом инварианте отдельно: пустой список
найденных вызовов/файлов – КРАСНЫЙ результат, а не "всё сходится".
"""
import ast
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_SIDECAR = os.path.dirname(_HERE)
_ENGINES_DIR = os.path.join(_SIDECAR, 'engines')
_UTILS_DIR = os.path.join(_SIDECAR, 'utils')
_MODELER_PY = os.path.join(_ENGINES_DIR, 'modeler.py')
_BACKTEST_PY = os.path.join(_ENGINES_DIR, 'backtest.py')


def _parse_file(path: str) -> ast.Module:
    with open(path, encoding='utf-8') as f:
        src = f.read()
    return ast.parse(src, filename=path)


def _iter_py_files(root: str):
    """Все .py-файлы под root, обходом дерева каталогов, путь отсортирован."""
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith('.py'):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


def _find_pm_sample_calls(tree: ast.Module) -> list[ast.Call]:
    """Все узлы вызова ``pm.sample(...)`` в дереве."""
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == 'sample'
            and isinstance(func.value, ast.Name)
            and func.value.id == 'pm'
        ):
            calls.append(node)
    return calls


def _is_global_numpy_seed_call(node: ast.AST) -> bool:
    """``np.random.seed(...)`` или ``numpy.random.seed(...)`` – глобальный засев."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == 'seed'):
        return False
    middle = func.value
    if not (isinstance(middle, ast.Attribute) and middle.attr == 'random'):
        return False
    base = middle.value
    return isinstance(base, ast.Name) and base.id in ('np', 'numpy')


def _subscript_string_key(node: ast.Subscript) -> str | None:
    """Строковый литерал ключа в ``obj['ключ']``, либо None, если ключ не литерал."""
    sl = node.slice
    # ast.Index – обёртка до Python 3.9, здесь на всякий случай разворачиваем.
    if hasattr(ast, 'Index') and isinstance(sl, ast.Index):
        sl = sl.value
    if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
        return sl.value
    return None


def _find_train_config_seed_assignments(tree: ast.Module) -> list[int]:
    """Номера строк присваиваний вида ``train_config['seed'] = ...``."""
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == 'train_config'
                and _subscript_string_key(target) == 'seed'
            ):
                lines.append(node.lineno)
    return lines


def test_all_pm_sample_calls_have_random_seed():
    """Каждый вызов pm.sample(...) в modeler.py несёт random_seed."""
    tree = _parse_file(_MODELER_PY)
    calls = _find_pm_sample_calls(tree)

    # Защита от тихого нуля: пустой разбор – КРАСНЫЙ, не "стеречь нечего".
    assert len(calls) >= 3, (
        f'В modeler.py обходом дерева найдено вызовов pm.sample: {len(calls)} '
        f'(ожидалось не меньше 3 – Tier-1 NumPyro, Tier-2 PyTensor с колбэком '
        f'и без него). Идиома вызова сменилась – почини тест, не отключай.'
    )

    missing = []
    for call in calls:
        kw_names = {kw.arg for kw in call.keywords if kw.arg is not None}
        if 'random_seed' not in kw_names:
            missing.append(call.lineno)

    assert not missing, (
        'pm.sample(...) без random_seed в modeler.py, строки: '
        f'{missing} – два обучения на одних данных дадут разные апостериорные '
        'интервалы, клиент увидит "поехавшие" цифры при повторном расчёте '
        '(регресс P0.2, utils/seeding.py).'
    )


def test_no_global_numpy_seed_in_engine():
    """В engines/**.py и utils/**.py нет глобального np.random.seed(...)."""
    files = _iter_py_files(_ENGINES_DIR) + _iter_py_files(_UTILS_DIR)

    # Защита от тихого нуля: каталоги переехали или сканирование сломано.
    assert len(files) >= 10, (
        f'Просмотрено файлов engines/+utils/: {len(files)} – ожидалось не '
        f'меньше 10. Каталог переехал или обход дерева сломан.'
    )

    offenders = []
    for path in files:
        tree = _parse_file(path)
        for node in ast.walk(tree):
            if _is_global_numpy_seed_call(node):
                rel = os.path.relpath(path, _SIDECAR)
                offenders.append(f'{rel}:{node.lineno}')

    assert not offenders, (
        'Глобальный засев np.random.seed(...) в движке: '
        + ', '.join(offenders)
        + ' – сдвинет выдачу уже засеянных независимых путей '
        '(reliability_a4.py, conformal.py, ols_bootstrap.py, все на '
        'default_rng(42)), а с ней и уже выпущенные клиентам интервалы. '
        'Зерно MCMC – только через random_seed= в pm.sample (utils/seeding.py).'
    )


def test_backtest_seeds_retraining_config_at_least_twice():
    """backtest.py кладёт зерно в train_config не меньше двух раз."""
    tree = _parse_file(_BACKTEST_PY)
    lines = _find_train_config_seed_assignments(tree)

    assert len(lines) >= 2, (
        f'В backtest.py найдено присваиваний train_config[\'seed\'] = ...: '
        f'{len(lines)} (строки: {lines}). Ожидалось не меньше 2 – проверка на '
        'отложенном периоде и перепроверка окон на истории обязаны '
        'переобучаться тем же зерном, что исходная модель, иначе разброс '
        'между прогонами проверки смешается с разбросом самой модели '
        '(P0.2). Обход дерева ничего не нашёл – переобучение потеряло зерно, '
        'либо идиома присваивания сменилась.'
    )
