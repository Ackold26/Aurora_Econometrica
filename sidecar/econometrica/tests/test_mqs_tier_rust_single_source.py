"""Паритет канона MQS с Rust-слоем отчётов (report.rs / mqs_tiers.rs).

Инцидент, ради которого заводился (2026-07-27): пока Python (`_MQS_TIERS`,
utils/diagnostics.py) и JS (`mqs-tiers.js`, сверяется
`src/lib/__tests__/mqs-tiers.guard.test.js`) уже были сведены к одному
источнику 85/70/55/40, Rust-слой Excel/Markdown-отчётов (`report.rs`) держал
СВОЮ лестницу 80/60 в четырёх местах: строка вердикта XLSX, две
рекомендации markdown, глоссарий. Внешний аудит нашёл рецидив (см.
test_mqs_tier_single_source.py про тот же паттерн на слое PPTX/HTML) — тот
же дефект, третий язык в профиль.

2026-07-27 пороги/ярлыки в Rust переехали в единственный модуль
`src-tauri/src/commands/mqs_tiers.rs::MQS_TIERS`; `report.rs` больше не
хранит числовых порогов MQS вовсе — только зовёт функции модуля
(`resolve_mqs_label`, `mqs_is_dependable`, `mqs_is_weak`, `mqs_scale_text`).

Тест держит ДВЕ гарантии структурно, не по памяти "все места нашли":
  1. ПАРИТЕТ — таблица `MQS_TIERS` в mqs_tiers.rs совпадает с питоновским
     `_MQS_TIERS` порог-в-порог, ярлык-в-ярлык, цвет-в-цвет.
  2. НЕТ ГОЛОЙ ЛЕСТНИЦЫ В report.rs — файл больше не сравнивает балл модели
     (`v`) с числами старой 3-уровневой лестницы (80.0/60.0) или голыми
     каноническими порогами (85.0/70.0/55.0/40.0) в обход mqs_tiers.

Защита от тихого нуля: пустой разбор канона либо отсутствие проверяемых
Rust-файлов — КРАСНЫЙ результат, а не "всё сходится".
"""
import os
import re

from utils.diagnostics import _MQS_TIERS

_HERE = os.path.dirname(os.path.abspath(__file__))
# sidecar/econometrica/tests/ → ../../../src-tauri/src/commands/
_RUST_COMMANDS_DIR = os.path.abspath(
    os.path.join(_HERE, "..", "..", "..", "src-tauri", "src", "commands")
)
_MQS_TIERS_RS = os.path.join(_RUST_COMMANDS_DIR, "mqs_tiers.rs")
_REPORT_RS = os.path.join(_RUST_COMMANDS_DIR, "report.rs")

_MQS_TIER_ROW_RE = re.compile(
    r'MqsTier\s*\{\s*min:\s*([\d.]+)\s*,\s*tier:\s*"([a-z_]+)"\s*,\s*'
    r'label:\s*"([^"]+)"\s*,\s*color:\s*"(#[0-9a-fA-F]{6})"\s*\}'
)


def _parse_rust_tiers() -> list[dict]:
    assert os.path.isfile(_MQS_TIERS_RS), (
        f"Канон Rust не найден: {_MQS_TIERS_RS} — путь сместился, почини тест, не отключай"
    )
    with open(_MQS_TIERS_RS, encoding="utf-8") as f:
        src = f.read()
    return [
        {"min": float(m.group(1)), "tier": m.group(2), "label": m.group(3), "color": m.group(4)}
        for m in _MQS_TIER_ROW_RE.finditer(src)
    ]


def _parse_python_tiers() -> list[dict]:
    return [
        {"min": float(threshold), "tier": tier, "label": label, "color": color}
        for threshold, tier, label, color in _MQS_TIERS
    ]


def test_rust_mqs_tiers_parity_with_python_canon():
    rust_rows = _parse_rust_tiers()
    # защита от тихого нуля: пустой разбор — это КРАСНЫЙ, а не «всё сходится»
    assert rust_rows, (
        "Из mqs_tiers.rs не разобрано ни одной ступени — форма записи MQS_TIERS "
        "изменилась, тест смотрит не туда, а не «канон синхронен»"
    )

    py_rows = _parse_python_tiers()
    assert py_rows, "_MQS_TIERS в diagnostics.py пуст — канон сломан"

    print(
        f"ОХВАТ паритета: сверено {len(rust_rows)} ступеней Rust "
        f"(mqs_tiers.rs) против {len(py_rows)} ступеней Python-канона "
        f"(_MQS_TIERS)"
    )
    assert rust_rows == py_rows, (
        "Rust mqs_tiers.rs разошёлся с питоновским каноном _MQS_TIERS "
        f"(рецидив L16/инцидент 2026-07-27 в третьем языке):\n"
        f"Rust:   {rust_rows}\n"
        f"Python: {py_rows}"
    )


# Старая лестница 80/60 и голые канонические пороги 85/70/55/40 в сравнении
# с переменной балла `v` (устойчивое имя во всех match-ветках report.rs,
# `Some(v) => ...`). Строки, зовущие сам модуль (`mqs_tiers::...`), законны —
# именно туда и должна была переехать логика.
_BARE_MQS_THRESHOLD_RE = re.compile(
    r'\bv\s*(?:>=|<=|>|<)\s*(?:85|80|70|60|55|40)\.0\b'
)


def test_report_rs_has_no_bare_mqs_ladder():
    assert os.path.isfile(_REPORT_RS), f"report.rs не найден: {_REPORT_RS}"
    with open(_REPORT_RS, encoding="utf-8") as f:
        lines = f.readlines()

    # защита от тихого нуля: файл почти пуст — тест смотрит не туда
    assert len(lines) > 500, f"report.rs подозрительно короткий ({len(lines)} строк) — путь сместился?"

    offenders = [
        (i + 1, ln.strip())
        for i, ln in enumerate(lines)
        if _BARE_MQS_THRESHOLD_RE.search(ln) and "mqs_tiers::" not in ln
    ]
    print(f"ОХВАТ голой лестницы: проверено {len(lines)} строк report.rs")
    assert not offenders, (
        "report.rs снова держит свою лестницу порогов MQS вместо вызова "
        f"mqs_tiers::*: {offenders}"
    )
