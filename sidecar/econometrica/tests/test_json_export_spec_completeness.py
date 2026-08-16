"""Сторож полноты спецификации в выгрузке параметров модели.

Зачем файл: 1272 теста движка проверяли, что записано то, что записано, –
и ни один не поймал того, что нашла приёмка опытом. Постороннему аналитику
выдали только документ и попросили восстановить модель: не вышло. Из двадцати
пунктов восемнадцать оказались не про природу метода, а про то, что в документ
не выгрузили уже имеющееся в коде.

Что доказывается здесь:
    1. у каждого приора названо СЕМЕЙСТВО распределения и разрешены параметры –
       «beta_sigma = 0.7» без семейства спецификацией не является;
    2. приоры взаимоисключающих ветвей не выдаются за применённые скопом:
       у неиерархической модели приоры категорий помечены неприменёнными
       (эту ошибку разбор ветвлений однажды уже допускал на `elif`);
    3. настройки сэмплера выгружены вместе с честным списком того, что коду
       передавать не случилось, – зерно без них обещает повторяемость, которой
       не будет;
    4. праздничные окна описаны календарно и ПРОВЕРЕНЫ: признаки строятся
       заново и сличаются с записанными в модели статистиками;
    5. правило ряда Фурье описано и проверено тем же способом;
    6. диапазон дат берётся из файла исходных данных ТОЛЬКО при совпавшем
       отпечатке таблицы, иначе поле пустое – подмены нет;
    7. отпечаток данных доезжает до документа целиком (вложенные разделы
       раньше молча отбрасывались) и сопровождается правилами пересчёта.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.json_export import (  # noqa: E402
    НЕ_ЗАПИСАНО,
    РАССЧИТАНО,
    СПРАВОЧНО,
    _ПАРАМЕТР_В_ДОКУМЕНТЕ,
    export_model_params_json,
)
from utils.data_fingerprint import compute_frame_fingerprint  # noqa: E402
from utils.fourier_seasonality import generate_fourier_terms  # noqa: E402
from utils.holiday_calendar_ru import generate_holiday_dummies  # noqa: E402

ПЕРИОД = 12
ГАРМОНИК = 2
НАБЛЮДЕНИЙ = 24


def _выборки(n_каналов: int, сдвиг: float = 0.0) -> np.ndarray:
    генератор = np.random.RandomState(7)
    основа = генератор.normal(0.3, 0.05, size=(n_каналов, 300))
    return (основа + сдвиг).astype(np.float32)


def проект(tmp_path, *, режим: str | None = 'fraction', иерархия: bool = False) -> dict:
    """Модель с настоящим файлом данных и настоящим отпечатком таблицы.

    Файл кладётся во временный каталог и хешируется тем же алгоритмом, что при
    обучении, – только так проверяется весь путь «сверил отпечаток → прочитал
    даты → построил признаки заново → сличил со статистиками модели».
    """
    даты = pd.date_range('2023-01-31', periods=НАБЛЮДЕНИЙ, freq='ME')
    таблица = pd.DataFrame({
        'Date': даты,
        'Продажи в руб. бренд': np.linspace(1e6, 2e6, НАБЛЮДЕНИЙ),
        'OLV Бюджет': np.linspace(1e5, 3e5, НАБЛЮДЕНИЙ),
        'Кол-во запросов': np.linspace(100, 400, НАБЛЮДЕНИЙ),
    })
    файл = tmp_path / 'данные проекта.csv'
    таблица.to_csv(файл, index=False)
    # Выгрузка читает файл с диска – отпечаток снимаем с того же прочтения.
    прочитанная = pd.read_csv(файл, sep=None, engine='python')
    отпечаток = compute_frame_fingerprint(прочитанная)

    режим_для_признаков = режим or 'fraction'
    праздники = generate_holiday_dummies(pd.to_datetime(таблица['Date']), mode=режим_для_признаков)
    фурье = generate_fourier_terms(НАБЛЮДЕНИЙ, ПЕРИОД, ГАРМОНИК)
    признаки = pd.concat([праздники, фурье], axis=1)
    имена_праздников = list(праздники.columns)
    контроли = ['Кол-во запросов'] + имена_праздников + list(фурье.columns)

    средние = {'Кол-во запросов': 250.0}
    разбросы = {'Кол-во запросов': 90.0}
    for имя in признаки.columns:
        средние[имя] = float(признаки[имя].mean())
        разбросы[имя] = float(признаки[имя].std())

    нормировка = {
        'y_mean': 1.5e6,
        'y_std': 3e5,
        'intercept_mean': -0.4,
        'media_means': {'OLV Бюджет': 2.4e5},
        'control_means': средние,
        'control_stds': разбросы,
        'control_betas_mean': [0.1] * len(контроли),
        'control_kinds': ['unknown'] + ['holiday'] * len(имена_праздников) + ['seasonality'] * len(фурье.columns),
        'control_prior_mus': [0.0] * len(контроли),
        'holiday_cols_injected': имена_праздников,
        'untrained_channels': [],
        'untrained_controls': [],
    }
    if режим is not None:
        нормировка['holiday_dummies_mode'] = режим

    return {
        'model_version': '1.3' if иерархия else '1.2',
        'use_hierarchical': иерархия,
        'kpi_type': 'sales',
        'kpi_kind': 'monetary',
        'kpi_likelihood': 'normal',
        'training_granularity': 'M',
        'y_actual': [float(v) for v in таблица['Продажи в руб. бренд']],
        'channel_categories': {'OLV Бюджет': 'brand'} if иерархия else {},
        'channel_adstock_types': {'OLV Бюджет': 'geometric'},
        'per_channel_input': {'OLV Бюджет': 'monetary'},
        'weibull_params_per_channel': {},
        'unit_costs_snapshot': {},
        'channel_params': {
            'OLV Бюджет': {'beta': 0.09, 'alpha': 1.57, 'gamma': 0.49,
                           'adstock': {'type': 'geometric'}, 'tail_ess_ok': True,
                           'decay': 0.29, 'adstock_mean_posterior': 340000.0},
        },
        'config': {
            'kpi_column': 'Продажи в руб. бренд',
            'date_column': 'Date',
            'media_columns': ['OLV Бюджет'],
            'control_columns': контроли,
            'data_file': str(файл),
            'seed': 42,
        },
        'normalization': нормировка,
        'posterior_samples': {
            'media_columns': ['OLV Бюджет'],
            'control_columns': контроли,
            'media_betas': _выборки(1),
            'alphas': _выборки(1, сдвиг=1.2),
            'gammas': _выборки(1, сдвиг=0.2),
            'adstock_decay': _выборки(1),
            'adstock_mu_logit_mean': -1.34,
            'adstock_sigma_logit_mean': 0.83,
            'n_chains': 2,
            'n_draws': 300,
        },
        'hierarchical_priors': {},
        'signed_factor_priors_used': {},
        'fourier_seasonality': {
            'period': ПЕРИОД, 'n_harmonics': ГАРМОНИК,
            'columns': list(фурье.columns), 'granularity': 'M', 'autocorr': 0.85,
        },
        'seasonality_detected': {'period': ПЕРИОД, 'autocorr': 0.85},
        'reproducibility': {
            'seed': 42,
            'seed_source': 'config',
            'sampler_tier': 'numpyro-nuts',
            'chain_method_requested': 'vectorized',
            'chain_method_delivered': True,
            'jax_devices': 1,
            'data_fingerprint': {
                'content': отпечаток,
                'file': {'status': 'ok', 'algo': 'sha256-full-file',
                         'file_sha256': 'a' * 64, 'size_bytes': файл.stat().st_size,
                         'file_name': файл.name, 'file_ext': '.csv'},
            },
            'has_compiler': True,
            'mcmc': {'chains': 2, 'draws': 300, 'tune': 2000},
            'versions': {'python': '3.12.10', 'pymc': '5.28.4'},
            'platform': {'system': 'Windows', 'machine': 'AMD64'},
        },
    }


def выгрузка(модель: dict) -> dict:
    return json.loads(export_model_params_json(модель))


def поля_отсутствия(результат: dict) -> set:
    return {з['field'] for з in результат['absent_fields']}


# ─── 1. Приоры: семейство и параметры ────────────────────────────────

def test_у_каждого_приора_названо_семейство_и_разрешены_параметры(tmp_path):
    """«sigma = 0.7» без семейства – не спецификация: нормальное? усечённое?"""
    результат = выгрузка(проект(tmp_path))
    спецификация = результат['priors']['specification_from_code']
    assert спецификация is not None
    assert результат['priors']['specification_from_code_origin'] == СПРАВОЧНО

    применённые = [п for п in спецификация['priors'] if п['applies_to_this_model']]
    по_имени = {п['variable']: п for п in применённые}
    # Ровно те величины, из-за отсутствия которых модель не восстанавливалась.
    for имя, семейство in (
        ('intercept', 'Normal'),          # свободный член
        ('media_betas', 'HalfNormal'),    # коэффициенты каналов
        ('alphas', 'Gamma'),              # приор насыщения alpha – его не было вовсе
        ('gammas', 'Beta'),
        ('sigma', 'HalfNormal'),          # шум наблюдения
        ('adstock_mu_logit', 'Normal'),   # откат
    ):
        assert имя in по_имени, f'приор {имя} в выгрузке отсутствует'
        assert по_имени[имя]['family'] == семейство
        for параметр, поле in по_имени[имя]['parameters'].items():
            assert поле['value'] is not None or поле.get('value_where_to_find'), (
                f'{имя}.{параметр} остался невыраженным числом и без указания, где его взять'
            )


def test_правдоподобие_и_структура_отката_выгружены(tmp_path):
    """Модель обучена без иерархии, но гиперпараметры отката записаны –
    структура обязана быть названа, иначе она «неизвестна» для читателя."""
    спецификация = выгрузка(проект(tmp_path))['priors']['specification_from_code']
    правдоподобие = [п for п in спецификация['likelihood'] if п['applies_to_this_model']]
    assert правдоподобие and правдоподобие[0]['family'] == 'Normal'

    откат = [
        п for п in спецификация['deterministic_transforms']
        if п['variable'] == 'adstock_decay' and п['applies_to_this_model']
    ]
    assert len(откат) == 1
    assert 'sigmoid' in откат[0]['expression']


def test_карта_параметров_покрывает_всё_найденное_в_коде(tmp_path):
    """Переименовали величину в модели – карта «где это в документе» обязана
    обновиться вместе с ней, а не остаться врать."""
    спецификация = выгрузка(проект(tmp_path))['priors']['specification_from_code']
    найденные = {п['variable'] for п in спецификация['priors']}
    найденные |= {п['variable'] for п in спецификация['likelihood']}
    найденные |= {п['variable'] for п in спецификация['deterministic_transforms']}
    незакрытые = найденные - set(_ПАРАМЕТР_В_ДОКУМЕНТЕ)
    assert not незакрытые, f'нет строки в _ПАРАМЕТР_В_ДОКУМЕНТЕ: {sorted(незакрытые)}'


# ─── 2. Ветви приоров не путаются ────────────────────────────────────

@pytest.mark.parametrize('иерархия', [False, True])
def test_приоры_чужой_ветви_не_выдаются_за_применённые(tmp_path, иерархия):
    """У неиерархической модели приоры категорий НЕ применялись – и наоборот."""
    результат = выгрузка(проект(tmp_path, иерархия=иерархия))
    спецификация = результат['priors']['specification_from_code']
    по_имени = {}
    for приор in спецификация['priors']:
        по_имени.setdefault(приор['variable'], []).append(приор)

    групповые = [приор for имя in ('brand_sigma', 'perf_sigma', 'mixed_sigma')
                 for приор in по_имени.get(имя, [])]
    assert групповые
    assert all(п['applies_to_this_model'] is иерархия for п in групповые)

    if not иерархия:
        # Общий приор коэффициента канала: применённым может быть ровно один
        # из трёх записанных в коде (подкова / группы / общий).
        применённые = [п for п in по_имени['media_betas'] if п['applies_to_this_model']]
        assert len(применённые) == 1
        assert применённые[0]['family'] == 'HalfNormal'
        assert применённые[0]['parameters']['sigma']['value'] == pytest.approx(0.3)
        assert 'категор' in спецификация['category_note']
        assert not [п for п in по_имени.get('media_betas_z', []) if п['applies_to_this_model']]
    else:
        # В иерархической ветви коэффициент канала – производная величина:
        # приор стоит на вспомогательной z, а beta = сигма группы × z. Читатель
        # обязан видеть обе части, иначе приор коэффициента «пропадает».
        assert not [п for п in по_имени.get('media_betas', []) if п['applies_to_this_model']]
        через_z = [п for п in по_имени['media_betas_z'] if п['applies_to_this_model']]
        assert len(через_z) == 1 and через_z[0]['family'] == 'HalfNormal'
        связка = [
            п for п in спецификация['deterministic_transforms']
            if п['variable'] == 'media_betas' and п['applies_to_this_model']
        ]
        assert len(связка) == 1 and 'media_betas_z' in связка[0]['expression']
        assert 'category_note' not in спецификация


# ─── 3. Настройки сэмплера ───────────────────────────────────────────

def test_настройки_сэмплера_и_честный_список_непереданного(tmp_path):
    """Зерно и версии без целевой доли принятия обещают побитовое повторение,
    которого не будет. Что не передано – должно быть названо."""
    результат = выгрузка(проект(tmp_path))
    прогон = результат['sampling']
    assert прогон['n_tune'] == 2000
    настройки = прогон['settings_from_code']
    assert настройки is not None

    применённый = [в for в in настройки['calls'] if в['applies_to_this_model']]
    assert len(применённый) == 1, 'ярус прогона записан – применённый вызов должен быть один'
    assert применённый[0]['arguments']['target_accept'] == '0.95'
    assert прогон['settings_from_code']['applied_tier'] == 'numpyro-nuts'
    assert 'max_treedepth' in применённый[0]['not_passed']
    assert 'init' in применённый[0]['not_passed']
    # Непереданное обязано быть видно и в списке отсутствующих полей.
    assert any('max_treedepth' in поле for поле in поля_отсутствия(результат))


# ─── 4. Календарь праздников ─────────────────────────────────────────

def test_окна_праздников_описаны_датами_и_проверены(tmp_path):
    """Двенадцать имён и слово «доля» регрессор собрать не позволяют."""
    результат = выгрузка(проект(tmp_path))
    календарь = результат['holiday_calendar']
    assert календарь['mode_recorded'] == 'fraction'
    assert календарь['calendar']['mode_rules']['fraction']
    assert календарь['calendar']['row_period_rule']

    события = {с['name']: с for с in календарь['calendar']['events']}
    assert set(события) == set(результат['holidays_injected'])
    for имя, событие in события.items():
        assert событие['windows'], f'у события {имя} нет календарных границ'
        первое = событие['windows'][0]
        assert первое['start'] <= первое['end']
        assert событие['window_kind'] in ('preparation', 'sale_period', 'calendar_period')

    сверка = календарь['verification']
    assert сверка['status'] == 'verified'
    assert сверка['checked'] == len(события)


def test_без_записанного_режима_оба_варианта_и_никакого_выбора_за_читателя(tmp_path):
    """Режим не записан – окна распродаж неоднозначны. Подставлять нельзя."""
    результат = выгрузка(проект(tmp_path, режим=None))
    календарь = результат['holiday_calendar']
    assert календарь['mode_recorded'] is None
    assert календарь['calendar'] is None
    assert set(календарь['calendar_by_mode']) == {'fraction', 'binary_point'}
    assert календарь['verification']['status'] == 'not_checked'
    assert 'normalization.holiday_dummies_mode' in поля_отсутствия(результат)


# ─── 5. Правило ряда Фурье ───────────────────────────────────────────

def test_правило_фурье_описано_и_проверено(tmp_path):
    результат = выгрузка(проект(tmp_path))
    правило = результат['seasonality']['fourier_rule']
    assert 'sin(2π' in правило['formula']
    assert 'ПОЗИЦИЯ' in правило['index_rule']
    assert правило['verification']['status'] == 'verified'
    assert правило['verification']['checked'] == 2 * ГАРМОНИК


# ─── 6. Диапазон дат – только с доказательством ──────────────────────

def test_диапазон_дат_выводится_при_совпавшем_отпечатке(tmp_path):
    результат = выгрузка(проект(tmp_path))
    диапазон = результат['history']['date_range']
    assert результат['history']['date_range_origin'] == РАССЧИТАНО
    assert диапазон['first'] == '2023-01-31'
    assert диапазон['last'] == '2024-12-31'
    assert диапазон['n_dates'] == НАБЛЮДЕНИЙ
    assert диапазон['matches_history_length'] is True


def test_подменённый_файл_данных_не_становится_источником_дат(tmp_path):
    """Файл изменился – документ обязан промолчать, а не заверить чужой ряд."""
    модель = проект(tmp_path)
    файл = Path(модель['config']['data_file'])
    таблица = pd.read_csv(файл, sep=None, engine='python')
    таблица.loc[0, 'Продажи в руб. бренд'] = 42.0
    таблица.to_csv(файл, index=False)

    результат = выгрузка(модель)
    assert результат['history']['date_range'] is None
    assert результат['history']['date_range_origin'] == НЕ_ЗАПИСАНО
    assert результат['holiday_calendar']['source_data']['status'] == 'mismatch'
    assert результат['holiday_calendar']['verification']['status'] == 'not_checked'
    assert 'history.date_range' in поля_отсутствия(результат)


def test_без_отпечатка_файл_не_читается_вовсе(tmp_path):
    """Старые модели: отпечатка нет – сверять не с чем, значит и брать нечего."""
    модель = проект(tmp_path)
    модель['reproducibility'] = None
    результат = выгрузка(модель)
    assert результат['history']['date_range'] is None
    assert результат['holiday_calendar']['source_data']['status'] == 'unavailable'
    assert результат['reproducibility']['available'] is False


# ─── 7. Отпечаток доезжает до документа ──────────────────────────────

def test_отпечаток_данных_не_теряется_и_снабжён_правилами(tmp_path):
    """Вложенные разделы паспорта раньше отбрасывались, и поле
    data_fingerprint выходило пустым объектом в разделе «воспроизводимость»."""
    результат = выгрузка(проект(tmp_path))
    отпечаток = результат['reproducibility']['data_fingerprint']
    assert отпечаток['content']['content_sha256']
    assert отпечаток['content']['n_rows'] == НАБЛЮДЕНИЙ
    assert отпечаток['file']['file_sha256']

    правила = результат['reproducibility']['data_fingerprint_algorithm']
    assert правила['algo'] == отпечаток['content']['algo']
    assert правила['cell_canonical_form'] and правила['frame_digest']


# ─── 8. Недоступный исходник не ломает и не сочиняет ─────────────────

def test_без_исходника_спецификация_объявлена_отсутствующей(tmp_path, monkeypatch):
    """Исходник кода недоступен (собранная поставка, урезанный образ) – документ
    обязан честно сказать «не прочитано», а не выдать неполный список."""
    from engines import json_export

    monkeypatch.setattr(json_export, '_дерево_сборки_модели', lambda: (None, 'modeler.py'))
    результат = выгрузка(проект(tmp_path))
    assert результат['priors']['specification_from_code'] is None
    assert результат['priors']['specification_from_code_origin'] == НЕ_ЗАПИСАНО
    assert результат['sampling']['settings_from_code'] is None
    поля = поля_отсутствия(результат)
    assert 'priors.specification_from_code' in поля
    assert 'sampling.settings_from_code' in поля


# ─── 9. Единицы величин ──────────────────────────────────────────────

def test_единицы_названы_у_kpi_и_у_каналов(tmp_path):
    результат = выгрузка(проект(tmp_path))
    assert результат['kpi']['unit_kind'] == 'monetary'
    assert 'валюта' in результат['kpi']['unit_kind_note']
    канал = результат['channels']['OLV Бюджет']
    assert канал['unit_kind'] == 'monetary'
    assert 'adstock_mean_posterior' in канал['notes']['unit_kind']
