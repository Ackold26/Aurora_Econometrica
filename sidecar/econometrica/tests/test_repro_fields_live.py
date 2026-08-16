"""Живой сторож паспорта воспроизводимости: `data_fingerprint` + `adstock_selection`.

Почему отдельным живым файлом, а не только структурным (P0.6b):
    `test_repro_data_and_adstock.py::test_train_model_stores_protocol_under_free_name`
    ищет подстроку в исходном тексте ``modeler.py`` — дёшево, но слепо к сути:
    переписанное иначе выражение даёт ложный красный, а поле, записанное
    пустым или сломанным, — ложный зелёный (текст на месте, значение — нет).
    Разделение с `test_mcmc_determinism_live.py` то же самое: структурный
    сторож живёт в CI без PyMC, живой — здесь, с реальным обучением.

Что доказывается (перечитывая СОХРАНЁННЫЙ файл модели с диска, не возврат
функции train_model — иначе тест проверял бы память процесса, а не то, что
реально легло на диск и переживёт перезапуск):

    1. отпечаток содержимого данных снят и совпадает с исходной таблицей
       (число строк/столбцов);
    2. отпечаток файла — полный хеш и размер, а имя в поле БЕЗ каталогов
       (путь может содержать имя клиента — ему в этом поле не место);
    3. протокол выбора затухания заполнен по каждому медиаканалу и несёт
       три факта: что просили, что применилось, кто выбрал;
    4. настройка 'auto' у пользователя НЕ теряется — `_resolve_auto_adstock`
       мутирует `adstock_config` на месте, и без отдельного поля исходная
       настройка стиралась бы бесследно. Проверяем это же зондом на самом
       `config`, который держим за пределами train_model: после обучения его
       `adstock_config` уже содержит разрешённый тип, а не 'auto' — то есть
       без `adstock_selection` в модели узнать про исходный запрос было бы
       неоткуда.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

pymc = pytest.importorskip('pymc', reason='PyMC недоступен – живой прогон невозможен')

# Минимальные цепи/выборки: тест проверяет НАЛИЧИЕ и ЧЕСТНОСТЬ полей, а не
# качество модели — по образцу test_mcmc_determinism_live.py.
MCMC_OVERRIDE = {'chains': 1, 'draws': 40, 'tune': 40}
SEED = 42
N_WEEKS = 24


def _make_dataset(path: Path) -> None:
    """24 недели синтетики с двумя медиаканалами.

    Один канал держим на `'auto'` (гоняет BIC-выбор затухания), другой —
    явным `'geometric'` (гоняет ветку `ADSTOCK_BY_USER`). Оба канала ненулевые
    и коррелируют с KPI, иначе BIC-селектор откатится на geometric по
    признаку «все нули», а не реально выберет.
    """
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(20260816)
    tv = rng.uniform(400_000, 1_200_000, N_WEEKS)
    digital = rng.uniform(200_000, 800_000, N_WEEKS)
    sales = (
        5_000_000
        + 1.8 * tv
        + 2.4 * digital
        + rng.normal(0, 150_000, N_WEEKS)
    )
    pd.DataFrame({
        'date': pd.date_range('2025-01-06', periods=N_WEEKS, freq='W-MON'),
        'tv': tv,
        'digital': digital,
        'sales': sales,
    }).to_excel(path, index=False)


@pytest.fixture(scope='module')
def trained_model_on_disk(tmp_path_factory):
    """Обучает модель один раз на модуль и перечитывает файл модели с диска.

    Дорогая часть (обучение) выполняется один раз — четыре проверки задания
    читают один и тот же перечитанный `model_data`, а не гоняют MCMC заново
    на каждый assert.
    """
    from engines.modeler import train_model
    from engines.persistence import load_model_with_compat

    tmp_root = tmp_path_factory.mktemp('repro_fields_live')
    data_file = tmp_root / 'data.xlsx'
    _make_dataset(data_file)

    project_dir = tmp_root / 'project'
    project_dir.mkdir(parents=True, exist_ok=True)

    # Держим СВОЮ копию конфигурации отдельно от той, что уйдёт в train_model:
    # `_resolve_auto_adstock` мутирует `adstock_config` (и, значит, объект
    # под ключом 'adstock_config') на месте. Если передать один и тот же
    # словарь, наблюдать «до» будет уже неоткуда — а именно это наблюдение
    # доказывает пункт 4.
    adstock_config = {'tv': 'auto', 'digital': 'geometric'}
    config = {
        'data_file': str(data_file),
        'kpi_column': 'sales',
        'media_columns': ['tv', 'digital'],
        'control_columns': [],
        'date_column': 'date',
        'kpi_type': 'sales',
        'adstock_config': adstock_config,
        'mcmc_override': dict(MCMC_OVERRIDE),
        'seed': SEED,
    }

    result = train_model(config, str(project_dir))
    assert result.get('status') == 'ok', (
        f'Обучение не прошло: {result.get("error_code")} {result.get("message")}'
    )

    model_path = project_dir / 'models' / 'latest.pkl'
    assert model_path.exists(), (
        f'Файл модели не создан по каноническому пути {model_path} — '
        f'перечитывать нечего.'
    )
    model_data = load_model_with_compat(model_path)

    return {
        'model_data': model_data,
        'config_after_train': config,
        'df_rows': N_WEEKS,
        'df_cols': 3,  # date, tv, digital, sales — 4 столбца; см. ниже уточнение
    }


@pytest.mark.slow
def test_data_fingerprint_content_matches_source_table(trained_model_on_disk):
    """Отпечаток содержимого таблицы снят и число строк/столбцов совпадает."""
    reproducibility = trained_model_on_disk['model_data'].get('reproducibility') or {}
    fingerprint = reproducibility.get('data_fingerprint')
    assert isinstance(fingerprint, dict), (
        'В перечитанном файле модели нет reproducibility.data_fingerprint — '
        'поле не доехало до диска.'
    )
    content = fingerprint.get('content') or {}
    assert content.get('status') == 'ok', (
        f'Отпечаток содержимого не снят: {content}'
    )
    assert isinstance(content.get('content_sha256'), str) and len(content['content_sha256']) == 64, (
        'content_sha256 отсутствует или не похож на SHA-256 (64 hex-символа)'
    )
    assert content.get('n_rows') == N_WEEKS, (
        f'Число строк в отпечатке ({content.get("n_rows")}) не совпадает '
        f'с исходной таблицей ({N_WEEKS})'
    )
    # date, tv, digital, sales — ровно 4 столбца в исходном xlsx.
    assert content.get('n_cols') == 4, (
        f'Число столбцов в отпечатке ({content.get("n_cols")}) не совпадает '
        f'с исходной таблицей (4)'
    )


@pytest.mark.slow
def test_data_fingerprint_file_has_full_hash_size_and_bare_name(trained_model_on_disk):
    """Отпечаток файла: полный хеш, размер, имя БЕЗ пути (может содержать имя клиента)."""
    reproducibility = trained_model_on_disk['model_data'].get('reproducibility') or {}
    fingerprint = reproducibility.get('data_fingerprint') or {}
    file_part = fingerprint.get('file') or {}

    assert file_part.get('status') == 'ok', f'Отпечаток файла не снят: {file_part}'
    assert isinstance(file_part.get('file_sha256'), str) and len(file_part['file_sha256']) == 64, (
        'file_sha256 отсутствует или не похож на полный SHA-256'
    )
    assert isinstance(file_part.get('size_bytes'), int) and file_part['size_bytes'] > 0, (
        'size_bytes отсутствует или не положительный'
    )
    file_name = file_part.get('file_name')
    assert file_name == 'data.xlsx', (
        f'Имя файла в отпечатке ({file_name!r}) не совпадает с ожидаемым '
        f"'data.xlsx' — либо потеряно, либо содержит путь"
    )
    assert '\\' not in file_name and '/' not in file_name, (
        f'В поле file_name найден путь ({file_name!r}) — путь к исходнику '
        f'может содержать имя клиента, в этом поле его быть не должно'
    )


@pytest.mark.slow
def test_adstock_selection_filled_per_channel_with_three_facts(trained_model_on_disk):
    """Протокол выбора затухания заполнен по каждому каналу: requested/resolved/by."""
    model_data = trained_model_on_disk['model_data']
    selection = model_data.get('adstock_selection')
    assert isinstance(selection, dict), (
        'В перечитанном файле модели нет adstock_selection — поле не доехало '
        'до диска.'
    )
    assert set(selection) == {'tv', 'digital'}, (
        f'Протокол покрывает не все каналы: {set(selection)}'
    )
    for channel, entry in selection.items():
        assert set(entry) == {'requested', 'resolved', 'by'}, (
            f'Запись по каналу {channel} не несёт всех трёх фактов: {entry}'
        )
        assert entry['resolved'] in ('geometric', 'weibull'), (
            f'Применённый тип по каналу {channel} не выглядит валидным типом '
            f'затухания: {entry["resolved"]!r}'
        )
        assert entry['by'], f'Причина выбора по каналу {channel} пуста'


@pytest.mark.slow
def test_auto_request_survives_in_place_mutation_of_adstock_config(trained_model_on_disk):
    """Главное: исходная настройка 'auto' не затирается мутацией на месте.

    `_resolve_auto_adstock` мутирует переданный `adstock_config` в самом
    объекте — после обучения в `config['adstock_config']['tv']` уже лежит
    разрешённый тип, а не 'auto'. Без отдельного поля `adstock_selection` в
    модели узнать про исходный запрос пользователя было бы неоткуда — это
    и проверяем: requested-факт в модели переживает мутацию, а сам мутировавший
    объект — живое доказательство того, что без него было бы потеряно.
    """
    config_after = trained_model_on_disk['config_after_train']
    mutated_type = config_after['adstock_config']['tv']
    assert mutated_type in ('geometric', 'weibull'), (
        f"Мутация не произошла как ожидалось: config['adstock_config']['tv'] "
        f'= {mutated_type!r}, а не разрешённый тип. Если резолвер перестал '
        f'мутировать конфиг на месте — сценарий этого теста больше не '
        f'воспроизводит риск, который он проверяет.'
    )
    assert mutated_type != 'auto', (
        "config['adstock_config']['tv'] после обучения всё ещё 'auto' — "
        'резолвер не сработал, тест ничего не доказывает'
    )

    selection = trained_model_on_disk['model_data'].get('adstock_selection') or {}
    tv_entry = selection.get('tv') or {}
    assert tv_entry.get('requested') == 'auto', (
        f"В сохранённой модели adstock_selection['tv']['requested'] = "
        f"{tv_entry.get('requested')!r}, ожидали 'auto'. Исходная настройка "
        f"пользователя потеряна — ровно то, от чего это поле защищает."
    )
    assert tv_entry.get('resolved') == mutated_type, (
        'Применённый тип в паспорте разошёлся с фактически применённым в '
        'конфиге'
    )

    digital_entry = selection.get('digital') or {}
    assert digital_entry.get('requested') == 'geometric', (
        f"Явный выбор пользователя по 'digital' не записан как есть: "
        f"{digital_entry.get('requested')!r}"
    )
    assert digital_entry.get('by') == 'user', (
        f"Причина выбора по 'digital' должна быть 'user' (явный выбор), "
        f"получили {digital_entry.get('by')!r}"
    )
