"""P0.3 шаг 8: доля пропусков доезжает до экранов, и продукт о них говорит.

Корень. Движок отдавал только абсолютное `nulls`, а ПЯТЬ мест на фронте читают
`stats.missing_pct` (`ColumnMapperConfirm` дважды, `ExpertValidatePanel`,
`PerChannelInputSelector`, `InsightsPanel`) — все с `?? 0`. Поле не приходило
никогда, поэтому на любых данных показывался ровно ноль пропусков.

Вторая половина корня — молчание. Пропуски обрабатываются ПО-РАЗНОМУ, смотря
где они, и ни о том, ни о другом пользователю не сообщалось:
  * в целевой метрике — строка выбрасывается целиком (`modeler.py`:
    ``df = df[df[kpi_col].notna()]``), вместе с медиа-данными этого периода;
  * в канале или контроле — становится нулём (``fillna(0)``), то есть
    «активности не было». Восстановления пропущенных значений в коде нет.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engines.validator import validate_data


@pytest.fixture()
def data_with_gaps(tmp_path):
    """30 недель; 3 пропуска в канале, 2 — в целевой метрике."""
    rng = np.random.default_rng(3)
    n = 30
    tv = rng.uniform(400_000, 900_000, n)
    digital = rng.uniform(200_000, 500_000, n)
    sales = 3_000_000 + 1.4 * tv + rng.normal(0, 90_000, n)
    df = pd.DataFrame({
        'date': pd.date_range('2025-01-06', periods=n, freq='W-MON'),
        'tv': tv,
        'digital': digital,
        'sales': sales,
    })
    df.loc[[3, 7, 11], 'digital'] = np.nan
    df.loc[[20, 21], 'sales'] = np.nan
    path = tmp_path / 'data.xlsx'
    df.to_excel(path, index=False)
    return str(path)


def _stats_by_name(result):
    return {c['name']: (c.get('stats') or {}) for c in result['columns']}


def test_missing_pct_is_reported_at_all(data_with_gaps):
    """Поле есть в ответе — раньше его не было вовсе, и экраны показывали ноль."""
    stats = _stats_by_name(validate_data(data_with_gaps))
    assert 'missing_pct' in stats['digital'], (
        'stats.missing_pct отсутствует — пять экранов снова покажут ноль '
        'пропусков на любых данных'
    )


def test_missing_pct_matches_actual_gaps(data_with_gaps):
    """Доля считается от ВСЕХ строк файла, а не от очищенного ряда."""
    stats = _stats_by_name(validate_data(data_with_gaps))
    assert stats['digital']['missing_pct'] == pytest.approx(10.0)
    assert stats['digital']['nulls'] == 3
    assert stats['sales']['missing_pct'] == pytest.approx(6.7, abs=0.1)
    assert stats['tv']['missing_pct'] == 0.0


def test_gaps_in_channel_are_disclosed_as_zeros(data_with_gaps):
    """Про канал сказано, что пропуск станет нулём и восстановления нет."""
    warnings = validate_data(data_with_gaps)['warnings']
    hits = [w for w in warnings if w.get('type') == 'missing_filled_with_zero']
    assert hits, 'молчание про пропуски в канале: пользователь не узнает, что они станут нулём'
    text = hits[0]['message']
    assert 'digital' in text
    assert 'нулём' in text
    assert 'Восстановления' in text


def test_gaps_in_target_metric_are_disclosed_as_dropped_rows(data_with_gaps):
    """Про целевую метрику сказано, что период выбрасывается целиком."""
    warnings = validate_data(data_with_gaps)['warnings']
    hits = [w for w in warnings if w.get('type') == 'kpi_missing_rows_dropped']
    assert hits, (
        'молчание про пропуски в целевой метрике: строки выбрасываются вместе '
        'с медиа-данными периода, а пользователь об этом не знает'
    )
    assert 'sales' in hits[0]['message']
    assert 'исключаются' in hits[0]['message']


def test_two_kinds_of_gaps_are_not_confused(data_with_gaps):
    """Канал и целевая метрика получают РАЗНЫЕ сообщения.

    Единый текст «есть пропуски» был бы неправдой в обе стороны: он умолчал
    бы и про выброшенные периоды, и про подмену нулём.
    """
    warnings = validate_data(data_with_gaps)['warnings']
    kinds = {w.get('type') for w in warnings}
    assert 'missing_filled_with_zero' in kinds
    assert 'kpi_missing_rows_dropped' in kinds
    for w in warnings:
        if w.get('type') == 'missing_filled_with_zero':
            assert w['column'] != 'sales', 'целевой метрике приписано поведение канала'
        if w.get('type') == 'kpi_missing_rows_dropped':
            assert w['column'] == 'sales'


def test_clean_data_stays_silent(tmp_path):
    """Без пропусков — ни одного предупреждения про них."""
    rng = np.random.default_rng(11)
    n = 24
    df = pd.DataFrame({
        'date': pd.date_range('2025-01-06', periods=n, freq='W-MON'),
        'tv': rng.uniform(400_000, 900_000, n),
        'sales': rng.uniform(3_000_000, 5_000_000, n),
    })
    path = tmp_path / 'clean.xlsx'
    df.to_excel(path, index=False)
    warnings = validate_data(str(path))['warnings']
    noisy = [w for w in warnings if w.get('type') in
             ('missing_filled_with_zero', 'kpi_missing_rows_dropped')]
    assert not noisy, f'предупреждение о пропусках на чистых данных: {noisy}'
