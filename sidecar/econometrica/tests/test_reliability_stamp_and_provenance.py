"""Сторожа единого источника вердикта надёжности и происхождения модели.

Закрывают проверенный дефект 2026-08-07 и его класс.

🔴 ЧТО БЫЛО. `modeler.py` штамповал вердикт надёжности в диагностику на 413 строк
РАНЬШЕ, чем клал в ту же диагностику признак `holidays_excluded`. В файл уезжали
оба поля сразу: верный признак и вердикт, посчитанный так, будто праздники не
исключали. Кто пересчитывал от файла (оптимизатор, мост отчётов) — получал
честный «ориентировочно» с причиной про смещение; кто читал штамп (экраны
«Декомпозиция» и «Оптимизация» до запуска) — получал «надёжна», то есть плашку
не рисовал вовсе. Ошибка была направлена в НЕДОпредупреждение — против чего
честностный гейт INV-50 и существует. Второй путь того же класса:
`tools/recompute_mqs.py` пересчитывал `mqs`/`checks`, а штамп не обновлял.

🔴 ЧЕМУ ЭТО УЧИТ. Вердикт — не шаг обучения, а СВОЙСТВО ЗАПИСИ диагностики.
Отсюда инвариант, который стерегут тесты ниже: штамп ставится последним
действием над словарём, любой писатель диагностики через него проходит, а имя
поля происхождения одинаково понимают обе стороны шва Python — Rust.

Сторожа структурные там, где поведение стоило бы полного прогона обучения
(десятки минут MCMC). Ограничения структурного разбора соблюдены по урокам этой
линии: область — тело нужной функции, а не весь файл; строки берутся по строкам,
не байтовым срезом (в файлах кириллица); строки-комментарии под шаблон не
подпадают, потому что начинаются с решётки.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from utils.optimizer_honesty import model_reliability_verdict, stamp_reliability

_ROOT = Path(__file__).resolve().parents[3]
_ENGINES = _ROOT / "sidecar" / "econometrica" / "engines"
_RUST_REPORT = _ROOT / "src-tauri" / "src" / "commands" / "report.rs"

# Имя поля происхождения. Одно и то же на обоих концах шва — Python пишет,
# Rust читает. Разъедется — разъедется и сверка, молча.
_FINGERPRINT_KEY = "model_fingerprint"

_DIAG_FILE = "model-diagnostics.json"

# Писатели диагностики: файл → как в нём выглядит вызов штампа.
_WRITERS = [
    _ENGINES / "modeler.py",
    _ENGINES / "ols_modeler.py",
    _ROOT / "sidecar" / "econometrica" / "tools" / "recompute_mqs.py",
]

# Мутации словаря диагностики, которые обязаны предшествовать штампу.
# Имя словаря у писателей разное (`diagnostics` у движков, `diag` у пересчёта
# MQS) — берём его из самого вызова штампа, а не угадываем.
_STAMP = re.compile(r"^\s*stamp_reliability\s*\(\s*(\w+)\s*\)")
_DEF = re.compile(r"^def\s+\w+")


def _mutation_re(var: str) -> re.Pattern[str]:
    """Шаблон изменения словаря диагностики.

    🔴 Скобочных групп может быть НЕСКОЛЬКО: внешний аудит показал, что первая
    редакция ловила только `diagnostics['x'] = …` и пропускала вложенное
    `diagnostics['metrics']['x'] = …`. А вложенные ключи — как раз то, что
    вердикт и читает (`metrics`, `checks`, `mqs`), так что дыра была ровно в
    самом чувствительном месте.
    """
    return re.compile(
        rf"^\s*{re.escape(var)}\s*((\[[^\]]+\])+\s*=|\.setdefault\(|\.update\()"
    )


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


# ── 1. Поведение самого штампа ────────────────────────────────────────────


def test_stamp_matches_recomputation_on_same_dict() -> None:
    """После штампа пересчёт по тому же словарю обязан дать тот же вердикт.

    Это и есть «единый источник»: замороженная копия и живой пересчёт совпадают
    по построению, а не по совпадению.

    🔴 Примеры подобраны так, чтобы среди них были НЕ «надёжна». Первая редакция
    этого теста брала только здоровую модель — и пережила мутацию, подменявшую
    вердикт постоянной «надёжна»: подмена случайно совпала с ожидаемым. Сторож,
    у которого ожидаемое значение совпадает с подменой, ничего не стережёт.
    """
    примеры = [
        # здоровая → reliable
        {
            "engine": "bayesian",
            "metrics": {"r_hat_max": 1.0, "divergences": 0, "ratio": 5.0},
            "checks": {"ratio": True},
            "mqs": {"tier": "good", "tier_label": "Хорошее", "score": 70},
        },
        # тонкие данные → uncertain
        {
            "engine": "bayesian",
            "metrics": {"r_hat_max": 1.0, "divergences": 0, "ratio": 2.4},
            "checks": {"ratio": False},
            "mqs": {"tier": "good", "tier_label": "Хорошее", "score": 70},
        },
        # несошедшаяся → unreliable, с отказом от переброски
        {
            "engine": "bayesian",
            "metrics": {"r_hat_max": 1.21, "divergences": 0, "ratio": 6.0},
            "checks": {"ratio": True},
            "mqs": {"tier": "good", "tier_label": "Хорошее", "score": 70},
        },
    ]
    полученные = []
    for diag in примеры:
        stamp_reliability(diag)
        assert diag["model_reliability"] == model_reliability_verdict(diag), (
            "штамп разошёлся с пересчётом по тому же словарю — значит хранимое "
            "значение и вычисляемое перестали быть одним и тем же"
        )
        assert diag["honesty_verdict"] == diag["model_reliability"]["verdict"], (
            "поле совместимости honesty_verdict разошлось с полным диктом"
        )
        полученные.append(diag["honesty_verdict"])

    assert полученные == ["reliable", "uncertain", "unreliable"], (
        f"штамп перестал различать состояния модели: {полученные}. Если все "
        f"значения одинаковы — вердикт подменён постоянной, и плашка надёжности "
        f"клиенту либо всегда рисуется, либо никогда."
    )
    assert примеры[2]["model_reliability"]["refused"] is True, (
        "у несошедшейся модели пропал отказ от переброски бюджета — интерфейс "
        "перестанет прятать рекомендации, которые строить нельзя"
    )


def test_empty_diagnostics_is_left_unstamped() -> None:
    """🔴 Пустую диагностику не штампуем — иначе ломается сам инвариант.

    Простановка полей сделала бы словарь непустым, и повторное вычисление ушло
    бы в другую ветку («диагностика неполна» вместо «диагностики нет»): хранимое
    перестало бы совпадать с вычисляемым. Найдено этим же набором при первой
    сборке — тест равенства покраснел на примере с пустым словарём.
    """
    diag: dict = {}
    stamp_reliability(diag)
    assert diag == {}, (
        f"пустая диагностика проштампована ({sorted(diag)}) — хранимый вердикт "
        f"разойдётся с вычисляемым при первом же пересчёте на стороне моста"
    )


def test_stamp_sees_holidays_flag_when_it_is_present() -> None:
    """🔴 Ядро дефекта: при исключённых праздниках модель НЕ «надёжна».

    Словарь здесь чистый по всем прочим признакам — единственная причина
    оговорки — исключённые праздники. Ровно этот случай экраны продукта и
    пропускали, когда штамп ставился до появления признака.
    """
    diag = {
        "engine": "bayesian",
        "metrics": {"r_hat_max": 1.0, "divergences": 0, "ratio": 6.0},
        "checks": {"ratio": True},
        "mqs": {"tier": "good", "tier_label": "Хорошее", "score": 70},
        "holidays_excluded": True,
    }
    stamp_reliability(diag)
    assert diag["honesty_verdict"] == "uncertain", (
        "при исключённых праздниках вердикт обязан быть «ориентировочно»: "
        "подтвердить отсутствие праздничного эффекта мы не можем, а «надёжна» "
        "означает, что плашку клиенту не рисуют вовсе"
    )
    assert diag["model_reliability"]["caveat_text"], (
        "оговорка пуста — клиенту нечего показать"
    )


def test_stamp_clears_reasons_of_previous_verdict() -> None:
    """Повторный штамп не оставляет причин прошлого вердикта.

    Штамп теперь ставится повторно (после пересчёта MQS), и уцелевший список
    рассказывал бы клиенту о проблеме, которой уже нет.
    """
    diag = {
        "engine": "bayesian",
        "metrics": {"r_hat_max": 1.0, "divergences": 0, "ratio": 2.4},
        "checks": {"ratio": False},
        "mqs": {"tier": "good", "tier_label": "Хорошее", "score": 70},
    }
    stamp_reliability(diag)
    assert diag["honesty_reasons"], "тонкие данные обязаны дать причину"

    diag["checks"] = {"ratio": True}
    diag["metrics"]["ratio"] = 6.0
    stamp_reliability(diag)
    assert diag["honesty_verdict"] == "reliable"
    assert diag["honesty_reasons"] == [], (
        "причины прошлого вердикта пережили повторный штамп — клиент увидит "
        "предупреждение о проблеме, которой больше нет"
    )


# ── 2. Штамп — последнее действие перед записью ───────────────────────────


@pytest.mark.parametrize("path", _WRITERS, ids=[p.name for p in _WRITERS])
def test_stamp_is_the_last_touch_before_write(path: Path) -> None:
    """🔴 Инвариант порядка: сначала собрать диагностику целиком, потом штамп.

    Область разбора — тело той функции, которая пишет файл диагностики. Так
    сторож не спотыкается о соседние функции того же файла.
    """
    lines = _lines(path)

    # Место записи ищем по делу, а не по упоминанию имени: имя файла встречается
    # и в описании модуля, и в комментариях. Берём переменную, которой присвоен
    # путь, и строку, где ЭТУ переменную открывают на запись.
    path_var = next(
        (m.group(1) for m in
         (re.match(rf"\s*(\w+)\s*=\s*.*{re.escape(_DIAG_FILE)}", line) for line in lines)
         if m),
        None,
    )
    assert path_var, (
        f"{path.name} больше не собирает путь к {_DIAG_FILE} в переменную — "
        f"разметка файла переехала, сторож ослеп и его надо чинить, а не отключать"
    )
    write_re = re.compile(rf"open\s*\(\s*{re.escape(path_var)}\s*,\s*['\"]w")
    write_idx = next((i for i, line in enumerate(lines) if write_re.search(line)), None)
    assert write_idx is not None, (
        f"{path.name}: путь к {_DIAG_FILE} собирается в «{path_var}», но эта "
        f"переменная нигде не открывается на запись — сторож ослеп"
    )

    start = 0
    for i in range(write_idx, -1, -1):
        if _DEF.match(lines[i]):
            start = i
            break

    stamp_idx, stamp_var = None, None
    for i in range(start, len(lines)):
        m = _STAMP.match(lines[i])
        if m:
            stamp_idx, stamp_var = i, m.group(1)
            break
    assert stamp_idx is not None, (
        f"{path.name} не вызывает stamp_reliability(...) в функции, которая "
        f"пишет {_DIAG_FILE}. Значит на диск уедет диагностика без вердикта "
        f"надёжности либо с вердиктом, посчитанным где-то раньше по неполным данным."
    )

    mutation = _mutation_re(stamp_var)
    late = [
        (i + 1, lines[i].strip())
        for i in range(stamp_idx + 1, write_idx)
        if mutation.match(lines[i])
    ]
    assert not late, (
        f"в {path.name} словарь диагностики меняется ПОСЛЕ штампа и до записи: "
        f"{late}. Вердикт уедет на диск посчитанным по неполным данным — ровно "
        f"дефект 2026-08-07 (штамп не знал про исключённые праздники, и экраны "
        f"продукта молчали там, где отчёт предупреждал)."
    )
    assert stamp_idx < write_idx, (
        f"в {path.name} штамп стоит ПОСЛЕ записи файла — на диск попадает "
        f"непроштампованная диагностика"
    )


def test_every_writer_of_diagnostics_file_is_covered() -> None:
    """Новый писатель диагностики не должен появиться в обход штампа.

    Сторож ищет по всему движку файлы, которые пишут `model-diagnostics.json`,
    и требует, чтобы каждый из них знал про штамп. Иначе завтра появится
    четвёртый писатель, и класс дефекта вернётся с другой стороны.
    """
    missed = _unstamped_writers(_ROOT / "sidecar" / "econometrica")
    assert not missed, (
        f"файлы пишут {_DIAG_FILE}, но не проходят через stamp_reliability: {missed}. "
        f"Либо проведите запись через штамп, либо внесите файл в список писателей "
        f"этого сторожа осознанно."
    )


def test_writer_detector_actually_detects(tmp_path: Path) -> None:
    """🔴 Сторож писателей проверяет сам себя.

    Без этого он был бы декоративным: список нарушителей пуст и когда всё
    хорошо, и когда поиск сломан. Здесь ему подсовывают заведомого нарушителя
    во временной папке — он обязан его увидеть; и тот же файл со штампом —
    обязан пропустить. Проверка постоянная, а не разовая мутация в репозитории.
    """
    нарушитель = tmp_path / "rogue_writer.py"
    нарушитель.write_text(
        "import json\n"
        "def save(results_dir, diagnostics):\n"
        "    p = results_dir / 'model-diagnostics.json'\n"
        "    with open(p, 'w', encoding='utf-8') as f:\n"
        "        json.dump(diagnostics, f)\n",
        encoding="utf-8",
    )
    assert _unstamped_writers(tmp_path) == ["rogue_writer.py"], (
        "поиск писателей диагностики не увидел заведомого нарушителя — значит "
        "он не увидит и настоящего, а зелёный прогон будет ничего не значить"
    )

    нарушитель.write_text(
        нарушитель.read_text(encoding="utf-8").replace(
            "    with open(p", "    stamp_reliability(diagnostics)\n    with open(p"
        ),
        encoding="utf-8",
    )
    assert _unstamped_writers(tmp_path) == [], (
        "поиск считает нарушителем файл, который штамп вызывает — сторож будет "
        "красным всегда и его отключат"
    )

    # 🔴 Другие естественные формы записи — их первая редакция поиска не видела
    # (нашёл внешний аудит). Каждая обязана быть замечена, иначе новый писатель
    # обойдёт сторожа, просто написав код чуть иначе.
    формы = {
        "inline_open.py": (
            "import json\n"
            "def save(results_dir, diagnostics):\n"
            "    with open(results_dir / 'model-diagnostics.json', 'w') as f:\n"
            "        json.dump(diagnostics, f)\n"
        ),
        "write_text_var.py": (
            "import json\n"
            "def save(results_dir, diagnostics):\n"
            "    p = results_dir / 'model-diagnostics.json'\n"
            "    p.write_text(json.dumps(diagnostics), encoding='utf-8')\n"
        ),
        "write_text_inline.py": (
            "import json\n"
            "def save(results_dir, diagnostics):\n"
            "    (results_dir / 'model-diagnostics.json').write_text(json.dumps(diagnostics))\n"
        ),
    }
    нарушитель.unlink()
    for имя, текст in формы.items():
        (tmp_path / имя).write_text(текст, encoding="utf-8")
    assert sorted(_unstamped_writers(tmp_path)) == sorted(формы), (
        f"поиск не увидел часть форм записи диагностики: ожидались {sorted(формы)}, "
        f"найдено {sorted(_unstamped_writers(tmp_path))}. Новый писатель обойдёт "
        f"сторожа, просто написав запись иначе."
    )


def _unstamped_writers(root: Path) -> list[str]:
    """Файлы под `root`, которые пишут диагностику мимо штампа."""
    known = {p.resolve() for p in _WRITERS}
    missed: list[str] = []

    for py in root.rglob("*.py"):
        if "tests" in py.parts or py.name.startswith("test_"):
            continue
        # `_internal` — выход сборщика PyInstaller, лежащий в дереве. Это копия,
        # а не второй исходник: правится он пересборкой, а не руками.
        if "_internal" in py.parts:
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        if _DIAG_FILE not in text:
            continue
        # Пишет, а не читает: имя файла кладётся в переменную, и ЭТА переменная
        # открывается на запись. Простое совпадение имени в файле ничего не значит —
        # диагностику многие только читают.
        # 🔴 Формы записи, которые надо видеть. Первая редакция знала только
        # «путь в переменную, потом open(переменная, 'w')» — внешний аудит
        # показал, что ни встроенный open с самим именем файла, ни write_text
        # она не замечает, то есть новый писатель прошёл бы мимо неё спокойно.
        writes = False
        # (1) имя файла прямо в open(..., 'w')
        if re.search(rf"open\s*\([^)]*{re.escape(_DIAG_FILE)}[^)]*['\"]w", text):
            writes = True
        for var in re.findall(rf"(\w+)\s*=\s*[^\n]*{re.escape(_DIAG_FILE)}", text):
            v = re.escape(var)
            # (2) путь в переменную, потом open(переменная, 'w')
            if re.search(rf"open\s*\(\s*{v}\s*,\s*['\"]w", text):
                writes = True
            # (3) путь в переменную, потом переменная.write_text(...)
            if re.search(rf"{v}\s*\.\s*write_text\s*\(", text):
                writes = True
        # (4) write_text прямо на выражении с именем файла
        if re.search(rf"{re.escape(_DIAG_FILE)}['\"]?\s*\)?\s*\.\s*write_text\s*\(", text):
            writes = True
        if not writes:
            continue
        if py.resolve() in known:
            continue
        if "stamp_reliability" in text:
            continue
        missed.append(str(py.relative_to(root)))

    return missed


# ── 2а. Проводка признака расхождения: мост и HTML ────────────────────────
#
# Класс Ф-04 этой линии: функция покрыта, а её ВЫЗОВ — нет. Тесты ниже
# проверяют не «умеет ли код сравнивать подписи», а доезжает ли признак от
# файлов до клиентского вывода.


def _builder_data(
    diag_fp: str | None,
    opt_fp: str | None,
    diag_verdict: str | None = None,
    opt_verdict: str | None = None,
) -> dict:
    from engines.narrative_adapter import _map_pipeline_to_builder_data

    diagnostics = {
        "engine": "bayesian",
        "metrics": {"r_hat_max": 1.0, "divergences": 0, "ratio": 6.0, "r_squared": 0.9},
        "checks": {"ratio": True},
        "mqs": {"tier": "good", "tier_label": "Хорошее", "score": 70},
    }
    if diag_fp:
        diagnostics["model_fingerprint"] = diag_fp
    if diag_verdict:
        diagnostics["model_reliability"] = {
            "verdict": diag_verdict, "refused": False,
            "reasons": [], "caveat_text": "оговорка",
        }
    optimize: dict = {}
    if opt_fp:
        optimize["model_fingerprint"] = opt_fp
    if opt_verdict:
        optimize["model_reliability"] = {
            "verdict": opt_verdict, "refused": False,
            "reasons": [], "caveat_text": "оговорка",
        }
    return _map_pipeline_to_builder_data(
        model_data={"diagnostics": diagnostics},
        decompose_data={},
        optimize_data=optimize,
        scenarios=[],
        project_id="проверка",
    )


def test_bridge_raises_provenance_flag_only_on_real_mismatch() -> None:
    """Мост обязан поднять признак при разных подписях и молчать в остальных случаях.

    Молчание на отсутствующих подписях — не мелочь: проекты, обученные до этой
    правки, подписей не имеют, и ложная тревога накрыла бы их все разом.
    """
    from utils.diagnostics import PROVENANCE_MISMATCH_NOTE

    разошлись = _builder_data("a" * 64, "b" * 64)["diagnostics"]
    assert разошлись.get("provenance_mismatch") is True, (
        "мост не заметил, что диагностика и оптимизация от разных моделей — "
        "предупреждение не доедет ни в HTML, ни в презентацию"
    )
    assert разошлись.get("provenance_note") == PROVENANCE_MISMATCH_NOTE, (
        "текст предупреждения на мосту разошёлся с единым источником"
    )

    совпали = _builder_data("c" * 64, "c" * 64)["diagnostics"]
    assert not совпали.get("provenance_mismatch"), (
        "мост поднял тревогу на одной и той же модели — клиент получит "
        "предупреждение там, где всё в порядке"
    )

    for случай, (d, o) in {
        "нет обеих подписей": (None, None),
        "нет подписи оптимизации": ("d" * 64, None),
        "нет подписи модели": (None, "e" * 64),
    }.items():
        assert not _builder_data(d, o)["diagnostics"].get("provenance_mismatch"), (
            f"мост поднял тревогу в случае «{случай}» — все проекты, обученные до "
            f"этой правки, покроются ложным предупреждением"
        )


def test_bridge_catches_stale_verdict_when_model_did_not_change() -> None:
    """🔴 Одной подписи модели мало: пересчёт качества модель не трогает.

    `tools/recompute_mqs.py` пересчитывает качество без переобучения. Диагностика
    меняется, модель — нет, подпись остаётся ПРЕЖНЕЙ. Замороженный вердикт в
    результатах оптимизации при этом устаревает, и расхождение форматов —
    HTML и презентация от свежей диагностики, Markdown и XLSX от старой копии —
    выживает незамеченным. Дыру нашёл внешний аудит, сверка по одной подписи её
    не видела.
    """
    одна_подпись = "f" * 64
    расхождение = _builder_data(
        одна_подпись, одна_подпись, diag_verdict="uncertain", opt_verdict="reliable"
    )["diagnostics"]
    assert расхождение.get("provenance_mismatch") is True, (
        "подписи совпадают, а вердикты разные — сверка обязана сработать: иначе "
        "клиент получит в XLSX «модель надёжна», а в HTML «ориентировочно» по "
        "одной и той же модели"
    )

    совпали = _builder_data(
        одна_подпись, одна_подпись, diag_verdict="uncertain", opt_verdict="uncertain"
    )["diagnostics"]
    assert not совпали.get("provenance_mismatch"), (
        "тревога поднята там, где оба вердикта одинаковы"
    )

    только_в_оптимизации = _builder_data(
        одна_подпись, одна_подпись, opt_verdict="reliable"
    )["diagnostics"]
    assert not только_в_оптимизации.get("provenance_mismatch"), (
        "у проектов, обученных до правки, вердикта в диагностике нет — сравнивать "
        "не с чем, и молчание тут единственно честное поведение"
    )


def test_html_shows_provenance_note_even_when_model_is_reliable() -> None:
    """🔴 В HTML предупреждение обязано пережить ранний выход «модель надёжна».

    Именно здесь его легче всего потерять: функция дисклеймера возвращает пустую
    строку, как только вердикт оказывается надёжным, и предупреждение о разном
    происхождении молча исчезло бы вместе с ней.
    """
    from aurora_html.sections import _reliability_disclaimer_html
    from utils.diagnostics import PROVENANCE_MISMATCH_NOTE

    надёжна_и_расхождение = _reliability_disclaimer_html({
        "diagnostics": {
            "honesty_verdict": "reliable",
            "provenance_mismatch": True,
            "provenance_note": PROVENANCE_MISMATCH_NOTE,
        }
    })
    assert PROVENANCE_MISMATCH_NOTE in надёжна_и_расхождение, (
        "у надёжной модели предупреждение о разном происхождении пропало — "
        "клиент примет числа прошлой модели за нынешние"
    )

    ненадёжна_и_расхождение = _reliability_disclaimer_html({
        "diagnostics": {
            "honesty_verdict": "uncertain",
            "honesty_caveat_text": "оговорка про данные",
            "provenance_mismatch": True,
            "provenance_note": PROVENANCE_MISMATCH_NOTE,
        }
    })
    assert PROVENANCE_MISMATCH_NOTE in ненадёжна_и_расхождение, (
        "предупреждение о происхождении пропало рядом с плашкой надёжности"
    )
    assert "оговорка про данные" in ненадёжна_и_расхождение, (
        "плашка надёжности вытеснена предупреждением о происхождении — они "
        "про разное и обязаны показываться вместе"
    )

    без_расхождения = _reliability_disclaimer_html({
        "diagnostics": {"honesty_verdict": "reliable"}
    })
    assert без_расхождения == "", (
        "у надёжной модели без расхождения происхождения выводить нечего"
    )


def test_reliability_disclaimer_gate_blocks_plaque_when_reliable() -> None:
    """🔴 Гейт «при reliable плашку не рисуем» (ранний выход в
    `_reliability_disclaimer_html`, sections.py) не стерегли ни один тест:
    сняв его probe'ом, зелёными остались все три смежных теста разом. Ловим
    именно класс `reliability-disclaimer` — не пустоту вывода целиком, блок
    `provenance-mismatch` рисуется независимо от вердикта (см. тест выше) и
    трогать его нельзя."""
    from aurora_html.sections import _reliability_disclaimer_html
    from utils.diagnostics import PROVENANCE_MISMATCH_NOTE

    надёжна_без_расхождения = _reliability_disclaimer_html({
        "diagnostics": {"honesty_verdict": "reliable"}
    })
    assert "reliability-disclaimer" not in надёжна_без_расхождения, (
        "у надёжной модели плашка надёжности не должна рисоваться — гейт "
        "снят или обойдён"
    )

    надёжна_с_расхождением = _reliability_disclaimer_html({
        "diagnostics": {
            "honesty_verdict": "reliable",
            "provenance_mismatch": True,
            "provenance_note": PROVENANCE_MISMATCH_NOTE,
        }
    })
    assert "reliability-disclaimer" not in надёжна_с_расхождением, (
        "плашка надёжности не должна появиться у надёжной модели, даже когда "
        "рядом рисуется предупреждение о разном происхождении"
    )
    assert "provenance-mismatch" in надёжна_с_расхождением, (
        "предупреждение о происхождении обязано остаться — гейт reliability "
        "не должен задевать этот независимый блок"
    )


# ── 3. Шов Python — Rust: имя поля происхождения ──────────────────────────


def test_fingerprint_key_is_written_by_python() -> None:
    """Python обязан писать опознаватель модели в оба файла-результата."""
    modeler = (_ENGINES / "modeler.py").read_text(encoding="utf-8")
    ols = (_ENGINES / "ols_modeler.py").read_text(encoding="utf-8")
    optimizer = (_ENGINES / "optimizer.py").read_text(encoding="utf-8")

    # 🔴 Проверяем ПРИСВОЕНИЕ, а не упоминание. Первая редакция этого сторожа
    # искала имя поля как подстроку — и внешний аудит показал, что снятие
    # переноса подписи в optimizer.py оставляет ВЕСЬ набор зелёным: имя всё ещё
    # встречается в соседней строке ЧТЕНИЯ (`_diagnostics.get('model_fingerprint')`)
    # и в пояснении. Вся сверка происхождения умирала молча. Тот же класс, что
    # «наличие вызова не означает, что результат используется».
    for name, text in (("modeler.py", modeler), ("ols_modeler.py", ols)):
        assert re.search(rf"diagnostics\[['\"]{_FINGERPRINT_KEY}['\"]\]\s*=", text), (
            f"{name} не ПРИСВАИВАЕТ {_FINGERPRINT_KEY} в диагностику — отчёт не "
            f"сможет понять, на какой модели посчитаны показанные числа"
        )
    assert re.search(rf"result_data\[['\"]{_FINGERPRINT_KEY}['\"]\]\s*=", optimizer), (
        "optimizer.py не ПЕРЕНОСИТ опознаватель модели в результат оптимизации — "
        "сверка происхождения на стороне отчёта становится невозможной, и при этом "
        "ничего не падает: именно так эта дыра и пряталась от первой редакции сторожа"
    )
    assert re.search(r"result_data\[['\"]model_reliability['\"]\]\s*=", optimizer), (
        "optimizer.py не кладёт вердикт надёжности в результат оптимизации — "
        "Markdown и XLSX останутся без плашки надёжности вовсе"
    )


def test_provenance_note_is_mirrored_word_for_word_in_rust() -> None:
    """🔴 Зеркало текста предупреждения: Python пишет — Rust повторяет дословно.

    Rust не импортирует Python и собирает Markdown и XLSX сам, поэтому текст
    физически существует дважды. Пока сверки не было, такие пары в этой линии
    расходились молча: два комментария обещали «тест сверяет», а теста не
    существовало. Сравнение побайтовое и намеренно строгое — расхождение в
    тире или пробеле означает, что клиент получит в разных файлах разные
    формулировки об одном и том же.
    """
    from utils.diagnostics import PROVENANCE_MISMATCH_NOTE

    m = re.search(
        r'FINGERPRINT_MISMATCH_TEXT\s*:\s*&str\s*=\s*"([^"]*)"', _rust_product_code()
    )
    assert m, (
        "в продакшн-коде report.rs не найдена строковая постоянная "
        "FINGERPRINT_MISMATCH_TEXT — Rust либо перестал предупреждать о разном "
        "происхождении, либо собирает текст иначе и зеркало больше не проверяется"
    )
    assert m.group(1) == PROVENANCE_MISMATCH_NOTE, (
        "текст предупреждения о разном происхождении разошёлся между Python и Rust.\n"
        f"Python: {PROVENANCE_MISMATCH_NOTE!r}\n"
        f"Rust:   {m.group(1)!r}\n"
        "Клиент получит в HTML и PPTX одну формулировку, а в Markdown и XLSX другую."
    )
    assert "—" not in PROVENANCE_MISMATCH_NOTE, (
        "в клиентском тексте длинное тире — в этом продукте принято короткое «–»"
    )


def test_fingerprint_key_is_read_by_rust() -> None:
    """🔴 Сторож на ВТОРОМ конце шва: Rust обязан читать то же имя поля.

    Односторонний сторож не только пропускает дефект на неохраняемой стороне —
    он превращает добросовестное зеркалирование в занос нарушения на охраняемую.
    Поэтому имя поля стережётся с обеих сторон.
    """
    assert f'"{_FINGERPRINT_KEY}"' in _rust_product_code(), (
        f"продакшн-код report.rs не читает поле {_FINGERPRINT_KEY}: сверка "
        f"происхождения не выполняется, и отчёт молча смешает диагностику одной "
        f"модели с числами оптимизации другой"
    )


def _rust_product_code() -> str:
    """Код продукта из report.rs: без тестового модуля и БЕЗ КОММЕНТАРИЕВ.

    🔴 Обе отрезки обязательны, и обе выучены на ошибках этой линии. Тестовый
    модуль отрезается, иначе сторож находит образцы в тексте собственных тестов
    и остаётся зелёным при вырезанной проводке. Комментарии отрезаются, иначе
    сторож находит СОБСТВЕННОЕ ОБЪЯСНЕНИЕ: первая редакция этого теста искала
    имя поля во всём файле, а оно упоминается в пояснении к функции сверки —
    мутация, переименовавшая поле во всём коде, теста не уронила.
    """
    src = _RUST_REPORT.read_text(encoding="utf-8")
    marker = src.find("#[cfg(test)]")
    product = src if marker == -1 else src[:marker]
    return "\n".join(
        line for line in product.splitlines() if not line.lstrip().startswith("//")
    )
