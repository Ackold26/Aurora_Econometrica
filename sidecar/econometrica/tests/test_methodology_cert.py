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
        'kpi_type': 'sales',
        'kpi_likelihood': 'normal',
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

    без_kpi = _модель(kpi_type=None)
    with pytest.raises(CertificateUnavailable, match='kpi_type'):
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
