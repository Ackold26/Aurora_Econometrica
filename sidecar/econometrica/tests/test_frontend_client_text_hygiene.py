"""Лёгкая проверка гигиены клиентского текста для интерфейса приложения (Svelte).

Фаза 3 (2026-07-25): третий и последний из трёх стеков экспортных/видимых
клиенту текстов (после HTML — test_report_text_hygiene.py — и Rust-таблицы —
test_report_rs_client_text_hygiene.py). До этой правки интерфейс (src/**/*.svelte)
не проверялся НИЧЕМ на те же правила П8-1/П8-2, что применяются к отчётам.

Полноценный Svelte-парсер здесь избыточен ("лёгкая проверка" по заданию
Фазы 3). Механика своя под этот стек: .svelte-файл смешивает <script>
(JS-код, идентификаторы вроде `baseline` как имя переменной/пропа — НЕ
клиентский текст), <style> (CSS, `align-items: baseline` — валидное
CSS-свойство, НЕ нарушение) и разметку с текстом. Наивный скан всего файла
даёт ПОЧТИ ПОЛНЫЙ ШУМ (проверено эмпирически при разработке: 1057 "хитов"
em-dash / 348 "baseline" по всему src/ до фильтрации — в подавляющем
большинстве CSS/идентификаторы/комментарии, не текст). Поэтому здесь
вырезаются <script>/<style>/<!-- -->-блоки, значения HTML-атрибутов (кроме
title/aria-label/placeholder/alt — они остаются пулом текста, т.к. это
реальный клиентский текст, просто в атрибуте) и Svelte mustache-выражения
`{...}` (переменные/директивы `{#if baseline}`, `{@const x = ...}` — код,
не проза).

Известное ограничение (документируется, не маскируется): title={...} с
JS-template-literal (backtick-строка вместо двойных кавычек) не попадает в
общий текстовый пул и не проверяется — часть тултипов вне охвата этой
лёгкой проверки. Компромисс лёгкого инструмента, не скрытое сужение: явно
проговорено здесь и в отчёте Фазы 3.
"""
import os
import re

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
# sidecar/econometrica/tests/ → ../../../src
_SRC_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", "src"))

SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
WHITELIST_ATTR_RE = re.compile(
    r'\b(?:title|aria-label|placeholder|alt)\s*=\s*"([^"]*)"', re.IGNORECASE
)
ANY_ATTR_VALUE_RE = re.compile(r'=\s*"[^"]*"')
TAG_RE = re.compile(r"<[^>]+>")
MUSTACHE_RE = re.compile(r"\{[^{}]*\}")
# Внутренние JS-ключи/идентификаторы вида 'adstock' / "baseline" (нижний
# регистр, кавычки вплотную) — аргументы функций, не клиентский текст.
_INTERNAL_KEY_RE = re.compile(r"""['"](?:adstock|baseline)['"]""")

EM_DASH_RE = re.compile(r"—")
BASELINE_RE = re.compile(r"\bbaseline\b", re.IGNORECASE)
# "media-" вплотную к кириллице — реальный паттерн утечки (напр. "media-вклад"
# вместо "медиа-вклад"). Без этого сужения шум CSS-классов (.media-table) и
# JS-идентификаторов ('media-analyst') полностью маскирует сигнал.
MEDIA_LATIN_RE = re.compile(r"media-[а-яёА-ЯЁ]", re.IGNORECASE)
ADSTOCK_RE = re.compile(r"(?<!\()\badstock\b(?!\))", re.IGNORECASE)


def _strip_mustache(s: str) -> str:
    for _ in range(6):
        new = MUSTACHE_RE.sub(" ", s)
        if new == s:
            break
        s = new
    return s


def extract_display_text(content: str) -> str:
    """Клиентский текст .svelte-файла: без <script>/<style>/комментариев/
    атрибутов-разметки/mustache-выражений. См. докстринг модуля."""
    content = SCRIPT_RE.sub(" ", content)
    content = STYLE_RE.sub(" ", content)
    content = COMMENT_RE.sub(" ", content)
    whitelisted = " ".join(WHITELIST_ATTR_RE.findall(content))
    content = ANY_ATTR_VALUE_RE.sub("=X", content)
    content = TAG_RE.sub("\n", content)
    content = _strip_mustache(content)
    whitelisted = _strip_mustache(whitelisted)
    pool = content + "\n" + whitelisted
    pool = _INTERNAL_KEY_RE.sub(" ", pool)
    return pool


def _iter_svelte_files():
    for dirpath, _dirnames, filenames in os.walk(_SRC_ROOT):
        for name in filenames:
            if name.endswith(".svelte"):
                yield os.path.join(dirpath, name)


def _relpath(path: str) -> str:
    return os.path.relpath(path, _SRC_ROOT).replace(os.sep, "/")


def _collect_violations():
    em, baseline, media, adstock = [], [], [], []
    scanned = 0
    for path in _iter_svelte_files():
        scanned += 1
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        disp = extract_display_text(content)
        rel = _relpath(path)
        for line in disp.split("\n"):
            line = line.strip()
            if not line:
                continue
            if EM_DASH_RE.search(line):
                em.append((rel, line[:110]))
            if BASELINE_RE.search(line):
                baseline.append((rel, line[:110]))
            if MEDIA_LATIN_RE.search(line):
                media.append((rel, line[:110]))
            if ADSTOCK_RE.search(line):
                adstock.append((rel, line[:110]))
    return {"scanned": scanned, "em_dash": em, "baseline": baseline,
            "media_latin": media, "adstock": adstock}


# Спорные находки (2026-07-25) — плотные двуязычные технические тултипы
# продвинутых панелей (ConfigPanel: настройки Adstock; ChannelCategoriesPanel
# и DecomposeStep: подсказки про adstock decay/hierarchical prior/posterior
# uncertainty; ReportStep: превью содержимого XLSX-спецификации, зеркалит
# ту же развилку, что уже отмечена спорной в report.rs строках 135-136).
# Точечный фикс одного слова "adstock" оставит эти тултипы непоследовательными
# (кругом остаётся "decay", "hierarchical prior", "variance", "posterior
# uncertainty" на английском) — нужно решение Антона об уровне русификации
# технических тултипов для продвинутых панелей целиком, не патч одного слова.
# НЕ исключения в regex (правило не ослаблено) — конкретные файлы помечены
# поимённо и оставлены как известное расхождение.
_KNOWN_ADSTOCK_SPORNY_FILES = {
    "lib/components/ConfigPanel.svelte",
    "lib/components/pipeline/ChannelCategoriesPanel.svelte",
    "lib/components/pipeline/DecomposeStep.svelte",
    "lib/components/pipeline/ReportStep.svelte",
}


def test_svelte_no_em_dash():
    v = _collect_violations()
    assert not v["em_dash"], f"П8-1: em-dash в интерфейсе (src/**/*.svelte): {v['em_dash'][:5]}"


def test_svelte_no_bare_baseline():
    v = _collect_violations()
    assert not v["baseline"], f"П8-2: голый baseline в интерфейсе: {v['baseline'][:5]}"


def test_svelte_no_media_latin():
    v = _collect_violations()
    assert not v["media_latin"], f"П8-2: latin media- в интерфейсе: {v['media_latin'][:5]}"


def test_svelte_bare_adstock_known_or_none():
    v = _collect_violations()
    unexpected = [(f, s) for f, s in v["adstock"] if f not in _KNOWN_ADSTOCK_SPORNY_FILES]
    assert not unexpected, f"П8-2: НОВЫЙ голый adstock в интерфейсе: {unexpected}"
    known = [(f, s) for f, s in v["adstock"] if f in _KNOWN_ADSTOCK_SPORNY_FILES]
    if known:
        pytest.xfail(
            f"Спорная находка (плотные двуязычные тултипы продвинутых панелей, "
            f"{len(set(f for f, _ in known))} файлов, {len(known)} строк) — "
            f"решение об уровне русификации за Антоном, см. PHASE3_ECON_COVERAGE.md"
        )


def test_svelte_coverage_is_reported():
    """Печатает и проверяет ФАКТ охвата — числом, не на глаз."""
    v = _collect_violations()
    adstock_files = sorted(set(f for f, _ in v["adstock"]))
    summary = (
        f"ОХВАТ интерфейса (src/**/*.svelte): файлов просканировано {v['scanned']}; "
        f"известные спорные файлы (adstock-тултипы) {len(adstock_files)}: {adstock_files}"
    )
    print(summary)
    assert v["scanned"] > 100, (
        "src/**/*.svelte: почти не нашли файлов — либо структура репозитория "
        "изменилась, либо проверка сломана (см. _SRC_ROOT путь)"
    )
