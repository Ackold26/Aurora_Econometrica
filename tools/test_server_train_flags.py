"""F-AUD-1 (аудит 2026-07-04): доставка тумблер-флагов через server-схемы.

Класс «вычислено ≠ доставлено»: Pydantic v2 МОЛЧА отбрасывает поля вне схемы.
Фронт слал use_holidays/disabled_holidays (тумблер «Авто-праздники РФ» + opt-out),
server терял → движок всегда инжектил все 12 праздников. Боевое доказательство:
Кагоцел project.json use_holidays=false, а в pickle 12 holiday_cols_injected.
use_seasonality унаследовал бы ту же дыру.

Тест шва: обе train-схемы объявляют флаги и model_dump() их сохраняет.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402


_BASE = dict(
    project_dir='p', data_file='d.xlsx', kpi_column='kpi', media_columns=['tv'],
)


@pytest.mark.parametrize('model_name', ['TrainRequest', 'TrainStartRequest'])
def test_flags_survive_model_dump(model_name):
    import server
    model_cls = getattr(server, model_name)
    req = model_cls(
        **_BASE,
        use_holidays=False,
        disabled_holidays=['holiday_march8'],
        use_seasonality=False,
    )
    d = req.model_dump()
    assert d.get('use_holidays') is False, f'{model_name}: use_holidays потерян'
    assert d.get('disabled_holidays') == ['holiday_march8'], f'{model_name}: disabled_holidays потерян'
    assert d.get('use_seasonality') is False, f'{model_name}: use_seasonality потерян'


@pytest.mark.parametrize('model_name', ['TrainRequest', 'TrainStartRequest'])
def test_flags_default_on(model_name):
    """Обратная совместимость: без флагов — default True/[] (легаси-поведение)."""
    import server
    model_cls = getattr(server, model_name)
    d = model_cls(**_BASE).model_dump()
    assert d.get('use_holidays') is True
    assert d.get('disabled_holidays') == []
    assert d.get('use_seasonality') is True
