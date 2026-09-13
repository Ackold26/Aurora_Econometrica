"""Сторож распознавания макропоказателей как контрольных факторов (14.09.2026).

Владелец попросил учитывать внешние факторы — курс валют, ключевую ставку,
индекс потребительских цен. Механизм для этого уже был (контрольные колонки),
не хватало имён: юаня и ключевой ставки.

🔴 Сторож проверяет ДВА детектора сразу. В проекте их два — `detect_column_role`
(плоские подстроки) и `classify_column` (регулярки с классом разделителей), — и
они уже расходились: аудит 2026-07-05 нашёл, что клиент со столбцом «Период»
получал «не найден столбец с датами», потому что русскую форму знал только один
из них. Добавляя имя в один список и забыв про другой, мы воспроизведём ровно
этот дефект, причём молча.

🔴 Отрицательный контроль здесь важнее положительного: голые признаки («cny»,
«ставка», «курс») ловят чужое — «Digital CNY» это медийный бюджет в валюте,
«Ставка НДС» вообще не про деньги рекламы, а «дискурс» содержит «курс» внутри
слова. Если такой столбец уедет в контроли, модель отдаст ему вклад медиа, и
ROI занизится молча.
"""
from __future__ import annotations

import pytest

from engines.validator import detect_column_role, detect_column_role_with_confidence
from utils.column_detection import classify_column


# Макропоказатели: обязаны распознаваться КАК КОНТРОЛЬ обоими детекторами.
MACRO_COLUMNS = [
    "Курс юаня", "курс_юаня", "курс-юаня",
    "CNY_RUB", "cny rub", "cny-rub",
    "Ключевая ставка", "ключевая_ставка", "ключевая-ставка",
    "Ставка ЦБ", "ставка_цб",
    "key_rate", "key rate", "key-rate",
    # были и раньше — закрепляем, чтобы не пропали при чистке списка
    "Курс доллара", "usd_rub", "eur_rub", "exchange_rate",
    "ИПЦ", "инфляция", "cpi",
    # полное русское название — 14.09.2026 не распознавалось вовсе
    "Индекс потребительских цен", "индекс_потребительских_цен",
]

# Контрольные категории второго детектора: макро и цена — обе контрольные со
# знаком, различие смысловое, не механическое. `consumer_price` попадает в
# signed_price (слово «price» проверяется раньше) — на модель это не влияет,
# поэтому сторож требует «любая контрольная», а не точное имя категории.
CONTROL_KINDS = {"signed_macro", "signed_price"}

# Ловушки: НЕ должны попасть в контроли.
NOT_CONTROL = [
    ("ТВ бюджет CNY", "медийный бюджет в валюте"),
    ("Digital spend USD", "медийный бюджет в валюте"),
    ("Ставка НДС", "налоговая ставка, не ключевая"),
    ("Дискурс бренда", "«курс» внутри слова"),
    ("Экскурсия по заводу", "«курс» внутри слова"),
]


@pytest.mark.parametrize("column", MACRO_COLUMNS)
def test_macro_column_is_control_in_validator(column):
    """Первый детектор относит макропоказатель к контрольным факторам."""
    role, confidence = detect_column_role_with_confidence(column)
    assert role == "control", (
        f"«{column}» → {role} вместо control. Такой столбец не попадёт в модель "
        f"контролем, и его влияние достанется медиа (смещение пропущенной переменной)."
    )
    assert confidence >= 0.5, f"«{column}»: уверенность {confidence} слишком низкая"


@pytest.mark.parametrize("column", MACRO_COLUMNS)
def test_macro_column_is_control_in_classifier(column):
    """Второй детектор согласен с первым — иначе рассинхрон, как было с «Период»."""
    kind = classify_column(column)
    assert kind in CONTROL_KINDS, (
        f"«{column}» → {kind}, не контрольная категория. Детекторы разошлись: "
        f"validator видит контроль, classify_column — нет."
    )


@pytest.mark.parametrize("column,why", NOT_CONTROL)
def test_lookalike_column_is_not_control(column, why):
    """Отрицательный контроль: похожее имя НЕ уводит столбец в контроли.

    Проверяются оба детектора. Медийный бюджет в валюте обязан остаться медиа
    (у validator при равенстве совпадений медиа выигрывает у контроля), а
    налоговая ставка и слова с «курс» внутри — не распознаваться вовсе.
    """
    role = detect_column_role(column)
    assert role != "control", f"«{column}» ушёл в контроли ({why})"

    kind = classify_column(column)
    assert kind not in CONTROL_KINDS, f"«{column}» распознан как контрольный ({why})"


def test_both_detectors_agree_on_every_macro_name():
    """Ни одного имени, которое знает только один детектор.

    Именно эта проверка ловит будущую правку «добавил в один список и забыл про
    второй»: она перебирает весь набор и требует согласия, а не проверяет
    каждое имя по отдельности.
    """
    disagreements = []
    for column in MACRO_COLUMNS:
        role = detect_column_role(column)
        kind = classify_column(column)
        if (role == "control") != (kind in CONTROL_KINDS):
            disagreements.append(f"{column}: validator={role}, classify={kind}")
    assert not disagreements, "детекторы разошлись:\n  " + "\n  ".join(disagreements)
