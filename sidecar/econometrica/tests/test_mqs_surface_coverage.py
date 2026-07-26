"""Охват поверхностей: несчитанная оценка качества модели нигде не становится нулём.

Инвариант «нет числа — нет подписи» закрывался поверхность за поверхностью и
трижды возвращался с другой стороны: сначала на слайдах, потом в разделе выводов
HTML, потом в XLSX, markdown и карточке HTML. Каждый раз чинили названные места,
а класс оставался открытым — следующая поверхность появлялась через неделю.

Этот гейт закрывает КЛАСС, а не места. Он ищет во всех трёх стеках приведение
отсутствующей оценки к нулю — то самое, из-за чего клиент получал приговор
модели вместо отметки, что её не оценивали.

Охват печатается числом (правило линейки): сколько файлов и строк просмотрено по
каждому стеку. Пустой вход — КРАСНЫЙ, а не «всё чисто»: гейт, который ничего не
нашёл потому, что ничего не читал, хуже отсутствующего.

Реестр узаконенных исключений — ПО ТЕКСТУ СТРОКИ, не по номеру: номера сползают
при любой правке файла, и реестр по ним молча протухает.
"""
import io
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_SIDECAR = os.path.dirname(_HERE)
_ROOT = os.path.abspath(os.path.join(_SIDECAR, "..", ".."))

# ── Стеки и то, как в каждом выглядит приведение к нулю ──────────────────────
# Ключ — имя стека для отчёта об охвате; значение — (корень, расширения, шаблон).
_STACKS = {
    "Rust": (
        os.path.join(_ROOT, "src-tauri", "src"),
        (".rs",),
        re.compile(r"unwrap_or\(\s*0(\.0)?\s*\)|unwrap_or_default\(\)"),
    ),
    "Python": (
        _SIDECAR,
        (".py",),
        re.compile(r"\bor\s+0(\.0)?\b|,\s*0(\.0)?\s*\)"),
    ),
    "Интерфейс": (
        os.path.join(_ROOT, "src"),
        (".js", ".svelte"),
        re.compile(r"(\?\?|\|\|)\s*0(\.0)?\b"),
    ),
}

# Строка засчитывается, только если речь именно об оценке качества модели.
_MQS_RE = re.compile(r"\bmqs\b|mqs_score|mqs\[|\"mqs\"|'mqs'", re.IGNORECASE)

_LEGITIMISED: tuple[str, ...] = (
    # Сюда — только то, где ноль является настоящим значением, а не заглушкой.
    # Каждая запись обязана нести обоснование в комментарии рядом.
)

# `dist` и `_internal` — собранные копии sidecar'а: они повторяют исходники и
# дают двойной счёт, а править их бессмысленно (перезаписываются сборкой).
_SKIP_DIRS = {
    "node_modules", ".svelte-kit", "__pycache__", "target", "build", ".git",
    "dist", "_internal",
}


def _is_comment(line: str) -> bool:
    t = line.lstrip()
    return (
        t.startswith("#")
        or t.startswith("//")
        or t.startswith("*")
        or t.startswith("/*")
        or t.startswith("<!--")
    )


def _walk(root: str, exts: tuple[str, ...]):
    if not os.path.isdir(root):
        return
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            if name.endswith(exts):
                path = os.path.join(dirpath, name)
                # Тесты не продукт: они вправе строить нули как входные данные.
                if "__tests__" in path or re.search(r"[\\/]tests?[\\/]", path):
                    continue
                if re.search(r"\.(test|spec)\.", name):
                    continue
                yield path


def _scan():
    """Возвращает (нарушения, охват-по-стекам)."""
    offenders = []
    coverage = {}
    for stack, (root, exts, zero_re) in _STACKS.items():
        files = 0
        lines = 0
        for path in _walk(root, exts):
            files += 1
            for i, line in enumerate(io.open(path, encoding="utf-8", errors="replace"), 1):
                lines += 1
                if _is_comment(line):
                    continue
                if any(lit in line for lit in _LEGITIMISED):
                    continue
                if _MQS_RE.search(line) and zero_re.search(line):
                    rel = os.path.relpath(path, _ROOT)
                    offenders.append(f"[{stack}] {rel}:{i}: {line.strip()[:110]}")
        coverage[stack] = (files, lines)
    return offenders, coverage


def test_coverage_is_not_silently_empty():
    """Страховка от тихого нуля: гейт обязан реально что-то прочитать."""
    _offenders, coverage = _scan()
    report = " · ".join(
        f"{stack}: {files} файлов / {lines} строк" for stack, (files, lines) in coverage.items()
    )
    print(f"\nОхват гейта отсутствия оценки — {report}")
    for stack, (files, lines) in coverage.items():
        assert files > 0, (
            f"стек «{stack}»: просмотрено 0 файлов — каталог переехал, гейт смотрит не туда"
        )
        assert lines > 100, (
            f"стек «{stack}»: просмотрено {lines} строк — чтение сломано"
        )


def test_missing_mqs_never_becomes_zero():
    """Ни на одной поверхности отсутствующая оценка не приводится к нулю."""
    offenders, _coverage = _scan()
    assert not offenders, (
        "несчитанная оценка качества модели приводится к нулю — клиент получит "
        "приговор модели вместо отметки, что её не оценивали. Ветвитесь по "
        "наличию значения и показывайте честное отсутствие:\n" + "\n".join(offenders)
    )
