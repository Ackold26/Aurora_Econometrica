"""У2 (2026-07-04): канарейка паритета фронт↔серверные схемы обучения.

Ловит класс F-AUD-1 «строгая Pydantic-схема МОЛЧА роняет поле»: фронт
(buildTrainConfig в train-config.js) шлёт ключ, которого нет в серверной схеме
TrainRequest/TrainStartRequest → Pydantic v2 отбрасывает его без ошибки → фича
превращается в декорацию (боевой случай: тумблер «Авто-праздники РФ» слался, но
терялся; в pickle всё равно 12 праздников). Кросс-язык паритет — аналог
mirror JS↔Rust из методов.

🔴 ЯКОРЬ: при добавлении флага в обучение обнови ОБЕ стороны (train-config.js
buildTrainConfig + обе схемы server.py) + этот тест не должен покраснеть.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'sidecar'
for _p in (str(SIDECAR), str(SIDECAR / 'econometrica')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TRAIN_CONFIG_JS = ROOT / 'src' / 'lib' / 'train-config.js'


def _frontend_train_keys() -> set[str]:
    """Извлечь top-level ключи возвращаемого объекта buildTrainConfig.

    Ключи return-объекта — на отступе ровно 4 пробела (вложенные значения глубже).
    calibrations добавляется через spread (...(cond ? {calibrations} : {})) —
    учитывается отдельно по наличию литерала.
    """
    text = TRAIN_CONFIG_JS.read_text(encoding='utf-8')
    m = re.search(r'return\s*\{(.*)\};', text, re.DOTALL)
    assert m, 'не найден return-объект buildTrainConfig в train-config.js'
    body = m.group(1)
    keys: set[str] = set()
    for line in body.splitlines():
        mm = re.match(r'^    ([a-z_][a-z0-9_]*):', line)
        if mm:
            keys.add(mm.group(1))
    if re.search(r'\bcalibrations:', body):
        keys.add('calibrations')
    return keys


def _schema_fields():
    import server  # noqa: E402
    return (
        set(server.TrainRequest.model_fields.keys()),
        set(server.TrainStartRequest.model_fields.keys()),
    )


def test_frontend_keys_extracted_nonempty():
    keys = _frontend_train_keys()
    # Санити: якорные ключи, которые точно должны извлечься.
    for anchor in ('project_dir', 'kpi_column', 'media_columns', 'use_holidays'):
        assert anchor in keys, f'парсер train-config.js не извлёк {anchor}: {sorted(keys)}'


def test_every_frontend_key_in_both_schemas():
    """КАЖДЫЙ фронт-ключ ∈ обеих серверных схем — иначе Pydantic молча роняет."""
    keys = _frontend_train_keys()
    req_fields, start_fields = _schema_fields()
    missing_req = keys - req_fields
    missing_start = keys - start_fields
    assert not missing_req, (
        f'F-AUD-1: фронт шлёт {sorted(missing_req)}, но TrainRequest их не объявляет '
        f'→ Pydantic отбросит молча (фича-декорация). Добавь поля в server.py.'
    )
    assert not missing_start, (
        f'F-AUD-1: фронт шлёт {sorted(missing_start)}, но TrainStartRequest их не '
        f'объявляет → async-путь (GUI) потеряет поле. Добавь поля в server.py.'
    )


def test_two_train_schemas_stay_in_sync():
    """TrainRequest и TrainStartRequest должны иметь ИДЕНТИЧНЫЕ поля — F-AUD-1
    возник из-за рассинхрона sync/async путей (флаг был в одной, не в другой)."""
    req_fields, start_fields = _schema_fields()
    only_req = req_fields - start_fields
    only_start = start_fields - req_fields
    assert not only_req and not only_start, (
        f'рассинхрон схем обучения: только в TrainRequest={sorted(only_req)}, '
        f'только в TrainStartRequest={sorted(only_start)} — путь потеряет поле.'
    )


def test_master_flags_present_both_schemas():
    """Мастер-флаги доставки объявлены в ОБЕИХ схемах (прямая защита F-AUD-1)."""
    req_fields, start_fields = _schema_fields()
    for flag in ('use_holidays', 'disabled_holidays', 'use_seasonality'):
        assert flag in req_fields, f'{flag} отсутствует в TrainRequest'
        assert flag in start_fields, f'{flag} отсутствует в TrainStartRequest'
