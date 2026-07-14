"""Канарейка паритета ДВУХ детекторов ролей колонок (B2, 2026-07-05).

Мотивация — класс Д-1 (самоаудит №5 пакета примеров): в программе два
независимых детектора семантики колонок, и они РАЗОШЛИСЬ на именах примеров:

  * utils.column_detection.classify_column → тонкий `kind`
    (monetary / physical / signed_* / category / target_* / date / control …)
    — используется modeler'ом для выбора Bayesian prior.
  * engines.validator.detect_column_role → грубая `role`
    (media / control / kpi / date / unused / unknown)
    — используется /validate endpoint'ом для роли в UI (Traffic Light).

`apteka_contacts` знал classify_column (physical), а validator — нет (→ unknown),
и колонка «падала» в примере OTC. Классификаторы правились в разных местах и
раз-синхронизировались молча: юнит каждого по отдельности был зелёным.

Этот тест — трип-проволока на будущий рассинхрон. Для КАЖДОГО имени колонки из
served-примеров (EXPECTED_SCHEMA — один SSOT с ssot-гейтом) проверяем, что грубая
`role` validator'а согласуется с тонким `kind` classify_column через таблицу
KIND_TO_ROLE ниже. Если кто-то добавит колонку/паттерн в один детектор и забудет
второй — тест краснеет с указанием колонки, не у клиента в «Попробовать на примере».

NB: тест НЕ дублирует test_sample_data_ssot.test_columns_recognized_and_correct_role
(тот сверяет classify_column с задуманным kind). Здесь — ортогональная ось:
СОГЛАСОВАННОСТЬ двух детекторов между собой на тех же именах.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SIDECAR = _REPO / 'sidecar' / 'econometrica'
_TOOLS = _REPO / 'tools'
for _p in (str(_SIDECAR), str(_TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from utils.column_detection import classify_column  # noqa: E402
from engines.validator import detect_column_role     # noqa: E402
from test_sample_data_ssot import EXPECTED_SCHEMA     # noqa: E402

# ── Контракт соответствия тонкого kind → грубой role ────────────────────────
# Читается так: «какую роль validator ОБЯЗАН вернуть, если classify_column
# определил колонку как <kind>». Меняется ТОЛЬКО осознанно, парой с обоими
# детекторами. Любой kind, встречающийся в примерах, должен здесь присутствовать
# (иначе test_mapping_covers_all_kinds краснеет — silent '???' не проскочит).
#   media   ← медиа-вход (бюджет ₽ ИЛИ натуральный Media KPI пары)
#   control ← любой контроль-фактор (signed_*, holiday, seasonality, category,
#             positive control) — все идут в control_columns модели
#   kpi     ← целевая метрика (в ₽ или в штуках)
#   date    ← ось времени
KIND_TO_ROLE = {
    'date': 'date',
    'target_monetary': 'kpi',
    'target_count': 'kpi',
    'monetary': 'media',
    'physical': 'media',
    'control': 'control',
    'signed_competitor': 'control',
    'signed_price': 'control',
    'signed_weather': 'control',
    'signed_macro': 'control',
    'holiday': 'control',
    'seasonality': 'control',
    'category': 'control',
}

# Все уникальные имена колонок served-примеров + пример-файл (для навигации).
# Детектор — чистая функция имени, поэтому дедуп по имени корректен.
_SEEN: dict[str, str] = {}
for _fname, _schema in EXPECTED_SCHEMA.items():
    for _col in _schema:
        _SEEN.setdefault(_col, _fname)

SAMPLE_COLUMNS = sorted(_SEEN)


@pytest.mark.parametrize('col', SAMPLE_COLUMNS)
def test_detectors_agree_on_role(col):
    """Грубая role validator'а согласуется с тонким kind classify_column."""
    kind = classify_column(col)
    assert kind in KIND_TO_ROLE, (
        f'{col} (пример {_SEEN[col]}): classify_column вернул kind={kind!r}, '
        f'которого нет в KIND_TO_ROLE — обнови контракт паритета осознанно'
    )
    expected_role = KIND_TO_ROLE[kind]
    role = detect_column_role(col)
    assert role == expected_role, (
        f'РАССИНХРОН детекторов на {col!r} (пример {_SEEN[col]}): '
        f'classify_column→kind={kind!r} ожидает role={expected_role!r}, '
        f'но validator.detect_column_role вернул {role!r}. '
        f'Правь оба детектора парой (utils/column_detection.py + engines/validator.py).'
    )


@pytest.mark.parametrize('col', SAMPLE_COLUMNS)
def test_no_orphan_role(col):
    """Ни одна колонка примера не должна быть unknown/unused (обе — сигнал битой
    детекции: unknown = не распознана, unused = ошибочно отброшена как derived)."""
    role = detect_column_role(col)
    assert role in ('date', 'kpi', 'media', 'control'), (
        f'{col!r} (пример {_SEEN[col]}): validator дал role={role!r} — '
        f'колонка served-примера не должна отбрасываться/теряться'
    )


def test_mapping_covers_all_kinds():
    """Каждый kind, реально встречающийся в примерах, покрыт KIND_TO_ROLE."""
    kinds_in_use = {classify_column(c) for c in SAMPLE_COLUMNS}
    uncovered = kinds_in_use - set(KIND_TO_ROLE)
    assert not uncovered, (
        f'kinds примеров без записи в KIND_TO_ROLE: {uncovered} — '
        f'добавь соответствие role осознанно'
    )


if __name__ == '__main__':
    # Standalone-прогон (backward-compat с python tools/test_*.py).
    fails = 0
    for c in SAMPLE_COLUMNS:
        k = classify_column(c)
        r = detect_column_role(c)
        exp = KIND_TO_ROLE.get(k, '???')
        status = 'ok' if r == exp else 'MISMATCH'
        if status != 'ok':
            fails += 1
        print(f'{c:<28}{k:<20}{r:<10}{exp:<10}{status}')
    print(f'\n{len(SAMPLE_COLUMNS)} columns, {fails} mismatches')
    sys.exit(1 if fails else 0)
