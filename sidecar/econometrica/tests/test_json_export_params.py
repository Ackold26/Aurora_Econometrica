"""Сторож честности выгрузки параметров модели (`engines/json_export.py`).

Зачем файл: у модуля не было ни одного вызывающего и ни одного теста, а читал он
имена полей, которых в продукте никогда не существовало. Он не падал – он молча
отдавал пустышку с подставленными умолчаниями: тип переноса «geometric», период
«monthly», категория канала «unknown». Документ с такими значениями клиент
показывает третьей стороне, поэтому подстановка здесь – не косметика, а ложь в
заверяемом поле (класс дефектов Critical F-01 / High Ф-01).

Что доказывается:
    1. на пустой модели выдача пустая, а не заполненная умолчаниями;
    2. параметры каналов читаются под настоящую схему записи
       (`beta`/`alpha`/`gamma`/`decay`/`adstock.type`), а не под выдуманную;
    3. записанная настройка «auto» не превращается в фактический тип переноса;
    4. апостериорные выборки сопоставляются каналу по имени, а не по позиции;
    5. блоки, которые модуль отдавал правдиво и до правки (контроли, знаковые
       факторы, праздники, нормировка), не сломались.

Числа фикстур сняты с живой модели проекта «кагоцел … 2306-26» (обучение
24.06.2026, все каналы с настройкой «auto») и с моделей от 10.07.2026, где типы
переноса записаны конкретные. Живой прогон по файлам моделей – в
`test_json_export_params_live.py`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.json_export import (  # noqa: E402
    ЗАПИСАНО,
    НЕ_ЗАПИСАНО,
    РАССЧИТАНО,
    СПРАВОЧНО,
    export_model_params_json,
    export_model_params_to_file,
)

ПОДСТАВЛЯЕМЫЕ_УМОЛЧАНИЯ = ('geometric', 'weibull', 'monthly', 'unknown', 'roi', 'effectiveness')


def _выборки(n_каналов: int, n_выборок: int = 400, сдвиг: float = 0.0) -> np.ndarray:
    """Правдоподобные апостериорные выборки: каждый канал со своим уровнем."""
    генератор = np.random.RandomState(11)
    основа = генератор.normal(0.3, 0.08, size=(n_каналов, n_выборок))
    return (основа + np.arange(n_каналов).reshape(-1, 1) * 0.1 + сдвиг).astype(np.float32)


def модель_кагоцел() -> dict:
    """Схема живой модели с настройкой переноса «auto» (обучение 24.06.2026)."""
    каналы = ['OLV', 'Banners', 'Social']
    контроли = ['Кол-во запросов', 'Продажи в уп. конкуренты', 'holiday_march8', 'holiday_may_holidays']
    return {
        'model_version': '1.2',
        'use_hierarchical': False,
        'kpi_type': 'sales',
        'kpi_kind': 'monetary',
        'kpi_likelihood': 'normal',
        'kpi_unit_cost_snapshot': None,
        'analysis_mode': None,
        'training_granularity': 'M',
        'y_actual': [float(i) for i in range(31)],
        'channel_categories': {},
        'channel_adstock_types': {канал: 'auto' for канал in каналы},
        'weibull_params_per_channel': {},
        'unit_costs_snapshot': {},
        'channel_params': {
            'OLV': {'beta': 0.0804, 'alpha': 1.522, 'gamma': 0.4867, 'adstock': {'type': 'auto'},
                    'tail_ess_ok': True, 'decay': 0.2484, 'adstock_mean_posterior': 6888976.6174},
            'Banners': {'beta': 0.0941, 'alpha': 1.5029, 'gamma': 0.4924, 'adstock': {'type': 'auto'},
                        'tail_ess_ok': True, 'decay': 0.2462, 'adstock_mean_posterior': 7209551.6072},
            'Social': {'beta': 0.1918, 'alpha': 1.6317, 'gamma': 0.5199, 'adstock': {'type': 'auto'},
                       'tail_ess_ok': False, 'decay': 0.2435, 'adstock_mean_posterior': 973701.7413},
        },
        'config': {
            'kpi_column': 'Продажи в руб. бренд',
            'date_column': 'Date',
            'media_columns': каналы,
            'control_columns': контроли,
            'data_file': r'C:\Users\кто-то\Документы\Кагоцел данные.xlsx',
        },
        'normalization': {
            'y_mean': 351574084.9,
            'y_std': 116525470.3,
            'intercept_mean': -0.4263618583917239,
            'media_means': {'OLV': 6888976.617, 'Banners': 7209551.607, 'Social': 973701.741},
            'control_means': {к: 1.0 for к in контроли},
            'control_stds': {к: 2.0 for к in контроли},
            'control_betas_mean': [0.12, -0.31, 0.05, -0.02],
            'control_kinds': ['unknown', 'signed_competitor', 'holiday', 'holiday'],
            'control_prior_mus': [0.0, -0.3, 0.0, 0.0],
            'holiday_cols_injected': ['holiday_march8', 'holiday_may_holidays'],
            'untrained_channels': [],
            'untrained_controls': ['holiday_may_holidays'],
        },
        'posterior_samples': {
            'media_columns': каналы,
            'control_columns': контроли,
            'media_betas': _выборки(3),
            'alphas': _выборки(3, сдвиг=1.2),
            'gammas': _выборки(3, сдвиг=0.2),
            'adstock_decay': _выборки(3, сдвиг=-0.05),
            'adstock_mu_logit_mean': -1.4,
            'adstock_sigma_logit_mean': 0.72,
            'n_chains': 4,
            'n_draws': 2000,
        },
        'hierarchical_priors': {},
        'signed_factor_priors_used': {},
        'fourier_seasonality': None,
        'seasonality_detected': {'period': 12, 'autocorr': 0.85},
        'reproducibility': None,
    }


def модель_с_записанными_типами() -> dict:
    """Схема моделей от 10.07.2026: типы переноса конкретные (geometric / weibull)."""
    модель = модель_кагоцел()
    модель['channel_params']['OLV']['adstock'] = {'type': 'geometric'}
    модель['channel_params']['Banners']['adstock'] = {'type': 'weibull'}
    модель['channel_params']['Social']['adstock'] = {'type': 'geometric'}
    модель['channel_adstock_types'] = {'OLV': 'geometric', 'Banners': 'weibull', 'Social': 'geometric'}
    модель['normalization']['holiday_dummies_mode'] = 'fraction'
    return модель


def выгрузка(модель: dict, **kwargs) -> dict:
    return json.loads(export_model_params_json(модель, **kwargs))


# ─── 1. Никаких подстановок ──────────────────────────────────────────

def test_пустая_модель_не_получает_подставленных_значений():
    """Пустой вход → пустая выдача. Именно тут прежняя версия сочиняла умолчания."""
    результат = выгрузка({})

    assert результат['channels'] == {}
    assert результат['history']['length'] is None
    assert результат['history']['granularity'] is None
    assert результат['kpi']['type'] is None
    assert результат['kpi']['kind'] is None
    assert результат['model']['version'] is None
    assert результат['model']['analysis_mode'] is None
    assert результат['diagnostics']['available'] is False
    assert результат['absent_fields'], 'отсутствие полей обязано быть заявлено, а не промолчано'


def test_на_пустой_модели_нет_ни_одного_умолчания_в_читаемых_блоках():
    """Обходим фактические блоки: ни одно значение не должно быть умолчанием."""
    результат = выгрузка({})

    def значения(узел):
        if isinstance(узел, dict):
            for ключ, значение in узел.items():
                if ключ in ('notes', 'note', 'origin', 'reason', 'where_to_find'):
                    continue
                yield from значения(значение)
        elif isinstance(узел, list):
            for элемент in узел:
                yield from значения(элемент)
        elif isinstance(узел, str):
            yield узел

    for блок in ('channels', 'history', 'kpi', 'normalization', 'controls', 'signed_factors'):
        собранное = list(значения(результат[блок]))
        пересечение = [v for v in собранное if v in ПОДСТАВЛЯЕМЫЕ_УМОЛЧАНИЯ]
        assert not пересечение, f'в блоке {блок} подставлено умолчание: {пересечение}'


def test_отсутствующее_поле_даёт_честный_статус_а_не_исчезает():
    """Ключ остаётся в выдаче, значение пустое, причина названа."""
    модель = модель_кагоцел()
    модель['training_granularity'] = None
    результат = выгрузка(модель)

    assert 'granularity' in результат['history']
    assert результат['history']['granularity'] is None
    assert результат['history']['granularity_origin'] == НЕ_ЗАПИСАНО
    поля = {запись['field'] for запись in результат['absent_fields']}
    assert 'history.granularity' in поля
    причина = next(з for з in результат['absent_fields'] if з['field'] == 'history.granularity')
    assert причина['reason'], 'причина отсутствия обязана быть названа словами'


# ─── 2. Чтение под настоящую схему ───────────────────────────────────

def test_параметры_каналов_читаются_настоящими_числами():
    результат = выгрузка(модель_кагоцел())
    канал = результат['channels']['OLV']

    assert канал['beta'] == pytest.approx(0.0804)
    assert канал['hill_alpha'] == pytest.approx(1.522)
    assert канал['hill_gamma'] == pytest.approx(0.4867)
    assert канал['adstock_decay'] == pytest.approx(0.2484)
    assert канал['adstock_mean_posterior'] == pytest.approx(6888976.6174)
    assert канал['media_mean'] == pytest.approx(6888976.617)
    assert канал['tail_ess_ok'] is True
    assert канал['origin']['beta'] == ЗАПИСАНО
    assert канал['origin']['hill_alpha'] == ЗАПИСАНО


def test_ни_один_канал_не_остался_пустым():
    """Прежняя версия отдавала null по всем восьми полям канала – это регресс-сторож."""
    результат = выгрузка(модель_кагоцел())
    for имя, канал in результат['channels'].items():
        for поле in ('beta', 'hill_alpha', 'hill_gamma', 'adstock_decay', 'adstock_mean_posterior'):
            assert канал[поле] is not None, f'{имя}.{поле} пустое – чтение снова разошлось со схемой'


def test_категория_канала_пустая_а_не_unknown():
    результат = выгрузка(модель_кагоцел())
    канал = результат['channels']['Social']

    assert канал['category'] is None
    assert канал['origin']['category'] == НЕ_ЗАПИСАНО


def test_длина_истории_из_ряда_kpi():
    результат = выгрузка(модель_кагоцел())

    assert результат['history']['length'] == 31
    assert результат['history']['length_origin'] == РАССЧИТАНО


def test_полный_путь_к_данным_не_выводится():
    """Документ уходит третьей стороне – путь пользователя в нём не место."""
    строка = export_model_params_json(модель_кагоцел())

    assert 'кто-то' not in строка
    assert json.loads(строка)['history']['data_file_name'] == 'Кагоцел данные.xlsx'


# ─── 3. Тип переноса: «auto» не становится фактом ────────────────────

def test_auto_не_превращается_в_geometric():
    результат = выгрузка(модель_кагоцел())

    for имя, канал in результат['channels'].items():
        assert канал['adstock_type'] is None, f'{имя}: настройка «auto» выдана за фактический тип'
        assert канал['adstock_type_recorded'] == 'auto'
        assert канал['origin']['adstock_type'] == НЕ_ЗАПИСАНО
        assert канал['adstock_decay_learned'] is False
    поля = {з['field'] for з in результат['absent_fields']}
    assert 'channels["OLV"].adstock_type' in поля


def test_записанный_тип_переноса_читается_как_факт():
    результат = выгрузка(модель_с_записанными_типами())

    геометрический = результат['channels']['OLV']
    вейбулловский = результат['channels']['Banners']
    assert геометрический['adstock_type'] == 'geometric'
    assert геометрический['origin']['adstock_type'] == ЗАПИСАНО
    assert геометрический['adstock_decay_learned'] is True
    assert вейбулловский['adstock_type'] == 'weibull'
    assert вейбулловский['adstock_decay_learned'] is False, (
        'у невогнутого в модель переноса откат остаётся приорным – выдавать его за выученный нельзя'
    )


def test_неизвестное_значение_типа_переноса_не_считается_фактом():
    модель = модель_кагоцел()
    модель['channel_params']['OLV']['adstock'] = {'type': 'Weibul'}  # опечатка из конфигурации
    результат = выгрузка(модель)

    assert результат['channels']['OLV']['adstock_type'] is None
    assert результат['channels']['OLV']['adstock_type_recorded'] == 'Weibul'


def test_отсутствие_типа_переноса_не_подставляется():
    модель = модель_кагоцел()
    модель['channel_params']['OLV'].pop('adstock')
    модель['channel_adstock_types'] = {}
    результат = выгрузка(модель)

    канал = результат['channels']['OLV']
    assert канал['adstock_type'] is None
    assert канал['adstock_type_recorded'] is None
    assert канал['adstock_decay_learned'] is None, 'без типа переноса вывод о выученности невозможен'


# ─── 4. Разброс коэффициентов ────────────────────────────────────────

def test_разброс_считается_из_выборок_и_помечен_расчётным():
    модель = модель_кагоцел()
    результат = выгрузка(модель)
    канал = результат['channels']['OLV']

    ожидаемый = float(np.asarray(модель['posterior_samples']['media_betas'][0], dtype=float).std())
    assert канал['beta_std'] == pytest.approx(ожидаемый, rel=1e-6)
    assert канал['origin']['beta_std'] == РАССЧИТАНО
    нижняя, верхняя = канал['beta_range_90']
    assert нижняя < канал['beta_std'] + верхняя  # диапазон непустой и упорядочен
    assert нижняя < верхняя


def test_без_выборок_разброс_пуст_а_не_нулевой():
    модель = модель_кагоцел()
    модель.pop('posterior_samples')
    результат = выгрузка(модель)
    канал = результат['channels']['OLV']

    assert канал['beta_std'] is None
    assert канал['beta_range_90'] is None
    assert канал['origin']['beta_std'] == НЕ_ЗАПИСАНО


def test_выборки_сопоставляются_по_имени_а_не_по_позиции():
    """Порядок ключей параметров ≠ порядок строк выборок – склейка по позиции дала бы чужие числа."""
    модель = модель_кагоцел()
    модель['posterior_samples']['media_columns'] = ['Social', 'Banners', 'OLV']
    результат = выгрузка(модель)

    ожидаемый_для_olv = float(np.asarray(модель['posterior_samples']['media_betas'][2], dtype=float).std())
    assert результат['channels']['OLV']['beta_std'] == pytest.approx(ожидаемый_для_olv, rel=1e-6)


def test_канал_вне_списка_выборок_не_получает_чужой_разброс():
    модель = модель_кагоцел()
    модель['posterior_samples']['media_columns'] = ['Banners', 'Social']
    результат = выгрузка(модель)

    assert результат['channels']['OLV']['beta_std'] is None


# ─── 5. Правдивые блоки не сломались ─────────────────────────────────

def test_контроли_знаковые_и_праздники_на_месте():
    результат = выгрузка(модель_кагоцел())

    assert set(результат['signed_factors']) == {'Продажи в уп. конкуренты'}
    assert результат['signed_factors']['Продажи в уп. конкуренты']['beta'] == pytest.approx(-0.31)
    assert set(результат['controls']) == {'Кол-во запросов', 'holiday_march8', 'holiday_may_holidays'}
    assert результат['controls']['Кол-во запросов']['beta'] == pytest.approx(0.12)
    assert результат['holidays_injected'] == ['holiday_march8', 'holiday_may_holidays']
    assert результат['controls']['holiday_may_holidays']['untrained'] is True


def test_вид_фактора_берётся_из_модели_а_не_переклассифицируется():
    """Модель – единственный источник вида фактора: правила распознавания могли смениться."""
    модель = модель_кагоцел()
    модель['config']['control_columns'] = ['столбец_без_говорящего_имени', 'второй', 'третий', 'четвёртый']
    модель['normalization']['control_kinds'] = ['signed_competitor', 'control', 'holiday', 'holiday']
    результат = выгрузка(модель)

    assert 'столбец_без_говорящего_имени' in результат['signed_factors']
    assert результат['signed_factors']['столбец_без_говорящего_имени']['origin']['kind'] == ЗАПИСАНО


def test_нормировка_читается_целиком():
    результат = выгрузка(модель_кагоцел())
    нормировка = результат['normalization']

    assert нормировка['y_mean'] == pytest.approx(351574084.9)
    assert нормировка['y_std'] == pytest.approx(116525470.3)
    assert нормировка['intercept_mean'] == pytest.approx(-0.4263618583917239)
    assert нормировка['media_means']['Social'] == pytest.approx(973701.741)
    assert нормировка['control_stds']['Кол-во запросов'] == pytest.approx(2.0)
    assert нормировка['untrained_controls'] == ['holiday_may_holidays']


def test_режим_праздничных_признаков_не_подставляется():
    результат = выгрузка(модель_кагоцел())
    assert результат['normalization']['holiday_dummies_mode'] is None

    результат_нового = выгрузка(модель_с_записанными_типами())
    assert результат_нового['normalization']['holiday_dummies_mode'] == 'fraction'


# ─── 6. Приоры, сэмплирование, диагностика ───────────────────────────

def test_приорные_средние_контролей_сопоставлены_столбцам():
    результат = выгрузка(модель_кагоцел())
    приоры = результат['priors']

    assert приоры['control_prior_means']['Продажи в уп. конкуренты'] == pytest.approx(-0.3)
    assert приоры['control_prior_means_origin'] == ЗАПИСАНО


def test_справочные_приоры_помечены_справочными():
    """Значения реестра KPI полезны для воспроизведения, но записью обучения не являются."""
    результат = выгрузка(модель_кагоцел())

    assert результат['priors']['registry_reference_origin'] == СПРАВОЧНО
    поля = {з['field'] for з in результат['absent_fields']}
    assert 'priors.specification_at_training' in поля


def test_параметры_прогона_читаются():
    результат = выгрузка(модель_кагоцел())
    прогон = результат['sampling']

    assert прогон['n_chains'] == 4
    assert прогон['n_draws_per_chain'] == 2000
    assert прогон['n_samples_total'] == 8000
    assert прогон['decay_hyper_mu_logit_posterior_mean'] == pytest.approx(-1.4)


def test_диагностика_без_файла_объявлена_отсутствующей():
    результат = выгрузка(модель_кагоцел())

    assert результат['diagnostics']['available'] is False
    assert результат['diagnostics']['where_to_find']
    поля = {з['field'] for з in результат['absent_fields']}
    assert 'diagnostics' in поля


def test_диагностика_читается_из_переданного_файла():
    диагностика = {
        'metrics': {'r_squared': 0.9763, 'mape_pct': 6.44, 'rmse': 27623063.97, 'r_hat_max': 1.0,
                    'divergences': 0, 'n_observations': 31, 'n_parameters': 20, 'ratio': 2.4,
                    'mcmc': {'chains': 4, 'draws': 2000, 'tune': 2000, 'target_accept': 0.95}},
        'mqs': {'score': 70, 'tier': 'good', 'tier_label': 'Хорошее'},
        'holidays_excluded': False,
        'per_param_rhat': {'intercept': 1.0},
        'verdict': 'Доверительные интервалы будут широкими.',
    }
    результат = выгрузка(модель_кагоцел(), diagnostics=диагностика)
    блок = результат['diagnostics']

    assert блок['available'] is True
    assert блок['fit']['r_squared'] == pytest.approx(0.9763)
    assert блок['convergence']['r_hat_max'] == pytest.approx(1.0)
    assert блок['mcmc_run']['target_accept'] == pytest.approx(0.95)
    assert блок['quality']['tier_label'] == 'Хорошее'
    assert 'verdict' not in json.dumps(блок, ensure_ascii=False), (
        'словесный вердикт продукта в клиентский документ не переносится (INV-50)'
    )


def test_окупаемость_названа_отсутствующей_с_указанием_источника():
    результат = выгрузка(модель_кагоцел())
    окупаемость = результат['not_included']['channel_roi']

    assert окупаемость['note']
    assert 'decomposition' in окупаемость['where_to_find']
    for канал in результат['channels'].values():
        assert 'roi' not in канал, 'молчаливый null по окупаемости хуже отсутствия поля'


# ─── 7. Пригодность файла ────────────────────────────────────────────

def test_нечисловые_значения_не_ломают_json():
    """NaN в модели не должен уехать в файл литералом NaN (нарушение RFC 8259)."""
    модель = модель_кагоцел()
    модель['normalization']['y_std'] = float('nan')
    модель['channel_params']['OLV']['beta'] = float('inf')

    строка = export_model_params_json(модель)
    разобранное = json.loads(строка)  # упало бы на литерале NaN

    assert 'NaN' not in строка
    assert разобранное['normalization']['y_std'] is None
    assert разобранное['channels']['OLV']['beta'] is None


def test_запись_в_файл(tmp_path):
    путь = export_model_params_to_file(модель_кагоцел(), tmp_path / 'вложенная' / 'параметры.json')

    assert путь.exists()
    разобранное = json.loads(путь.read_text(encoding='utf-8'))
    assert разобранное['channels']['OLV']['beta'] == pytest.approx(0.0804)


def test_паспорт_схемы_объясняет_обозначения():
    """Документ читает посторонний – расшифровка источников обязана быть внутри файла."""
    результат = выгрузка(модель_кагоцел())

    assert результат['schema']['version']
    for код in (ЗАПИСАНО, РАССЧИТАНО, НЕ_ЗАПИСАНО, СПРАВОЧНО):
        assert результат['schema']['origins'][код]
    assert результат['specification']['origin'] == СПРАВОЧНО
