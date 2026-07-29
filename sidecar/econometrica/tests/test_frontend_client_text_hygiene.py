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

Фаза 5 (2026-07-29): закрыта дыра охвата ФАЙЛОВОГО ТИПА — _iter_svelte_files()
брал только *.svelte, и src/**/*.js (бизнес-логика, не разметка — главный
источник insights-rules.js с сотнями сообщений выводов MMM) не проверялся
НИКЕМ вообще, включая П8-1. Собственный замер на момент правки: 370
точечных находок (em-dash + дефис-между-пробелами) в 15 production-файлах,
исправлены до внесения гейта (durable-отчёт: exec_econ_typography_report.md).

Заодно заведено П8-4 (дефис-минус между пробелами вместо короткого тире «–») —
для .js этой проверки не было вовсе ни здесь, ни где-либо на фронтенде (была
только в test_report_rs_client_text_hygiene.py для report.rs). Тот же корень,
что уже описан там: признак поиска (только длинное тире) не совпадал с
классом дефекта (неверный знак тире вообще).

Литералы .js НЕ извлекаются регэкспом backtick-в-backtick (как
extract_script_literals выше) — сознательно другая механика. Причина: в этом
файле есть строки с ВЛОЖЕННЫМ template literal внутри ${...}-интерполяции
(`` `текст ${cond ? `внутренний ${x} литерал` : 'иначе'} текст` ``,
insights-rules.js:626 и рядом) — нежадный `` `((?:[^`\\]|\\.)*)` `` останавливается
на ПЕРВОЙ внутренней открывающей кавычке чужого вложенного литерала, а не на
своей закрывающей, и рвёт один логический литерал на мусорные фрагменты
(доказано боем при замере: JS-арифметика `${x - 4}` внутри вложенного
тернарника утекала как «находка» П8-4, хотя это код, не текст). Вместо
литерал-экстракции здесь построчный скан ПОСЛЕ вычитания комментариев (та же
эвристика, что в _strip_script_line_comments/_BLOCK_COMMENT_RE выше) с
подсчётом глубины скобок ТОЛЬКО для ${...} (_interp_spans — держит границу
интерполяции, не границу литерала целиком, поэтому вложенные backtick её не
путают) — совпадение внутри такого диапазона размечается как код и в П8-1/
П8-4 не идёт. Компромисс лёгкого инструмента: логический литерал, перенесённый
через физическую СТРОКУ (не через `+`-конкатенацию отдельными строками — та
уже ловится, у каждой свой физический перенос), вне охвата — на практике в
этом файле такого не встретилось (все найденные клиентские сообщения умещены
в одну физическую строку), задокументировано, не замаскировано.

Обе проверки (П8-1 и П8-4) для .js, как и П8-2 выше, ограничены строками с
кириллицей — без неё строка почти всегда код (арифметика, regex, ключи), а
не клиентский текст; тот же выбор координатора, что и для П8-2.
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


# ══════════════════════════════════════════════════════════════════════════
# Фаза 5 (2026-07-29): охват src/**/*.js — П8-1 (em-dash) + П8-4 (дефис-минус
# между пробелами вместо короткого тире «–»). См. докстринг модуля выше для
# обоснования механики (построчный скан + _interp_spans, не литерал-экстракция).
# ══════════════════════════════════════════════════════════════════════════

SPACED_HYPHEN_RE = re.compile(r"(?<=\S) - (?=\S)")

# Каталоги тестовой обвязки разработчика — не клиентский код, вне охвата (тот
# же принцип, что "код до #[cfg(test)]" в test_report_rs_client_text_hygiene.py).
_JS_TEST_DIR_SEGMENTS = {"__tests__", "tests"}


def _iter_js_files():
    for dirpath, dirnames, filenames in os.walk(_SRC_ROOT):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".svelte-kit")]
        rel_dir = os.path.relpath(dirpath, _SRC_ROOT).replace(os.sep, "/")
        parts = set(rel_dir.split("/"))
        if parts & _JS_TEST_DIR_SEGMENTS:
            continue
        for name in filenames:
            if name.endswith(".js") and not name.endswith(".test.js"):
                yield os.path.join(dirpath, name)


def _interp_spans(text):
    """Диапазоны ${...} в JS-тексте — счётчик глубины фигурных скобок, НЕ
    regex-разбор границ template literal целиком (см. докстринг модуля: тот
    подход рвётся на вложенном backtick внутри интерполяции). Работает и на
    вложенных ${...}, и на объектных литералах внутри интерполяции
    (`${{a: 1}}`-подобных) — считает любые { } после `${`."""
    spans = []
    i, n = 0, len(text)
    while i < n:
        if text[i] == "$" and i + 1 < n and text[i + 1] == "{":
            depth = 1
            j = i + 2
            while j < n and depth > 0:
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                j += 1
            spans.append((i, j))
            i = j
        else:
            i += 1
    return spans


# Узаконенные строки (по ТЕКСТУ, не по номеру строки — та же причина, что у
# всех реестров выше: номера сползают при правках). Обе записи — реальные
# строки с кириллицей и дефисом/тире, но НЕ клиентский текст:
_LEGITIMISED_JS_LITERALS = {
    "защита от ROI-артефакта": (
        "project-state.js: тело console.warn() — уходит в devtools-консоль "
        "разработчика, пользователь этот текст не видит ни при каких условиях"
    ),
    '"delta_pct":<число: + увеличить, - уменьшить>': (
        "scenario-advisor.js (buildScenarioParsePrompt): элемент JSON-schema "
        "инструкции, уходит в промпт для Claude (описание формата ответа "
        "модели) — не клиентский текст, пользователь его не видит"
    ),
}


def _collect_js_violations():
    em, hyphen = [], []
    scanned = 0
    raw_em_occurrences = 0
    raw_hyphen_occurrences = 0
    for path in _iter_js_files():
        scanned += 1
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        rel = _relpath(path)
        # Вычитание комментариев — та же механика, что для <script>-блока
        # .svelte выше (переиспользуем _BLOCK_COMMENT_RE/_strip_script_line_comments:
        # общая JS-грамматика, файл .js не отличается от содержимого <script>).
        code = _BLOCK_COMMENT_RE.sub(" ", content)
        code = _strip_script_line_comments(code)
        for lineno, line in enumerate(code.split("\n"), start=1):
            raw_em_occurrences += len(EM_DASH_RE.findall(line))
            raw_hyphen_occurrences += len(SPACED_HYPHEN_RE.findall(line))
            if not CYRILLIC_RE.search(line):
                continue
            spans = _interp_spans(line)

            def _in_interp(pos, _spans=spans):
                return any(s <= pos < e for s, e in _spans)

            legit = next((k for k in _LEGITIMISED_JS_LITERALS if k in line), None)
            for m in EM_DASH_RE.finditer(line):
                if _in_interp(m.start()):
                    continue
                if legit:
                    continue
                em.append((rel, lineno, line.strip()[:140]))
            for m in SPACED_HYPHEN_RE.finditer(line):
                if _in_interp(m.start()):
                    continue
                if legit:
                    continue
                hyphen.append((rel, lineno, line.strip()[:140]))
    return {
        "scanned": scanned,
        "raw_em_occurrences": raw_em_occurrences,
        "raw_hyphen_occurrences": raw_hyphen_occurrences,
        "em_dash": em,
        "spaced_hyphen": hyphen,
    }


def test_js_no_em_dash():
    v = _collect_js_violations()
    assert not v["em_dash"], (
        f"П8-1: em-dash «—» в клиентском тексте src/**/*.js (не .svelte): {v['em_dash'][:10]}"
    )


def test_js_no_spaced_hyphen_as_dash():
    """П8-4: дефис-минус между пробелами вместо короткого тире «–» — та же
    проверка, что для report.rs (test_rs_report_no_spaced_hyphen_as_dash), но
    для .js фронтенда, где её не было вовсе."""
    v = _collect_js_violations()
    assert not v["spaced_hyphen"], (
        f"П8-4: дефис между пробелами вместо короткого тире «–» в src/**/*.js: {v['spaced_hyphen'][:10]}"
    )


def test_js_legitimised_literals_are_alive():
    """Запись реестра обязана иметь живой повод, иначе исключение переживает
    свою причину и молча прикрывает будущее нарушение с тем же текстом."""
    v = _collect_js_violations()
    # Пересобираем raw-совпадения БЕЗ фильтра по реестру, чтобы проверить,
    # какие строки реестр вообще мог бы накрыть (тот же скан, без `if legit`).
    present = set()
    for path in _iter_js_files():
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        code = _strip_script_line_comments(_BLOCK_COMMENT_RE.sub(" ", content))
        for key in _LEGITIMISED_JS_LITERALS:
            if key in code:
                present.add(key)
    dead = sorted(set(_LEGITIMISED_JS_LITERALS) - present)
    assert not dead, (
        f"узаконенные литералы .js больше не встречаются {dead} — "
        f"повод исчез, удалить запись из _LEGITIMISED_JS_LITERALS"
    )


def test_js_coverage_is_reported():
    """Печатает и проверяет ФАКТ охвата — числом, не на глаз.

    🔴 Страховка от тихого нуля (тот же приём, что rawDashOccurrences в
    Aurora_Creative_Hub/client-typography.coverage.test.js и checked_lines в
    test_report_rs_client_text_hygiene.py): raw_em_occurrences/raw_hyphen_occurrences
    считаются ДО фильтра по кириллице и ДО реестра исключений — если оба нуля,
    сканер смотрит не туда (маска расширений устарела, каталог переехал, регэксп
    сломан), а НЕ «в коде нет дефисов». Реестр из двух записей теоретически МОГ
    БЫ закрыть все текущие находки (assert выше стал бы зелёным «сверено 0») —
    эта проверка не даёт такому зелёному пройти незамеченным: raw-счётчики не
    ходят через реестр вообще, поэтому broad-реестр их не занулит.
    """
    v = _collect_js_violations()
    summary = (
        f"ОХВАТ src/**/*.js (без __tests__/tests/*.test.js): "
        f"файлов просканировано {v['scanned']}; "
        f"raw-вхождений «—» до фильтра {v['raw_em_occurrences']}, "
        f"raw-вхождений дефис-между-пробелами до фильтра {v['raw_hyphen_occurrences']}; "
        f"узаконенных строк {len(_LEGITIMISED_JS_LITERALS)}"
    )
    print(summary)
    assert v["scanned"] > 50, (
        "src/**/*.js: почти не нашли файлов — либо структура репозитория "
        "изменилась (каталог src переехал), либо маска расширений устарела "
        "(см. _iter_js_files)"
    )
    assert v["raw_em_occurrences"] > 0, (
        "src/**/*.js: ни одного «—» не найдено НИГДЕ (до фильтра по кириллице) — "
        "сканер смотрит не туда, а не «в коде нет длинных тире»"
    )
    assert v["raw_hyphen_occurrences"] > 0, (
        "src/**/*.js: ни одного дефиса-между-пробелами не найдено НИГДЕ (до "
        "фильтра по кириллице) — сканер смотрит не туда (SPACED_HYPHEN_RE или "
        "маска расширений сломаны), а не «в коде нет таких дефисов»"
    )
