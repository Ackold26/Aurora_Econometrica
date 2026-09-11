"""
Сторож INV (дефект 3, аудит 09.09/10.09.2026): клиентский текст движка использует
короткое тире «–», не длинное «—» (правило продукта). Тем же приёмом, что разовый
ast-скан дефекта 3: разбор источников движка через `ast`, строковые литералы БЕЗ
докстрок и БЕЗ tests/.

Из клиентских строк исключены заведомо служебные:
  1) автоматически - литерал внутри вызова `logger.*`/`logging.*`/`print(...)`
     (формат журнала) или внутри вызова `.replace(...)` (сравнение символов) -
     это `EM_DASH` в качестве ИСКОМОГО паттерна, не клиентская проза;
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
from pathlib import Path

EM_DASH = "—"

EXCLUDE_DIRS = {
    "tests", "__pycache__", ".hypothesis", "dist", "_internal",
    ".git", "node_modules", "build",
}

_LOGGING_CALL_NAMES = {"debug", "info", "warning", "warn", "error", "exception", "critical"}

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


class _EmDashVisitor(ast.NodeVisitor):
    """Собирает строковые литералы с «—» вместе с контекстом (вызывающая функция,
    module-level переменная-владелец, признак «внутри logger/print/replace»)."""

    def __init__(self, doc_ids: set[int]):
        self.doc_ids = doc_ids
        self._func_stack: list[str] = []
        self._call_stack: list[str | None] = []
        self._assign_stack: list[str | None] = []
        self.findings: list[dict] = []

    def visit_FunctionDef(self, node):
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        name = None
        f = node.func
        if isinstance(f, ast.Attribute):
            name = f.attr
        elif isinstance(f, ast.Name):
            name = f.id
        self._call_stack.append(name)
        self.generic_visit(node)
        self._call_stack.pop()

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
            self.findings.append({
                "lineno": node.lineno,
                "value": node.value,
                "func": self._func_stack[-1] if self._func_stack else None,
                "assign_target": assign_target,
                "in_logging_call": any(c in _LOGGING_CALL_NAMES for c in self._call_stack),
                "in_print_call": any(c == "print" for c in self._call_stack),
                "in_replace_call": any(c == "replace" for c in self._call_stack),
            })
        self.generic_visit(node)


def _scan_source_for_client_em_dash(source: str, rel_path: str) -> list[tuple[int, str]]:
    """Разбирает ОДИН исходник (строка Python-кода) и возвращает найденные
    клиентские литералы с «—» после применения auto- и именных исключений.
    Вынесено отдельно от обхода каталога, чтобы тест мутации мог прогнать
    сканер на синтетическом исходнике, не трогая файлы движка."""
    tree = ast.parse(source, filename=rel_path)
    doc_ids = _docstring_node_ids(tree)
    visitor = _EmDashVisitor(doc_ids)
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
