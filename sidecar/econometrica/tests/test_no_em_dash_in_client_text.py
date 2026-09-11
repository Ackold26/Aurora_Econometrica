"""
Сторож INV (дефект 3, аудит 09.09/10.09.2026): клиентский текст движка использует
короткое тире «–», не длинное «—» (правило продукта). Тем же приёмом, что разовый
ast-скан дефекта 3: разбор источников движка через `ast`, строковые литералы БЕЗ
докстрок и БЕЗ tests/.

Из клиентских строк исключены заведомо служебные:
  1) автоматически - литерал, который сам является ПРЯМЫМ аргументом (позиционным,
     именованным, или частью f-строки, переданной прямым аргументом) вызова
     `logger.*`/`log.*`/`self.logger.*`/`X.getLogger(...).*`/`logging.*`/`print(...)`
     (формат журнала) или вызова `.replace(...)` (сравнение/замена символов) - это
     `EM_DASH` в качестве ИСКОМОГО паттерна, не клиентская проза. Сужено аудитом s41
     (High x2, 11.09.2026): раньше прощался литерал ГДЕ УГОДНО в стеке вызовов, если
     где-то выше по стеку встречался `.replace(...)` (тонул литерал-получатель, не
     только поисковый образец санитайзера) или метод с именем `error`/`info`/`warn`
     у ЛЮБОГО получателя (`response.error(...)` тонуло наравне с `logger.error(...)`).
     Теперь получатель вызова журнала обязан быть похож на журнал (см.
     `_LOGGER_RECEIVER_RE` - `logger`/`log`/`logging`/`_log`/`_logger`/`LOG`/`LOGGER`
     и варианты с префиксом/суффиксом по факту именования в движке - `m_logger`,
     `save_logger`, `self.logger`, и т.п. - либо результат `x.getLogger(...)`);
  2) именным allowlist `_KNOWN_SERVICE_SCOPES` - конкретные функции/module-level
     переменные, лично проверенные при разборе дефекта 3 через анализ вызывающих
     (см. `Projects/enginefix_report.md`): либо перехватываются и уходят только в
     лог, либо не подключены ни к одному живому API-пути продукта. Каждая запись
     прокомментирована - почему это не клиентский текст.

Докстроки не проверяются намеренно (комментарии разработчика под правило не
подпадают - иначе сторож станет вечно красным на техдокументации и его отключат).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

EM_DASH = "—"

EXCLUDE_DIRS = {
    "tests", "__pycache__", ".hypothesis", "dist", "_internal",
    ".git", "node_modules", "build",
}

_LOGGING_CALL_NAMES = {"debug", "info", "warning", "warn", "error", "exception", "critical"}

# Получатель вызова журнала - по факту именования в движке (grep по
# `sidecar/econometrica`, 11.09.2026): `logger`, `_logger`, `LOG`/`LOGGER`, а также
# суффикс-варианты - `m_logger` (server.py), `save_logger` (server.py),
# `_scn_logger`/`_scenario_logger` (engines/scenario.py), `_preflight_logger`
# (server.py). Якорь по последнему сегменту получателя (`self.logger` → `logger`).
#
# 🔴 Находка проверяющего-противника (11.09.2026): прежнее выражение
# `(?:^|_)(?:logger|log|logging)$` прощало ЛЮБОЙ получатель на голый суффикс `_log`
# (не только `_logger`) - `progress_log.warning(...)` тонуло наравне с
# `logger.warning(...)`, хотя `progress_log` - клиентский объект со случайным именем,
# не журнал. Сужено до РЕАЛЬНО встречающихся форм: точные `log`/`_log`/`logger`/
# `_logger`/`logging` (регистронезависимо - `LOG`/`LOGGER` проходят той же веткой) и
# суффикс `_logger` для произвольного префикса (`m_logger`, `save_logger`,
# `_scn_logger`, `_preflight_logger`) - подтверждено grep-ом реальных получателей
# `sidecar/econometrica` перед вызовами `.debug/.info/.warning/.warn/.error/
# .exception/.critical(`: `_logger`, `_preflight_logger`, `_scenario_logger`,
# `_scn_logger`, `LOG`, `logger`, `m_logger` - ни одного голого `*_log` в реальном
# коде нет. Произвольный `*_log` (без `ger`) больше НЕ прощается.
_LOGGER_RECEIVER_RE = re.compile(r"^(?:log|_log|logger|_logger|logging)$|_logger$", re.IGNORECASE)

# Заведомо служебные литералы (б), НЕ клиентский текст - подтверждено лично при
# разборе дефекта 3 анализом вызывающих (обход поверхностного "raise/return =
# клиенту": часть исключений перехватывается ДО клиента, часть не подключена ни
# к одному живому пути продукта). Ключ - (путь относительно корня движка,
# имя функции ИЛИ имя module-level переменной, к которой приписан литерал).
_KNOWN_SERVICE_SCOPES = {
    # print() в CLI-инструменте разработчика (проверка overflow PPTX-слайдов) -
    # локальный терминальный вывод, клиенту не идёт.
    ("aurora_pptx/check_overflow.py", "report"),
    # raise ValueError за strict=True - ни один вызывающий в продукте не передаёт
    # strict=True (0 вызовов вне tests/), ветка недостижима вживую.
    ("aurora_pptx/font_embed.py", "embed_brand_fonts"),
    # raise CorruptArchiveError - функция вызывается только из tests/, не из
    # server.py/engines в живом пути продукта.
    ("engines/persistence_safe.py", "migrate_pickle_to_safe"),
    # raise ValueError перехватывается ВСЕМИ вызывающими (try/except вокруг
    # _compute_aggregate_roi внутри sensitivity.py) и уходит в logger.warning;
    # compute_sensitivity_tornado документирует "Never raises... warning logged".
    ("engines/sensitivity.py", "_compute_aggregate_roi"),
    # raise ValueError перехватывается ОБОИМИ вызывающими (engines/modeler.py,
    # server.py preflight) через `except Exception → logger.warning`, до клиента
    # не доходит.
    ("utils/reliability_a4.py", "prior_predictive_check"),
    # (bool, message) - message используется ТОЛЬКО в logger.info/logger.warning
    # у вызывающего (engines/modeler.py), в клиентский JSON-ответ не попадает.
    ("utils/fourier_seasonality.py", "should_inject_seasonality"),
    # HOLIDAY_DEFINITIONS - реестр-источник дат, не клиентская копия. Единственный
    # сегодняшний публичный экспорт описаний (describe_holiday_windows) уже
    # пропускает копию через _короткое_тире; get_holiday_metadata - тоже (правка
    # этой сессии). Докстрока _короткое_тире прямо говорит: "сами определения
    # событий не трогаем, у них другие читатели".
    ("utils/holiday_calendar_ru.py", "HOLIDAY_DEFINITIONS"),
    # detect_holiday_collinearity - 0 вызывающих вне этого файла, не подключена ни
    # к одному API/отчёту продукта. Спорный случай (в) из отчёта по дефекту 3 -
    # оставлен на решение владельца, не тронут в этой сессии.
    ("utils/holiday_calendar_ru.py", "detect_holiday_collinearity"),
    # Комментарий сгенерированного JS-файла ("// GENERATED ... DO NOT EDIT") - код-
    # комментарий в сборочном артефакте, не клиентская проза.
    ("tools/sync_kpi_display.py", "generate"),
}


def _iter_py_files(root: Path):
    for p in root.rglob("*.py"):
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        yield p


def _docstring_node_ids(tree: ast.Module) -> set[int]:
    """id() узлов Constant, являющихся докстрокой module/class/func/async func."""
    ids: set[int] = set()

    def _mark(body):
        if body:
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                ids.add(id(first.value))

    _mark(tree.body)
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            _mark(node.body)
    return ids


def _build_parent_map(tree: ast.AST) -> dict[int, ast.AST]:
    """id(узел) → родитель, по всему дереву (не только по посещённым visitor'ом
    узлам) - нужно, чтобы для каждого литерала подняться к БЛИЖАЙШЕМУ вызову, а
    не проверять «есть ли где-то в стеке вызовов подходящее имя»."""
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _direct_call_arg_context(node: ast.AST, parents: dict[int, ast.AST]) -> ast.Call | None:
    """Ближайший ast.Call, которому УЗЕЛ передан ПРЯМЫМ аргументом (позиционным
    или именованным) - либо None, если между узлом и ближайшим вызовом есть
    что-то ещё (другой вызов, бинарная операция и т.п.).

    Разрешён ровно один шаг вверх через ast.JoinedStr (f-строка) - если сам
    литерал - один из фрагментов f-строки, а f-строка целиком передана прямым
    аргументом вызова, это тоже засчитывается («часть f-строки, являющейся
    прямым аргументом», аудит s41 finding #3). Литерал-ПОЛУЧАТЕЛЬ вызова
    (`("текст").replace(...)`) НЕ считается аргументом - его родитель тоже
    Call, но сам он лежит в `call.func`, не в `call.args`/`call.keywords`.
    """
    cur = node
    parent = parents.get(id(cur))
    if isinstance(parent, ast.JoinedStr) and cur in parent.values:
        cur = parent
        parent = parents.get(id(cur))
    if not isinstance(parent, ast.Call):
        return None
    if cur in parent.args or cur in [kw.value for kw in parent.keywords]:
        return parent
    return None


def _is_replace_call(call: ast.Call) -> bool:
    """`<любое_выражение>.replace(...)` - метод по имени, тип получателя не
    важен (может быть переменная, литерал, результат другого вызова)."""
    f = call.func
    return isinstance(f, ast.Attribute) and f.attr == "replace"


def _is_replace_search_pattern(node: ast.AST, call: ast.Call) -> bool:
    """Литерал — ПЕРВЫЙ аргумент `.replace(...)`, то есть искомый образец, а второй
    аргумент длинного тире не вносит.

    Прощается только санитайзер вида `.replace("—", "–")`. Второй аргумент — это то, что
    ВСТАВЛЯЕТСЯ в текст: `шаблон.replace("{вывод}", "Канал — убыточен")` кладёт длинное
    тире клиенту, а обратная замена `.replace("–", "—")` его создаёт (обе — находки
    проверяющего-противника 11.09.2026, прежде прощались как любой прямой аргумент)."""
    if not call.args:
        return False
    first = call.args[0]
    if node is not first and not (isinstance(first, ast.JoinedStr) and node in first.values):
        return False
    second = call.args[1] if len(call.args) > 1 else None
    return not (
        isinstance(second, ast.Constant)
        and isinstance(second.value, str)
        and EM_DASH in second.value
    )


def _is_print_call(call: ast.Call) -> bool:
    f = call.func
    return isinstance(f, ast.Name) and f.id == "print"


def _is_logging_call(call: ast.Call) -> bool:
    """`<журнал>.<имя_из_LOGGING_CALL_NAMES>(...)`, где получатель ПОХОЖ на
    журнал - см. `_LOGGER_RECEIVER_RE` и докстрока модуля. `warn(...)` как
    обычная функция (не метод получателя) сюда не попадает - находка s41
    (`raise X(warn("… — …"))`) требует ИМЕННО получателя-журнала, не любую
    функцию с подходящим именем."""
    f = call.func
    if not isinstance(f, ast.Attribute) or f.attr not in _LOGGING_CALL_NAMES:
        return False
    receiver = f.value
    if isinstance(receiver, ast.Call):
        # logging.getLogger(name).warning(...) / _logging.getLogger(...).warning(...)
        rf = receiver.func
        return isinstance(rf, ast.Attribute) and rf.attr == "getLogger"
    if isinstance(receiver, ast.Name):
        name = receiver.id
    elif isinstance(receiver, ast.Attribute):
        name = receiver.attr  # self.logger / self._logger → последний сегмент
    else:
        return False
    return bool(_LOGGER_RECEIVER_RE.search(name))


class _EmDashVisitor(ast.NodeVisitor):
    """Собирает строковые литералы с «—» вместе с контекстом (вызывающая функция,
    module-level переменная-владелец, признак «прямой аргумент logger/print/
    replace»)."""

    def __init__(self, doc_ids: set[int], parents: dict[int, ast.AST]):
        self.doc_ids = doc_ids
        self.parents = parents
        self._func_stack: list[str] = []
        self._assign_stack: list[str | None] = []
        self.findings: list[dict] = []

    def visit_FunctionDef(self, node):
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node):
        target_name = None
        if (
            not self._func_stack
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            target_name = node.targets[0].id
        self._assign_stack.append(target_name)
        self.generic_visit(node)
        self._assign_stack.pop()

    def visit_Constant(self, node):
        if isinstance(node.value, str) and EM_DASH in node.value and id(node) not in self.doc_ids:
            assign_target = next((t for t in reversed(self._assign_stack) if t), None)
            call = _direct_call_arg_context(node, self.parents)
            self.findings.append({
                "lineno": node.lineno,
                "value": node.value,
                "func": self._func_stack[-1] if self._func_stack else None,
                "assign_target": assign_target,
                "in_logging_call": call is not None and _is_logging_call(call),
                "in_print_call": call is not None and _is_print_call(call),
                "in_replace_call": (
                    call is not None
                    and _is_replace_call(call)
                    and _is_replace_search_pattern(node, call)
                ),
            })
        self.generic_visit(node)


def _scan_source_for_client_em_dash(source: str, rel_path: str) -> list[tuple[int, str]]:
    """Разбирает ОДИН исходник (строка Python-кода) и возвращает найденные
    клиентские литералы с «—» после применения auto- и именных исключений.
    Вынесено отдельно от обхода каталога, чтобы тест мутации мог прогнать
    сканер на синтетическом исходнике, не трогая файлы движка."""
    tree = ast.parse(source, filename=rel_path)
    doc_ids = _docstring_node_ids(tree)
    parents = _build_parent_map(tree)
    visitor = _EmDashVisitor(doc_ids, parents)
    visitor.visit(tree)

    out = []
    for item in visitor.findings:
        if item["in_logging_call"] or item["in_print_call"] or item["in_replace_call"]:
            continue
        scope = item["assign_target"] or item["func"]
        if (rel_path, scope) in _KNOWN_SERVICE_SCOPES:
            continue
        out.append((item["lineno"], item["value"]))
    return out


def _scan_engine_root(root: Path) -> list[tuple[str, int, str]]:
    findings = []
    for f in sorted(_iter_py_files(root)):
        rel = f.relative_to(root).as_posix()
        src = f.read_text(encoding="utf-8")
        for lineno, value in _scan_source_for_client_em_dash(src, rel):
            findings.append((rel, lineno, value))
    return findings


def _engine_root() -> Path:
    return Path(__file__).resolve().parent.parent


def test_no_em_dash_in_engine_client_text():
    """INV (10.09.2026): клиентский текст движка - короткое тире «–», не «—»."""
    findings = _scan_engine_root(_engine_root())
    assert not findings, (
        "Клиентский текст с длинным тире «—» (правило продукта - короткое «–»):\n"
        + "\n".join(f"  {p}:{l}: {v!r}" for p, l, v in findings)
    )


def test_no_em_dash_guard_catches_mutation():
    """Сторож обязан уметь покраснеть: подставляем ЗАВЕДОМО клиентский литерал
    (return-словарь с ключом 'message', вне logger/print/replace, вне allowlist)
    с длинным тире в синтетический исходник и доказываем, что сканер его ловит."""
    mutated_source = (
        "def build_client_message():\n"
        "    return {'status': 'error', 'message': 'бюджет пуст — сплит не определён'}\n"
    )
    findings = _scan_source_for_client_em_dash(mutated_source, "synthetic_mutation.py")
    assert findings, "мутация не сработала - сканер не покраснел на клиентском «—»"
    assert findings[0][1] == "бюджет пуст — сплит не определён"

    # Контроль: тот же литерал внутри logger.warning(...) сканер обязан ПРОПУСТИТЬ
    # (иначе сторож не различает клиент/служебное и станет шумным).
    control_source = (
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "def log_something():\n"
        "    logger.warning('бюджет пуст — сплит не определён')\n"
    )
    control_findings = _scan_source_for_client_em_dash(control_source, "synthetic_control.py")
    assert not control_findings, "сканер ложно покраснел на служебном logger.warning(...)"


def test_replace_receiver_literal_not_swallowed():
    """Аудит s41, High, `in_replace_call` (test_no_em_dash_in_client_text.py:172): раньше гасился ВЕСЬ
    стек вызовов, если где-то выше по дереву встречался `.replace(...)` - тонул
    не только поисковый образец санитайзера, но и литерал-ПОЛУЧАТЕЛЬ вызова
    (`("Канал — убыточен").replace("ё","е")` меняет «ё», длинное тире остаётся
    как было). Теперь такой литерал должен быть найден - он не прямой аргумент
    `.replace(...)`, он его получатель."""
    mutated_source = (
        "def build_client_message():\n"
        "    return ('Канал — убыточен').replace('ё', 'е')\n"
    )
    findings = _scan_source_for_client_em_dash(mutated_source, "synthetic_replace_receiver.py")
    assert findings, "литерал-получатель .replace() тонет молча - сторож не покраснел"
    assert findings[0][1] == "Канал — убыточен"


def test_replace_sanitizer_argument_still_forgiven():
    """Контроль: настоящий санитайзер - литерал с «—», который САМ передан
    ПРЯМЫМ аргументом `.replace(...)` (поисковый образец замены) - как и
    раньше, прощается (это и есть единственный законный случай auto-
    исключения по `.replace`, ср. `utils/holiday_calendar_ru.py`)."""
    control_source = (
        "def sanitize(текст):\n"
        "    return str(текст).replace('—', '–')\n"
    )
    findings = _scan_source_for_client_em_dash(control_source, "synthetic_replace_sanitizer.py")
    assert not findings, f"сторож ложно покраснел на настоящем санитайзере .replace: {findings}"


def test_logging_call_by_method_name_only_not_swallowed():
    """Аудит s41, High, `in_logging_call` (test_no_em_dash_in_client_text.py:153): раньше прощалось по
    ИМЕНИ метода ГДЕ УГОДНО в стеке вызовов, у ЛЮБОГО получателя -
    `response.error(...)` тонуло наравне с `logger.error(...)`, потому что
    метод назвали `error`. Теперь получатель обязан быть похож на журнал."""
    mutated_source = (
        "def handle():\n"
        "    return response.error('Бюджет пуст — расчёт невозможен')\n"
    )
    findings = _scan_source_for_client_em_dash(mutated_source, "synthetic_logging_name_only.py")
    assert findings, "response.error(...) тонет молча - сторож не различает получателя"
    assert findings[0][1] == "Бюджет пуст — расчёт невозможен"


def test_logging_bare_function_not_swallowed():
    """Из той же находки: `raise X(warn("… — …"))` - `warn(...)` здесь обычная
    функция (не метод получателя-журнала), литерал обязан быть найден, не
    прощён по одному только совпадению имени с `_LOGGING_CALL_NAMES`."""
    mutated_source = (
        "def handle():\n"
        "    raise ValueError(warn('Бюджет пуст — расчёт невозможен'))\n"
    )
    findings = _scan_source_for_client_em_dash(mutated_source, "synthetic_bare_warn.py")
    assert findings, "warn(...) как обычная функция тонет наравне с logger.warn(...)"


def test_real_logger_receiver_variants_still_forgiven():
    """Контроль: реальные имена журналов движка (grep по `sidecar/econometrica`,
    11.09.2026) - `m_logger`/`save_logger`-подобные суффиксные имена, `self.logger`,
    `LOG`/`LOGGER`, и цепочка `logging.getLogger(...).warning(...)` - остаются
    прощены после сужения."""
    control_source = (
        "import logging\n"
        "def a():\n"
        "    m_logger = logging.getLogger('a')\n"
        "    m_logger.warning('канал — превышен лимит')\n"
        "def b(self):\n"
        "    self.logger.error('канал — превышен лимит')\n"
        "def c():\n"
        "    LOG.info('канал — превышен лимит')\n"
        "def d():\n"
        "    logging.getLogger(__name__).warning('канал — превышен лимит')\n"
    )
    findings = _scan_source_for_client_em_dash(control_source, "synthetic_logger_variants.py")
    assert not findings, f"ложное срабатывание на настоящих журналах движка: {findings}"


def test_bare_underscore_log_suffix_receiver_not_forgiven():
    """Находка проверяющего-противника (11.09.2026): прежнее выражение
    `(?:^|_)(?:logger|log|logging)$` прощало ЛЮБОЙ получатель, заканчивающийся на
    `_log` (не только `_logger`) - `progress_log.warning(...)` тонуло наравне с
    `logger.warning(...)`, хотя `progress_log` - обычный клиентский объект со
    случайным именем, не журнал. Сужение обязано ловить длинное тире внутри."""
    mutated_source = (
        "def build_client_message(progress_log):\n"
        "    return progress_log.warning('Канал — убыточен')\n"
    )
    findings = _scan_source_for_client_em_dash(mutated_source, "synthetic_bare_log_suffix.py")
    assert findings, "получатель на голый «_log» (не «_logger») тонет молча - сторож не покраснел"
    assert findings[0][1] == "Канал — убыточен"


def test_logger_fstring_direct_argument_still_forgiven():
    """Часть находки #3: литерал внутри f-строки, которая САМА передана прямым
    аргументом вызова журнала, должна прощаться - не только простой строковый
    литерал."""
    control_source = (
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "def a(канал):\n"
        "    logger.warning(f'{канал} — превышен лимит')\n"
    )
    findings = _scan_source_for_client_em_dash(control_source, "synthetic_logger_fstring.py")
    assert not findings, f"ложное срабатывание на f-строке в logger.warning(...): {findings}"


def test_replace_replacement_argument_not_swallowed():
    """Проверяющий-противник 11.09.2026: `.replace` прощал ЛЮБОЙ прямой аргумент, а
    второй аргумент — вставляемый текст. Шаблон клиенту и обратная замена «–»→«—»
    обязаны быть найдены; настоящий санитайзер `.replace("—", "–")` — по-прежнему прощён."""
    template_source = (
        "def build(шаблон):\n"
        "    return шаблон.replace('{вывод}', 'Канал — убыточен')\n"
    )
    assert _scan_source_for_client_em_dash(template_source, "synthetic_replace_template.py"), (
        "текст, вставляемый .replace клиенту, тонет молча"
    )
    reverse_source = (
        "def build(текст):\n"
        "    return текст.replace('–', '—')\n"
    )
    assert _scan_source_for_client_em_dash(reverse_source, "synthetic_replace_reverse.py"), (
        "обратная замена, создающая длинное тире, тонет молча"
    )
    sanitizer_source = (
        "def sanitize(текст):\n"
        "    return текст.replace('—', '–')\n"
    )
    assert not _scan_source_for_client_em_dash(sanitizer_source, "synthetic_replace_ok.py")
