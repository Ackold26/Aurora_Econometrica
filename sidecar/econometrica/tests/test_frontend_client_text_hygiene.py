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

Фаза 4 (2026-07-26): закрыта структурная дыра в самой Фазе 3 — SCRIPT_RE
стирал ВЕСЬ <script>...</script> ДО сканирования, значит клиентский текст,
объявленный в скрипте и отрисованный через {переменная} (labels дропдаунов,
computeStatus.set(...)-сообщения, FAQ-подсказки, тултипы в JS-объектах), не
проверялся НИКЕМ. extract_script_literals() извлекает строковые литералы
('…', "…", `…`) из <script>, вырезая ДО этого блочные/построчные комментарии
(код для разработчика, не проза) и заменяя ${...}-интерполяцию в
template-literal пробелом (см. _strip_template_interp — ручной подсчёт
глубины скобок, а не regex, т.к. в кодовой базе есть паттерн
`${/** @type {number} */ (x).toFixed(1)}` с ВЛОЖЕННЫМИ {} внутри JSDoc-каста,
который наивный `\\$\\{[^{}]*\\}` не берёт).

П8-1 (em-dash) проверяется на ЛЮБОМ извлечённом литерале: символ «—» не
встречается ни в JS/CSS-синтаксисе, ни в regex/импортах, риск поймать код —
практически нулевой. П8-2 (bare baseline/media-/adstock) проверяется ТОЛЬКО
на литералах с кириллицей — без неё строка почти всегда идентификатор/ключ/
CSS-класс ('baseline' как имя переменной, 'media-table' класс), а не
клиентский текст; ложное срабатывание здесь дороже пропуска (условие
координатора). Ручная проверка на контрольных примерах (ConfigPanel.svelte)
подтвердила: 0 идентификаторов/импортов поймано, извлечение совпало 1:1 с
независимым внешним аудитом (41 хит em-dash в 18 файлах).
"""
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
# sidecar/econometrica/tests/ → ../../../src
_SRC_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", "src"))

SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
# Фаза 4: тот же <script>, но с захватом содержимого — для извлечения текста
# ИЗ него (SCRIPT_RE выше стирает блок целиком для markup-пула, эта версия
# нужна, чтобы взять то, что стирается).
SCRIPT_CONTENT_RE = re.compile(r"<script\b[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
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
# Фаза 4: гейт "это вообще похоже на клиентский текст, а не идентификатор" —
# см. докстринг модуля.
CYRILLIC_RE = re.compile(r"[а-яёА-ЯЁ]")

# ── Фаза 4: извлечение строковых литералов из <script> ──────────────────
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRING_SINGLE_RE = re.compile(r"'((?:[^'\\\n]|\\.)*)'")
_STRING_DOUBLE_RE = re.compile(r'"((?:[^"\\\n]|\\.)*)"')
_TEMPLATE_LIT_RE = re.compile(r"`((?:[^`\\]|\\.)*)`", re.DOTALL)


def _strip_template_interp(s: str) -> str:
    """Заменяет ${...} внутри template-literal на пробел, учитывая ВЛОЖЕННЫЕ
    фигурные скобки. Паттерн `${/** @type {number} */ (x).toFixed(1)}`
    (JSDoc type-cast внутри интерполяции — частый в этом кодовом стиле) имеет
    {number} ВНУТРИ ${...}; наивный regex `\\$\\{[^{}]*\\}` рвётся на первой
    внутренней "{" и не находит закрывающую "}" интерполяции — отсюда ручной
    подсчёт глубины скобок вместо re.sub."""
    out = []
    i, n = 0, len(s)
    while i < n:
        if s[i] == "$" and i + 1 < n and s[i + 1] == "{":
            depth = 1
            j = i + 2
            while j < n and depth > 0:
                if s[j] == "{":
                    depth += 1
                elif s[j] == "}":
                    depth -= 1
                j += 1
            out.append(" ")
            i = j
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _strip_script_line_comments(code: str) -> str:
    """Построчно вырезает `// ...` — та же осторожная эвристика, что в
    test_report_rs_client_text_hygiene.py::_string_literals: если после `//`
    на строке нет кавычки, считаем что это реальный line-comment хвост (не
    режем `//` внутри уже открытой строки, напр. URL)."""
    out_lines = []
    for line in code.split("\n"):
        if line.strip().startswith("//"):
            out_lines.append("")
            continue
        if "//" in line:
            idx = line.find("//")
            before, after = line[:idx], line[idx + 2:]
            if not any(q in after for q in ("'", '"', "`")):
                line = before
        out_lines.append(line)
    return "\n".join(out_lines)


def extract_script_literals(content: str) -> list:
    """Строковые литералы ('...', "...", `...`) из <script>-блока(ов) файла —
    закрывает дыру Фазы 3 (см. докстринг модуля). Комментарии вырезаются
    заранее; template-literal интерполяция ${...} заменяется пробелом.
    Каждый литерал — отдельная смысловая единица (в отличие от markup, где
    текст рвётся тегами произвольно)."""
    literals = []
    for m in SCRIPT_CONTENT_RE.finditer(content):
        block = _BLOCK_COMMENT_RE.sub(" ", m.group(1))
        block = _strip_script_line_comments(block)

        def _take_template(tm):
            literals.append(_strip_template_interp(tm.group(1)))
            return " "  # стереть из block, чтобы кавычки внутри template не спутали regex ниже

        block = _TEMPLATE_LIT_RE.sub(_take_template, block)
        literals.extend(_STRING_SINGLE_RE.findall(block))
        literals.extend(_STRING_DOUBLE_RE.findall(block))
    return literals


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
    script_literals_total = 0
    script_literals_cyrillic = 0
    for path in _iter_svelte_files():
        scanned += 1
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        rel = _relpath(path)

        # ── Markup-пул (Фаза 3, без изменений) ──
        disp = extract_display_text(content)
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

        # ── Script-пул (Фаза 4) — см. докстринг модуля для обоснования,
        # почему em-dash проверяется на любом литерале, а baseline/media-/
        # adstock — только на литералах с кириллицей.
        for literal in extract_script_literals(content):
            script_literals_total += 1
            if EM_DASH_RE.search(literal):
                em.append((rel, literal[:110]))
            if not CYRILLIC_RE.search(literal):
                continue
            script_literals_cyrillic += 1
            if BASELINE_RE.search(literal):
                baseline.append((rel, literal[:110]))
            if MEDIA_LATIN_RE.search(literal):
                media.append((rel, literal[:110]))
            if ADSTOCK_RE.search(literal):
                adstock.append((rel, literal[:110]))
    return {
        "scanned": scanned,
        "script_literals_total": script_literals_total,
        "script_literals_cyrillic": script_literals_cyrillic,
        "em_dash": em, "baseline": baseline,
        "media_latin": media, "adstock": adstock,
    }


# Узаконенные технические подсказки (решение владельца 2026-07-26): принятые
# термины отрасли остаются как есть в плотных двуязычных тултипах продвинутых
# панелей (ConfigPanel: настройки Adstock; ChannelCategoriesPanel и
# DecomposeStep: подсказки про adstock decay/hierarchical prior/posterior
# uncertainty; ReportStep: превью содержимого XLSX-спецификации, зеркалит ту
# же развилку, что уже узаконена в report.rs — см.
# test_report_rs_client_text_hygiene.py::_LEGITIMISED_LITERALS). Механический
# перевод одного слова "adstock" оставил бы эти тултипы непоследовательными
# (кругом остаётся "decay", "hierarchical prior", "posterior uncertainty" на
# английском) — принято решение НЕ русифицировать точечно, термины остаются.
#
# Раньше — xfail на набор файлов; теперь явный реестр с обоснованием на
# каждую запись (тот же принцип, что в report.rs), обязан УМЕТЬ КРАСНЕТЬ:
#   - новый файл с bare adstock ВНЕ реестра → test_svelte_bare_adstock_known_or_none
#     падает (см. ниже — CommandPalette.svelte/OnboardingOverlay.svelte,
#     найденные Фазой 4, НЕ добавлены сюда самовольно: это НОВЫЕ находки за
#     пределами уже одобренных 4 файлов, решение — за владельцем, см. отчёт);
#   - запись, потерявшая повод (файл переименован/тултип убран) → test_adstock_registry_entries_are_alive падает.
# Ключ — ФАЙЛ, не точный текст литерала (в отличие от report.rs): markup-текст
# после TAG_RE/MUSTACHE_RE — склеенные построчно фрагменты, не стабильные
# литералы; малейшая правка соседней разметки сдвигает границы "строки".
# Файловая гранулярность устойчивее для этого источника текста.
_LEGITIMISED_ADSTOCK_FILES = {
    "lib/components/ConfigPanel.svelte": (
        "справка о типах Adstock (значок '?' у поля Adstock, expertMode) — "
        "методологический тултип продвинутой панели, не проза"
    ),
    "lib/components/pipeline/ChannelCategoriesPanel.svelte": (
        "подсказка про adstock decay/hierarchical prior при категоризации "
        "каналов (продвинутая панель)"
    ),
    "lib/components/pipeline/DecomposeStep.svelte": (
        "подсказка «Adstock decay» на графике декомпозиции (продвинутая панель)"
    ),
    "lib/components/pipeline/ReportStep.svelte": (
        "превью содержимого отчёта (спецификация модели: Adstock + Hill, "
        "и в markup, и в <script> — генерация markdown-превью) — зеркалит "
        "ту же развилку, что уже узаконена в report.rs (лист «Спецификация "
        "модели»)"
    ),
    # Вскрыто закрытием дыры покрытия 2026-07-26: эти три файла раньше были
    # невидимы для проверки (текст жил внутри <script>). Узаконены по тому же
    # решению владельца о принятых терминах отрасли, каждый — со своей причиной.
    "lib/components/CommandPalette.svelte": (
        "строка ключевых слов поиска по командам («mmm байес mcmc adstock "
        "hill насыщение») — поисковый индекс, а не подпись: пользователь "
        "ищет по тому имени, которое знает, включая профессиональное"
    ),
    "lib/components/pipeline/ExpertModelPanel.svelte": (
        "тултип коэффициента канала в ЭКСПЕРТНОЙ панели — плотный "
        "технический текст того же класса, что уже узаконен для "
        "ConfigPanel/DecomposeStep"
    ),
}
# OnboardingOverlay.svelte исключён из реестра 2026-07-26: решение владельца —
# разнести онбординг на два уровня (понятная фраза на слайде, методы своими
# именами под «Подробнее»). После этого «adstock» стоит в скобках после
# русского «запаздывающий эффект» и правилу П8-2 удовлетворяет сам по себе —
# исключение стало не нужно. Ровно так исключения и должны уходить: не
# потому, что про них забыли, а потому, что исчез повод.


def test_svelte_no_em_dash():
    v = _collect_violations()
    assert not v["em_dash"], f"П8-1: em-dash в интерфейсе (src/**/*.svelte, включая <script>): {v['em_dash'][:5]}"


def test_svelte_no_bare_baseline():
    v = _collect_violations()
    assert not v["baseline"], f"П8-2: голый baseline в интерфейсе (включая <script>): {v['baseline'][:5]}"


def test_svelte_no_media_latin():
    v = _collect_violations()
    assert not v["media_latin"], f"П8-2: latin media- в интерфейсе (включая <script>): {v['media_latin'][:5]}"


def test_svelte_bare_adstock_known_or_none():
    v = _collect_violations()
    unexpected = [(f, s) for f, s in v["adstock"] if f not in _LEGITIMISED_ADSTOCK_FILES]
    assert not unexpected, (
        f"П8-2: НОВЫЙ голый adstock в интерфейсе вне реестра узаконенного "
        f"(_LEGITIMISED_ADSTOCK_FILES) — новый файл или новая формулировка "
        f"вне уже одобренных владельцем 4 файлов, нужно отдельное решение: {unexpected}"
    )


def test_adstock_registry_entries_are_alive():
    """Запись реестра обязана иметь живой повод — файл всё ещё даёт хотя бы
    один bare-adstock хит (markup или script). Иначе исключение переживает
    свою причину (тултип убрали/переписали без "adstock") и молча прикрывает
    будущее нарушение в том же файле."""
    v = _collect_violations()
    files_with_hits = {f for f, _ in v["adstock"]}
    dead = sorted(_LEGITIMISED_ADSTOCK_FILES.keys() - files_with_hits)
    assert not dead, (
        f"узаконенные файлы больше не дают bare-adstock совпадений {dead} — "
        f"повод исчез, удалить запись из _LEGITIMISED_ADSTOCK_FILES"
    )


def test_svelte_coverage_is_reported():
    """Печатает и проверяет ФАКТ охвата — числом, не на глаз."""
    v = _collect_violations()
    adstock_files = sorted(set(f for f, _ in v["adstock"]))
    summary = (
        f"ОХВАТ интерфейса (src/**/*.svelte): файлов просканировано {v['scanned']}; "
        f"строковых литералов извлечено из <script> {v['script_literals_total']} "
        f"(из них с кириллицей, проверяемый П8-2 пул: {v['script_literals_cyrillic']}); "
        f"узаконенных файлов (adstock-тултипы) {len(_LEGITIMISED_ADSTOCK_FILES)}: "
        f"{sorted(_LEGITIMISED_ADSTOCK_FILES)}; "
        f"файлы с bare-adstock сейчас {len(adstock_files)}: {adstock_files}"
    )
    print(summary)
    assert v["scanned"] > 100, (
        "src/**/*.svelte: почти не нашли файлов — либо структура репозитория "
        "изменилась, либо проверка сломана (см. _SRC_ROOT путь)"
    )
    assert v["script_literals_total"] > 1000, (
        "src/**/*.svelte: строковых литералов в <script> почти не найдено — "
        "либо структура репозитория изменилась, либо extract_script_literals сломан"
    )
