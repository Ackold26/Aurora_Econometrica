"""Типографский канон линейки на клиентских поверхностях (2026-07-26).

Канон записан в стандарте формата отчёта (§3 «правило двух строк», §5
«типографика»): одинокого слова на строке быть не должно, длинная проза
держится в читаемой мере, заголовок не ломается ступенькой в одно слово.
До этой правки в Econometrica не было применено ничего из перечисленного.

Проверка держит ДВЕ вещи, которые молча разъезжаются:
1. канон объявлен и в интерфейсе, и в КАЖДОМ файле справки — справку легко
   забыть, она правится реже и отдельными файлами (общего файла стилей у
   неё нет, каждый несёт свой блок);
2. селекторы меры строки не мертвы — класс, которого нет в разметке,
   создаёт видимость канона там, где его нет. Ровно на этом здесь уже
   ошиблись: первые селекторы были взяты из соседнего продукта.
"""
import os
import re

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
# tests → econometrica → sidecar → корень репозитория (три уровня, не два).
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_APP_CSS = os.path.join(_ROOT, "src", "app.css")
_HELP_DIR = os.path.join(_ROOT, "src-tauri", "help")
_SRC_DIR = os.path.join(_ROOT, "src")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _measure_selectors():
    """Классы из правила меры строки в app.css — как они там записаны."""
    css = _read(_APP_CSS)
    m = re.search(r"([^{}]*)\{\s*max-inline-size:\s*68ch", css)
    assert m, "правило меры строки (max-inline-size: 68ch) не найдено в app.css"
    return re.findall(r"\.([a-zA-Z][\w-]*)", m.group(1))


def test_interface_declares_canon():
    css = _read(_APP_CSS)
    assert re.search(r"body\s*\{[^}]*text-wrap:\s*pretty", css, re.S), (
        "в app.css нет `text-wrap: pretty` на body — вдовы в интерфейсе не лечатся"
    )
    assert re.search(r"h1[^{]*\{[^}]*text-wrap:\s*balance", css, re.S), (
        "в app.css нет `text-wrap: balance` на заголовках — заголовок ломается ступенькой"
    )


def test_measure_selectors_are_alive():
    """Каждый класс меры строки реально встречается в разметке."""
    selectors = _measure_selectors()
    assert selectors, "список селекторов меры строки пуст"
    markup = []
    for root, _dirs, files in os.walk(_SRC_DIR):
        for name in files:
            if name.endswith(".svelte"):
                markup.append(_read(os.path.join(root, name)))
    blob = "\n".join(markup)
    dead = [c for c in selectors if not re.search(rf'class="[^"]*\b{re.escape(c)}\b', blob)]
    assert not dead, (
        f"мёртвые селекторы меры строки {dead} — класса нет ни в одном компоненте, "
        f"правило создаёт видимость канона"
    )


def _help_pages():
    if not os.path.isdir(_HELP_DIR):
        return []
    return sorted(
        os.path.join(_HELP_DIR, n) for n in os.listdir(_HELP_DIR) if n.endswith(".html")
    )


def test_help_pages_exist():
    """Страховка от тихого нуля: пустой список файлов дал бы зелёный охват."""
    pages = _help_pages()
    assert len(pages) >= 10, (
        f"страниц справки найдено {len(pages)} — каталог переехал или проверка сломана"
    )


@pytest.mark.parametrize("page", _help_pages(), ids=os.path.basename)
def test_help_page_declares_canon(page):
    html = _read(page)
    assert "text-wrap: pretty" in html, (
        f"{os.path.basename(page)}: нет канона типографики — страница правилась "
        f"или создавалась мимо стандарта"
    )
    assert "text-wrap: balance" in html, (
        f"{os.path.basename(page)}: заголовки без balance"
    )


def test_help_coverage_is_reported(capsys):
    """Охват печатается числом — молчаливое сужение отсюда невозможно."""
    pages = _help_pages()
    with_canon = [p for p in pages if "text-wrap: pretty" in _read(p)]
    summary = (
        f"ОХВАТ типографского канона: интерфейс — app.css; "
        f"справка — {len(with_canon)} страниц из {len(pages)}; "
        f"селекторов меры строки {len(_measure_selectors())}"
    )
    print(summary)
    assert len(with_canon) == len(pages), summary
