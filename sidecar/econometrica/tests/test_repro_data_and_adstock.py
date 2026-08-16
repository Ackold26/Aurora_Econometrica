"""Запись фактов воспроизводимости при обучении: данные и выбор затухания.

Два пробела, которые здесь стерегутся:

1. **Отпечаток данных** едет в паспорт воспроизводимости
   (`utils/seeding.py::environment_snapshot` → `model_data['reproducibility']`).
   Снимается при обучении: у большинства обученных моделей исходного файла по
   записанному в конфиге пути уже нет, постфактум отпечаток взять неоткуда.

2. **Протокол выбора затухания** (`model_data['adstock_selection']`) отвечает на
   вопрос, на который готовая модель раньше ответить не могла: пользователь
   выбрал Вейбулла или его выбрал BIC-селектор. Резолвер мутирует
   `adstock_config` на месте, и этот же объект уезжает в модель — исходная
   настройка `'auto'` затиралась бесследно. Три ветки отката обязаны
   различаться: «выбрал BIC» и «селектор упал, откатились на geometric» — для
   документа воспроизводимости разные факты.

Обучение здесь не запускается: проверяется чистая логика записи.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.modeler import (  # noqa: E402
    ADSTOCK_BY_BIC,
    ADSTOCK_BY_DEFAULT,
    ADSTOCK_BY_NO_SELECTION,
    ADSTOCK_BY_SELECTOR_ERROR,
    ADSTOCK_BY_SELECTOR_STATUS,
    ADSTOCK_BY_USER,
    _resolve_auto_adstock,
)
from utils.seeding import environment_snapshot  # noqa: E402

# Реальная модель клиента, обученная до появления новых полей — проверка
# обратной совместимости. Копируется во временный каталог: загрузчик умеет
# переписывать файл ленивой миграцией, в проект клиента писать нельзя.
LEGACY_MODEL = Path(
    r'C:\Users\ackol\AppData\Roaming\aurora-econometrica-gui\projects'
    r'\кагоцел-рф--данные-для-эконометрики---на-ммх-2306-26\models\latest.pkl'
)


def _ok(selections: dict) -> dict:
    return {'status': 'ok', 'selections': selections, 'summary': 'mock'}


# ---------------------------------------------------------------------------
# 1. Паспорт воспроизводимости несёт отпечаток данных
# ---------------------------------------------------------------------------

def test_snapshot_carries_data_fingerprint():
    fingerprint = {
        'content': {'status': 'ok', 'content_sha256': 'a' * 64},
        'file': {'status': 'ok', 'file_sha256': 'b' * 64},
    }
    snapshot = environment_snapshot(
        seed=42,
        seed_source='default',
        chains=4,
        draws=2000,
        tune=2000,
        has_compiler=True,
        data_fingerprint=fingerprint,
    )
    assert snapshot['data_fingerprint'] == fingerprint


def test_snapshot_without_fingerprint_keeps_old_callers_working():
    """Аргумент со значением по умолчанию: прежние вызовы не ломаются.

    Ключ при этом присутствует со значением None — «отпечатка нет» должно
    читаться отсутствием отпечатка, а не отсутствием ключа.
    """
    snapshot = environment_snapshot(
        seed=7,
        seed_source='config',
        chains=2,
        draws=1000,
        tune=500,
        has_compiler=False,
    )
    assert 'data_fingerprint' in snapshot
    assert snapshot['data_fingerprint'] is None


def test_snapshot_fingerprint_is_keyword_only():
    """Позиционно отпечаток не передать — порядок аргументов не ломается."""
    with pytest.raises(TypeError):
        environment_snapshot(42, 'default', 4, 2000, 2000, True, None, None, {})  # noqa


def test_train_model_computes_fingerprint_right_after_read():
    """Врезка стоит в `train_model` и берёт таблицу как прочитана.

    Проверяем по исходному тексту: отпечаток обязан сниматься ДО отсева
    хвоста с пустым KPI, иначе посторонний не воспроизведёт его, просто
    открыв файл.
    """
    source = (Path(__file__).parent.parent / 'engines' / 'modeler.py').read_text(
        encoding='utf-8'
    )
    call_at = source.index('build_data_fingerprint(df, data_file)')
    filter_at = source.index('df[df[kpi_col].notna()]')
    read_at = source.index('df = pd.read_excel(data_file)')
    assert read_at < call_at < filter_at, (
        'Отпечаток должен сниматься между чтением файла и отсевом хвоста'
    )
    assert 'data_fingerprint=data_fingerprint' in source, (
        'Отпечаток обязан уходить в environment_snapshot одним снимком, '
        'а не дописываться в паспорт сбоку'
    )


# ---------------------------------------------------------------------------
# 2. Протокол выбора затухания
# ---------------------------------------------------------------------------

def test_auto_resolved_by_bic_keeps_requested_auto():
    """Главная потеря: 'auto' затирался разрешённым типом бесследно."""
    cfg = {'tv': 'auto'}
    with patch(
        'engines.adstock_selector.select_adstock',
        return_value=_ok({'tv': {'type': 'weibull', 'confidence': 'strong'}}),
    ):
        protocol = _resolve_auto_adstock(
            cfg, data_file='/fake.xlsx', kpi_col='sales', media_cols=['tv']
        )

    assert cfg['tv'] == 'weibull', 'мутация на месте сохранена'
    assert protocol['tv'] == {
        'requested': 'auto',
        'resolved': 'weibull',
        'by': ADSTOCK_BY_BIC,
    }


def test_dict_form_auto_recorded_as_auto():
    cfg = {'tv': {'type': 'auto'}}
    with patch(
        'engines.adstock_selector.select_adstock',
        return_value=_ok({'tv': {'type': 'geometric', 'confidence': 'weak'}}),
    ):
        protocol = _resolve_auto_adstock(
            cfg, data_file='/fake.xlsx', kpi_col='sales', media_cols=['tv']
        )

    assert protocol['tv']['requested'] == 'auto'
    assert protocol['tv']['by'] == ADSTOCK_BY_BIC


def test_explicit_user_choice_is_recorded_not_omitted():
    """Явный выбор пользователя тоже записывается — честно, а не пропуском."""
    cfg = {'tv': 'weibull', 'digital': 'geometric'}
    protocol = _resolve_auto_adstock(
        cfg, data_file='/fake.xlsx', kpi_col='sales', media_cols=['tv', 'digital']
    )

    assert protocol['tv'] == {
        'requested': 'weibull',
        'resolved': 'weibull',
        'by': ADSTOCK_BY_USER,
    }
    assert protocol['digital']['by'] == ADSTOCK_BY_USER


def test_channel_absent_from_config_is_marked_default():
    """Канала нет в настройке — применяется geometric по умолчанию.

    Отличие «пользователь выбрал geometric» от «никто не выбирал» для
    документа существенно: во втором случае выбор не делался вовсе.
    """
    protocol = _resolve_auto_adstock(
        {}, data_file='/fake.xlsx', kpi_col='sales', media_cols=['tv']
    )
    assert protocol['tv'] == {
        'requested': None,
        'resolved': 'geometric',
        'by': ADSTOCK_BY_DEFAULT,
    }


def test_three_fallback_branches_are_distinguishable():
    """Три ветки отката пишут разные причины, хотя тип у всех geometric."""
    # Ветка 1: селектор бросил исключение.
    cfg1 = {'tv': 'auto'}
    with patch(
        'engines.adstock_selector.select_adstock', side_effect=RuntimeError('boom')
    ):
        p1 = _resolve_auto_adstock(
            cfg1, data_file='/fake.xlsx', kpi_col='sales', media_cols=['tv']
        )

    # Ветка 2: селектор вернул не-ok.
    cfg2 = {'tv': 'auto'}
    with patch(
        'engines.adstock_selector.select_adstock',
        return_value={'status': 'error', 'message': 'мало точек'},
    ):
        p2 = _resolve_auto_adstock(
            cfg2, data_file='/fake.xlsx', kpi_col='sales', media_cols=['tv']
        )

    # Ветка 3: селектор отработал, но по каналу выбора не дал.
    cfg3 = {'tv': 'auto'}
    with patch('engines.adstock_selector.select_adstock', return_value=_ok({})):
        p3 = _resolve_auto_adstock(
            cfg3, data_file='/fake.xlsx', kpi_col='sales', media_cols=['tv']
        )

    assert cfg1['tv'] == cfg2['tv'] == cfg3['tv'] == 'geometric'
    assert p1['tv']['by'] == ADSTOCK_BY_SELECTOR_ERROR
    assert p2['tv']['by'] == ADSTOCK_BY_SELECTOR_STATUS
    assert p3['tv']['by'] == ADSTOCK_BY_NO_SELECTION
    reasons = {p1['tv']['by'], p2['tv']['by'], p3['tv']['by']}
    assert len(reasons) == 3, 'причины отката обязаны различаться между собой'
    assert ADSTOCK_BY_BIC not in reasons, 'откат не выдавать за выбор BIC'
    for protocol in (p1, p2, p3):
        assert protocol['tv']['requested'] == 'auto'
        assert protocol['tv']['resolved'] == 'geometric'


def test_protocol_covers_every_media_channel():
    """Пустых мест в протоколе нет: каждый канал получает запись."""
    cfg = {'tv': 'auto', 'digital': 'weibull'}
    with patch(
        'engines.adstock_selector.select_adstock',
        return_value=_ok({'tv': {'type': 'geometric'}}),
    ):
        protocol = _resolve_auto_adstock(
            cfg,
            data_file='/fake.xlsx',
            kpi_col='sales',
            media_cols=['tv', 'digital', 'ooh'],
        )

    assert set(protocol) == {'tv', 'digital', 'ooh'}
    for entry in protocol.values():
        assert set(entry) == {'requested', 'resolved', 'by'}


def test_train_model_stores_protocol_under_free_name():
    """Поле кладётся в модель и НЕ переиспользует занятые имена."""
    source = (Path(__file__).parent.parent / 'engines' / 'modeler.py').read_text(
        encoding='utf-8'
    )
    assert "'adstock_selection': dict(adstock_selection)" in source
    assert 'adstock_selection = _resolve_auto_adstock(' in source
    # Занятые имена остались при своей механике.
    assert "'channel_adstock_types': dict(adstock_config)" in source


# ---------------------------------------------------------------------------
# 3. Совместимость: старая модель без новых полей
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not LEGACY_MODEL.exists(),
    reason='нет реальной модели клиента на этой машине',
)
def test_legacy_model_loads_and_consumers_survive(tmp_path):
    """Модель, обученная до новых полей, читается и потребителей не роняет."""
    from engines.methodology_cert import _extract_reproducibility
    from engines.persistence import load_model_with_compat

    # Копия: загрузчик умеет переписывать файл ленивой миграцией.
    copy_path = tmp_path / 'latest.pkl'
    shutil.copy2(LEGACY_MODEL, copy_path)
    sidecar = LEGACY_MODEL.with_suffix('.pkl.sha256')
    if sidecar.exists():
        shutil.copy2(sidecar, tmp_path / 'latest.pkl.sha256')

    model_data = load_model_with_compat(copy_path)

    # Новых полей нет — читатели обязаны видеть их отсутствие, а не подстановку.
    assert model_data.get('adstock_selection') is None
    snapshot = model_data.get('reproducibility') or {}
    assert snapshot.get('data_fingerprint') is None

    # Старые поля на месте и не подменены.
    assert isinstance(model_data.get('channel_adstock_types'), dict)
    assert model_data.get('channel_params')

    # Потребитель паспорта воспроизводимости отрабатывает по-прежнему.
    extracted = _extract_reproducibility(model_data)
    assert extracted['status'] in ('recorded', 'deterministic', 'absent')


def test_new_fields_are_optional_for_readers():
    """Читатель, работающий через .get(), на модели без полей не падает."""
    from engines.methodology_cert import _extract_reproducibility

    model_data = {
        'model_version': '1.3',
        'channel_params': {'tv': {'beta': 0.1}},
        'channel_adstock_types': {'tv': 'geometric'},
        'reproducibility': {'seed': 42, 'seed_source': 'default'},
    }
    extracted = _extract_reproducibility(model_data)
    assert isinstance(extracted, dict)
    assert model_data.get('adstock_selection') is None
