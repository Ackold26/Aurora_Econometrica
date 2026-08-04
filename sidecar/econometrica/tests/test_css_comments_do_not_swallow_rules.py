"""Сторож: комментарий в CSS не должен съедать правила.

Найдено внешним аудитом 2026-08-04 в `src/aurora-ui-alias.css`. В шапке файла
перечисление групп токенов записали через косую черту сразу после звёздочки —
и эта пара символов ЗАКРЫЛА блочный комментарий досрочно. Всё, что шло дальше,
парсер прочитал как селектор, и блок `:root` из 29 переменных отбросился
целиком. Проба в браузере на СОБРАННОМ css подтвердила: значение переменной
пусто, правил с этим селектором в `cssRules` ноль.

🔴 Почему это не поймал никто: файл ИМПОРТИРУЕТСЯ, сборка проходит, проверка
типов молчит, тесты зелёные. Мёртвым он был ровно в той роли, ради которой
заведён, а поскольку канон-namespace в продукте пока не используется, видимого
дефекта не возникало. Классический «зелёный гейт над неработающим кодом».

Сторож дешёвый и структурный: считает баланс открытий и закрытий комментария и
проверяет, что объявления переменных не оказались внутри комментария.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_CSS_DIR = _ROOT / "src"

# Файлы, которые несут переменные темы. Держим списком, а не глобом по всему
# дереву: в src/ лежат и сторонние стили, чей формат нас не касается.
_WATCHED = [
    _CSS_DIR / "aurora-ui-alias.css",
    _CSS_DIR / "app.css",
]


def _existing() -> list[Path]:
    return [p for p in _WATCHED if p.exists()]


@pytest.mark.parametrize("path", _existing(), ids=lambda p: p.name)
def test_comment_markers_balanced(path: Path) -> None:
    """Открытий блочного комментария столько же, сколько закрытий.

    Дисбаланс означает, что либо комментарий не закрыт (и съел остаток файла),
    либо закрыт лишний раз (и часть пояснения стала кодом).
    """
    src = path.read_text(encoding="utf-8")
    opens = src.count("/*")
    closes = src.count("*/")
    assert opens == closes, (
        f"{path.name}: открытий блочного комментария {opens}, закрытий {closes}. "
        f"Несовпадение означает, что часть файла проглочена комментарием или "
        f"часть комментария утекла в CSS как мусорный селектор."
    )


@pytest.mark.parametrize("path", _existing(), ids=lambda p: p.name)
def test_declared_variables_survive_comment_stripping(path: Path) -> None:
    """Объявления переменных не должны исчезать при вырезании комментариев.

    Именно этим отличается «файл выглядит правильно» от «файл работает»:
    браузер сначала вырезает комментарии, и только потом разбирает правила.
    """
    src = path.read_text(encoding="utf-8")
    stripped = re.sub(r"/\*.*?\*/", "", src, flags=re.S)

    pattern = r"--[a-z0-9-]+\s*:"
    total = len(re.findall(pattern, src))
    live = len(re.findall(pattern, stripped))

    if total == 0:
        pytest.skip(f"{path.name}: объявлений переменных нет — стеречь нечего")

    # Часть вхождений законно живёт в пояснениях; сигнал тревоги — когда
    # комментарии съедают заметную долю объявлений.
    assert live >= total * 0.5, (
        f"{path.name}: из {total} объявлений переменных до парсера доходит лишь "
        f"{live}. Похоже, блочный комментарий закрылся раньше времени и проглотил "
        f"правила — ровно тот дефект, из-за которого aurora-ui-alias.css был мёртв."
    )


def test_alias_file_delivers_canon_namespace() -> None:
    """Целевая проверка: мост канон-namespace реально отдаёт переменные.

    Смысл файла — отдать `--ui-*` и `--brand-*`. Если после вырезания
    комментариев их не осталось, мост не работает, чем бы файл ни выглядел.
    """
    path = _CSS_DIR / "aurora-ui-alias.css"
    if not path.exists():
        pytest.skip("aurora-ui-alias.css отсутствует")

    stripped = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)

    assert ":root" in stripped, (
        "aurora-ui-alias.css: блок :root не дошёл до парсера — он внутри "
        "комментария. Мост канон-namespace мёртв."
    )
    live = len(re.findall(r"--(?:ui|brand)-[a-z0-9-]+\s*:", stripped))
    assert live >= 20, (
        f"aurora-ui-alias.css: до парсера доходит лишь {live} переменных "
        f"канон-namespace (ожидается около 30). Проверьте, не закрылся ли "
        f"комментарий досрочно."
    )
