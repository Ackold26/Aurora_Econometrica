"""Сертификат методологии — структурные сторожа (P0.7 шаг 14).

Живая часть (обучение + декомпозиция + доезд до файла) — в
`test_methodology_cert_live.py`, она требует PyMC и в CI пропускается.
Здесь всё считается на словарях, поэтому идёт в CI.

Что стережём (следствия, не форму записи):
    1. канонизация недоступна → хеша НЕТ вовсе (прежний код тихо считал
       `json.dumps` и выдавал хеш, заведомо не сходящийся у проверяющего);
    2. в величинах сертификата не появляются подставленные нули;
    3. схема остаётся v1.3 — ровно пять полей: расширение без ответа
       проверяющей стороны ломает проверку на её конце;
    4. модель без паспорта воспроизводимости не выдаётся за заверенную;
    5. долг P0.6: неприменимая проверка отрицательной базы НЕ объявляется
       пройденной.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.methodology_cert import (  # noqa: E402
    CertificateUnavailable,
    build_cert_payload,
    compute_cert_hash,
    generate_methodology_certificate,
)

ПОЛЯ_СХЕМЫ_V13 = {
    'bundle_manifest_hash',
    'model_spec',
    'decomposition_summary',
    'channel_roi',
    'certificate_version',
}


def _модель(**переопределения):
    данные = {
        'model_version': '1.2',
        # Верхний уровень намеренно НЕ содержит описания: загрузчик модели
        # подставляет туда 'sales'/'normal' (`persistence.py:191-192`), и
        # сертификат обязан читать настоящее значение из конфигурации обучения
        # (аудит F-01 Critical).
        'kpi_type': 'sales',
        'kpi_likelihood': 'normal',
        'config': {'kpi_type': 'sales', 'kpi_likelihood': 'normal'},
        'channel_params': {'ТВ': {}, 'Диджитал': {}},
        'channel_adstock_types': {'ТВ': 'geometric', 'Диджитал': 'weibull'},
        'diagnostics': {},
    }
    данные.update(переопределения)
    return данные


def _разбивка(**переопределения):
    результат = {
        'status': 'ok',
        'total_sales': 10000.0,
        'baseline': 6000.0,
        'channels': [
            {'name': 'ТВ', 'contribution': 3000.0, 'roi': 2.5,
             'roi_ci_low': 1.9, 'roi_ci_high': 3.1},
            {'name': 'Диджитал', 'contribution': 1000.0, 'roi': 1.4},
        ],
    }
    результат.update(переопределения)
    return результат


def _манифест():
    return {
        'format': 'aurora-model',
        'format_version': '1',
        'created_at': '2026-08-03T09:00:00+00:00',
        'array_count': 7,
        'model_version': '1.2',
        'sha256_data': 'a' * 64,
        'sha256_arrays': 'b' * 64,
    }


# ── 1. Отказ вместо неверного хеша ───────────────────────────────────────────

def test_без_канонизации_хеша_нет(monkeypatch):
    """Следствие, а не форма: наружу не уходит хеш, посчитанный не по JCS.

    Прежнее поведение — предупреждение в журнал и `json.dumps(sort_keys=True)`:
    клиент получал сертификат, который у `verify.auroraai.pro` (Rust
    `serde_jcs`) не сошёлся бы никогда, и узнавал об этом на чужой стороне.
    """
    import builtins
    настоящий_импорт = builtins.__import__

    def без_rfc8785(имя, *args, **kwargs):
        if имя == 'rfc8785':
            raise ImportError('нет пакета (имитация окружения без канонизации)')
        return настоящий_импорт(имя, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', без_rfc8785)

    with pytest.raises(CertificateUnavailable):
        compute_cert_hash({'а': 1})

    итог = generate_methodology_certificate(_модель(), _разбивка(), _манифест())
    assert итог['status'] == 'unavailable'
    assert итог['hash'] is None, 'выдан хеш без канонизации'
    assert 'rfc8785' in итог['reason']


# ── 2. Нулей и подстановок нет ───────────────────────────────────────────────

def test_величин_нет_значит_отказ_а_не_ноль():
    """Пустой манифест, отсутствующий тип KPI, пустая разбивка — все три отказ."""
    with pytest.raises(CertificateUnavailable, match='анифест'):
        build_cert_payload(_модель(), _разбивка(), {})

    # Ни в конфигурации, ни в записи обучения типа метрики нет — заверять нечем.
    без_kpi = _модель(config={}, kpi_type=None)
    with pytest.raises(CertificateUnavailable, match='целевой метрики'):
        build_cert_payload(без_kpi, _разбивка(), _манифест())

    with pytest.raises(CertificateUnavailable):
        build_cert_payload(_модель(), _разбивка(channels=[]), _манифест())


def test_граница_roi_отсутствует_а_не_равна_нулю():
    """Канал без границ не получает `roi_ci_low = 0`.

    Ноль здесь — утверждение «нижняя граница окупаемости равна нулю», которого
    расчёт не делал. Прежний код подставлял его из-за приоритета операторов
    в тернарном выражении.
    """
    payload = build_cert_payload(_модель(), _разбивка(), _манифест())
    диджитал = payload['channel_roi']['Диджитал']
    assert 'roi_ci_low' not in диджитал and 'roi_ci_high' not in диджитал
    тв = payload['channel_roi']['ТВ']
    assert тв['roi_ci_low'] == 1.9 and тв['roi_ci_high'] == 3.1


def test_доли_считаются_от_одной_базы():
    """База и каналы — доли от общих продаж, не от разных знаменателей.

    В ответе декомпозера `baseline_pct` считается от общих продаж, а
    `contribution_pct` канала — от медиавклада: сложить их в один словарь
    значило бы выдать два числа разной природы под одним именем.
    """
    payload = build_cert_payload(_модель(), _разбивка(), _манифест())
    сводка = payload['decomposition_summary']
    assert сводка['Base']['contribution_pct'] == 60.0
    assert сводка['ТВ']['contribution_pct'] == 30.0
    assert сводка['Диджитал']['contribution_pct'] == 10.0
    assert abs(sum(v['contribution_pct'] for v in сводка.values()) - 100.0) < 0.01


# ── 3. Схема не расширяется ──────────────────────────────────────────────────

def test_схема_остаётся_v13():
    """Ровно пять полей.

    Проверяющая сторона десериализует payload в свою структуру и
    пересериализует: незнакомый ключ на любом уровне выпадает, и хеш перестаёт
    сходиться. Пока ответа от неё нет, схему трогать нельзя — поэтому
    воспроизводимость и статусы проверок живут РЯДОМ с payload.
    """
    итог = generate_methodology_certificate(_модель(), _разбивка(), _манифест())
    assert set(итог['payload'].keys()) == ПОЛЯ_СХЕМЫ_V13
    assert итог['payload']['certificate_version'] == '1.3'
    assert 'reproducibility' not in итог['payload']
    assert 'negative_baseline' not in итог['payload']
    assert 'checks' not in итог['payload']
    # …и при этом клиенту они доступны рядом.
    assert 'reproducibility' in итог and 'checks' in итог


def test_хеш_воспроизводим_и_меняется_от_данных():
    первый = generate_methodology_certificate(_модель(), _разбивка(), _манифест())
    второй = generate_methodology_certificate(_модель(), _разбивка(), _манифест())
    assert первый['hash'] == второй['hash']
    assert len(первый['hash']) == 64

    подменённый = _разбивка()
    подменённый['channels'][0]['roi'] = 9.9
    третий = generate_methodology_certificate(_модель(), подменённый, _манифест())
    assert третий['hash'] != первый['hash'], 'подмена ROI не изменила хеш'


# ── 4. Старая модель не выдаётся за заверенную ───────────────────────────────

def test_модель_без_паспорта_не_заверена():
    итог = generate_methodology_certificate(_модель(), _разбивка(), _манифест())
    assert итог['status'] == 'not_attested'
    assert итог['reproducibility']['status'] == 'absent'
    assert 'зерно' in итог['reason']
    # Хеш при этом честен для тех полей, что есть, — отказывать не за что.
    assert итог['hash'] is not None


def test_модель_с_паспортом_заверена():
    """Статус `issued` достижим — иначе первая проверка ничего не значит."""
    с_паспортом = _модель(reproducibility={
        'seed': 555, 'seed_source': 'config', 'sampler_tier': 'numpyro-nuts',
        'mcmc': {'chains': 2, 'draws': 200, 'tune': 200},
        'versions': {'python': '3.12.0', 'numpy': '1.26.4', 'pymc': '5.28.4'},
    })
    итог = generate_methodology_certificate(с_паспортом, _разбивка(), _манифест())
    assert итог['status'] == 'issued'
    assert итог['reason'] is None
    assert итог['reproducibility']['seed'] == 555
    assert итог['reproducibility']['seed_source'] == 'config'


# ── 5. Долг P0.6: неприменимая проверка не объявляется пройденной ────────────

@pytest.mark.parametrize('вердикт,чувствительна,ожидание', [
    ('ok', True, 'passed'),
    ('not_applicable', False, 'not_applicable'),
    ('ok', False, 'not_applicable'),   # ключевой случай долга
    ('watch', True, 'watch'),
    ('fail', True, 'failed'),
])
def test_статус_проверки_базы_честен(вердикт, чувствительна, ожидание):
    """«Годно» на данных, где проверка не могла провалиться, — ложь.

    Приор свободного члена делает отрицательную базу структурно недостижимой
    при малом разбросе продаж (замер P0.6: нужны 26 сигм на типовом проекте).
    Сертификат обязан различать «проверено» и «проверить не удалось».
    """
    модель = _модель(diagnostics={'negative_baseline': {
        'verdict': вердикт, 'detectable': чувствительна, 'prob_negative': 0.01,
    }})
    итог = generate_methodology_certificate(модель, _разбивка(), _манифест())
    assert итог['checks']['negative_baseline'] == ожидание


def test_проверки_базы_нет_значит_absent():
    итог = generate_methodology_certificate(_модель(), _разбивка(), _манифест())
    assert итог['checks']['negative_baseline'] == 'absent'


# ── 6. Находки внешнего аудита блока (2026-08-03) ────────────────────────────

def test_описание_модели_берётся_из_конфигурации_а_не_из_подстановки():
    """🔴 F-01 Critical. Загрузчик модели подставляет `kpi_type='sales'` и
    `kpi_likelihood='normal'` на верхний уровень (`persistence.py:191-192`), и
    прежняя проверка «нет величины → отказ» не срабатывала никогда: в хеш
    уезжала подстановка. Модель, обученную на знании марки, сертификат заверял
    как модель продаж.
    """
    подменённая = _модель(
        kpi_type='sales',            # ← подстановка загрузчика
        kpi_likelihood='normal',     # ← подстановка загрузчика
        config={'kpi_type': 'awareness'},   # ← настоящее значение
    )
    payload = build_cert_payload(подменённая, _разбивка(), _манифест())
    assert payload['model_spec']['kpi_type'] == 'awareness', (
        'в заверенное описание попала подстановка загрузчика, а не то, '
        'на чём модель обучали'
    )

    # Режим малых данных: обучение верхний уровень не пишет вовсе, поэтому всё,
    # что там видно, — подстановка загрузчика. Без конфигурации заверять нечего.
    ols_без_конфига = _модель(model_version='1.0-ols', kpi_type='sales', config={})
    with pytest.raises(CertificateUnavailable, match='целевой метрики'):
        build_cert_payload(ols_без_конфига, _разбивка(), _манифест())

    # Байесовская ветка пишет фактически применённое значение сама — это
    # законный источник, а не подстановка: отказывать здесь значило бы лишить
    # сертификата все модели, где тип метрики не задавали руками.
    байес_без_конфига = _модель(config={}, kpi_type='awareness')
    payload2 = build_cert_payload(байес_без_конфига, _разбивка(), _манифест())
    assert payload2['model_spec']['kpi_type'] == 'awareness'


def test_у_закрытой_формулы_правдоподобия_нет():
    """🔴 F-01. Вид правдоподобия существует только у байесовской ветки:
    печатать «normal» для МНК значит описывать модель, которой нет."""
    ols = _модель(model_version='1.0-ols', config={'kpi_type': 'sales'})
    payload = build_cert_payload(ols, _разбивка(), _манифест())
    assert 'kpi_likelihood' not in payload['model_spec']

    байес = _модель()
    assert 'kpi_likelihood' in build_cert_payload(байес, _разбивка(), _манифест())['model_spec']


def test_карта_адстоков_восстанавливается_из_конфигурации():
    """🔴 F-09 и его починка после аудита (Ф-01 High).

    Пустая карта не должна утверждать «адстоков нет» — но и заполнять её
    умолчанием нельзя: это ровно та подстановка, ради которой чинили Critical.
    Настоящий источник — конфигурация обучения; нет его — ключа нет вовсе.
    """
    из_конфига = _модель(
        channel_adstock_types={},
        config={'kpi_type': 'sales',
                'adstock_config': {'ТВ': 'geometric', 'Диджитал': 'weibull'}},
    )
    spec = build_cert_payload(из_конфига, _разбивка(), _манифест())['model_spec']
    assert spec['adstock_types'] == {'ТВ': 'geometric', 'Диджитал': 'weibull'}

    вовсе_без_источника = _модель(channel_adstock_types={}, config={'kpi_type': 'sales'})
    spec2 = build_cert_payload(вовсе_без_источника, _разбивка(), _манифест())['model_spec']
    assert 'adstock_types' not in spec2, 'подставлено умолчание вместо отказа от ключа'


def test_режим_малых_данных_заверяется_как_детерминированный():
    """🔴 F-02 High. У МНК паспорта прогона не бывает — зерно бутстрапа зашито
    в код. Говорить клиенту «модель обучена в ранней версии программы» о модели,
    обученной только что, — ложь, а совет переобучить не помог бы: малые данные
    снова ушли бы в тот же режим."""
    ols = _модель(model_version='1.0-ols', config={'kpi_type': 'sales'})
    итог = generate_methodology_certificate(ols, _разбивка(), _манифест())
    assert итог['reproducibility']['status'] == 'deterministic'
    assert итог['status'] == 'issued'
    assert итог['reason'] is None


def test_канал_с_неопределённой_окупаемостью_не_заверяется():
    """🔴 F-04 High. Декомпозер помечает канал без бюджета либо без обучаемой
    дисперсии маркером неприменимости и кладёт `roi = 0.0`. Расчёт не утверждал,
    что окупаемость нулевая — он утверждал, что она НЕ ОПРЕДЕЛЕНА."""
    разбивка = _разбивка()
    разбивка['channels'].append({
        'name': 'Радио', 'contribution': 0.0, 'roi': 0.0,
        'roi_ci_low': 0.0, 'roi_ci_high': 0.0,
        'ci_skip_reason': 'zero_spend', 'spend': 0.0,
    })
    payload = build_cert_payload(_модель(), разбивка, _манифест())
    assert 'Радио' not in payload['channel_roi'], (
        'заверена окупаемость 0 у канала, про который расчёт сказал «не определена»'
    )
    # Во вкладах канал остаётся: нулевой вклад — это факт, а не подстановка.
    assert payload['decomposition_summary']['Радио']['value'] == 0.0


def test_канал_с_именем_базы_даёт_отказ():
    """🔴 F-07. Имя канала приходит из столбца пользовательской таблицы;
    совпадение с ключом базы затирало её запись, и в хеш уходило неверное
    число под верным именем — без единого предупреждения."""
    разбивка = _разбивка()
    разбивка['channels'][0]['name'] = 'Base'
    with pytest.raises(CertificateUnavailable, match='Base'):
        build_cert_payload(_модель(), разбивка, _манифест())


def test_нечисловая_величина_даёт_человеческую_причину():
    """🔴 F-08. Канонизация не умеет `nan` и поднимала свою ошибку, чьё имя
    уезжало клиенту прямо в отчёт технической строкой."""
    разбивка = _разбивка()
    разбивка['channels'][0]['roi'] = float('nan')
    with pytest.raises(CertificateUnavailable) as отказ:
        build_cert_payload(_модель(), разбивка, _манифест())
    текст = str(отказ.value)
    assert 'не число' in текст and 'ТВ' in текст
    assert 'Error' not in текст, 'в причине техническое имя исключения'


def test_форма_чисел_в_хеше_зафиксирована():
    """🔴 F-10. Внутри хешируемого payload важна не только величина, но и её
    форма: смена округления долей молча изменила бы отпечаток у всех клиентов.
    Эталон ловит это, обычные проверки — нет."""
    payload = build_cert_payload(_модель(), _разбивка(), _манифест())
    assert payload['decomposition_summary'] == {
        'Base': {'value': 6000.0, 'contribution_pct': 60.0},
        'ТВ': {'value': 3000.0, 'contribution_pct': 30.0},
        'Диджитал': {'value': 1000.0, 'contribution_pct': 10.0},
    }
    assert payload['channel_roi'] == {
        'ТВ': {'roi': 2.5, 'roi_ci_low': 1.9, 'roi_ci_high': 3.1},
        'Диджитал': {'roi': 1.4},
    }
    # Эталонный отпечаток той же фикстуры. Если он изменился — изменился и
    # отпечаток у КАЖДОГО клиента: такую правку принимают осознанно, а не
    # замечают постфактум по жалобе проверяющей стороны.
    assert compute_cert_hash(payload) == (
        '3447d616b883604b1f45d3b83b473b587767dfe3d0862328f026f930f796b8b6'
    ), 'отпечаток фикстуры изменился — проверьте, что это намеренно'


def test_округление_доли_зафиксировано_на_неровных_числах():
    """🔴 F-10, вторая половина. Первая версия этого сторожа мутацию
    «округление 2 → 1 знак» ПРОПУСТИЛА: доли основной фикстуры ровные
    (60/30/10), и обе трактовки дают одно число. Различие живёт только на
    неровных долях — тот же урок, что с денежными строками при разборе запятой.
    """
    неровная = _разбивка(total_sales=10000.0, baseline=6123.45, channels=[
        {'name': 'ТВ', 'contribution': 2876.55, 'roi': 2.5},
    ])
    payload = build_cert_payload(_модель(), неровная, _манифест())
    сводка = payload['decomposition_summary']
    assert сводка['Base']['contribution_pct'] == 61.23
    assert сводка['ТВ']['contribution_pct'] == 28.77


def test_карта_адстоков_берётся_из_настоящего_источника():
    """🔴 Аудит починки, Ф-01 High: первая версия достраивала карту через
    `get_adstock_type`, а тот читает ту же пустую карту и отдаёт `geometric`
    всем. У режима малых данных карты не бывает никогда — в хеш уезжало бы
    `geometric` даже там, где пользователь выбрал Вейбулла.
    """
    ols = _модель(
        model_version='1.0-ols',
        channel_adstock_types={},
        config={'kpi_type': 'sales',
                'adstock_config': {'ТВ': 'weibull', 'Диджитал': 'geometric'}},
    )
    spec = build_cert_payload(ols, _разбивка(), _манифест())['model_spec']
    assert spec['adstock_types'] == {'ТВ': 'weibull', 'Диджитал': 'geometric'}, (
        'в заверенное описание уехал подставленный тип адстока'
    )


def test_карта_адстоков_не_собирается_наполовину():
    """Частичная карта утверждала бы об остальных каналах то, чего мы не знаем."""
    неполная = _модель(
        model_version='1.0-ols',
        channel_adstock_types={},
        config={'kpi_type': 'sales', 'adstock_config': {'ТВ': 'weibull'}},
    )
    spec = build_cert_payload(неполная, _разбивка(), _манифест())['model_spec']
    assert 'adstock_types' not in spec


def test_причина_отказа_не_содержит_имени_исключения():
    """🔴 Ф-03. Клиентская половина починки F-08 — замена технической строки в
    широком перехвате декомпозера — не была покрыта ничем."""
    from engines.decomposer import _build_methodology_certificate

    class ЛомающаясяМодель(dict):
        def get(self, *args, **kwargs):  # noqa: D102
            raise RuntimeError('внутренний сбой')

    итог = _build_methodology_certificate(ЛомающаясяМодель(), _разбивка(), Path('нет.pkl'))
    assert итог['status'] == 'unavailable'
    assert 'Error' not in итог['reason'] and 'error' not in итог['reason']
    assert итог['hash'] is None


def test_настройка_auto_не_выдаётся_за_тип_адстока():
    """🔴 Третий аудит, High: на реальных проектах и в конфигурации, и в
    параметрах каналов стоит `'auto'` — настройка «выбери сам», а не тип.
    Движок такого типа не знает и молча считает по геометрическому, а сертификат
    утверждал `auto` под именем «фактически применённый тип». Третий раз тот же
    класс, что F-01 и Ф-01.
    """
    авто = _модель(
        model_version='1.0-ols',
        channel_adstock_types={},
        config={'kpi_type': 'sales',
                'adstock_config': {'ТВ': 'auto', 'Диджитал': 'auto'}},
    )
    spec = build_cert_payload(авто, _разбивка(), _манифест())['model_spec']
    assert 'adstock_types' not in spec, (
        f'настройка уехала в заверенное описание: {spec.get("adstock_types")}'
    )

    # Настоящий тип в той же позиции — проходит.
    настоящий = _модель(
        model_version='1.0-ols',
        channel_adstock_types={},
        config={'kpi_type': 'sales',
                'adstock_config': {'ТВ': 'weibull', 'Диджитал': 'geometric'}},
    )
    spec2 = build_cert_payload(настоящий, _разбивка(), _манифест())['model_spec']
    assert spec2['adstock_types'] == {'ТВ': 'weibull', 'Диджитал': 'geometric'}


def test_auto_отфильтровывается_и_из_карты_модели():
    """Тот же фильтр на первом источнике: карта модели тоже может нести `auto`
    (замер на клиентском проекте «кагоцел» — там именно так)."""
    из_карты = _модель(channel_adstock_types={'ТВ': 'auto', 'Диджитал': 'auto'})
    spec = build_cert_payload(из_карты, _разбивка(), _манифест())['model_spec']
    assert 'adstock_types' not in spec
