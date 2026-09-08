"""Сторож (2026-09-08, внешний аудит, находка High-1): предполётная проверка
обязана строить симуляцию по ТЕМ ЖЕ мастер-флагам контролей, по которым будет
собрана обучаемая модель.

Дефект, который сторож закрывает
--------------------------------
Обучение собирает модель по мастер-флагам `use_holidays` (`modeler.py:484`) и
`use_seasonality` (`modeler.py:569`) и передаёт их в проверку приоров
(`modeler.py:857-862`). Предполётная проверка их не передавала, а класс запроса
`PreflightRequest` их вовсе не содержал — интерфейс их и не слал. Симуляция
всегда шла с праздниками РФ (~12 столбцов) и рядами Фурье, то есть оценивала
не ту модель, которую клиент собрался обучать.

Проверено зондом на демо-наборе продукта (`static/sample-data/synth_fmcg_brand.xlsx`,
48 наблюдений): при выключенных праздниках и сезонности предполётная проверка
давала покрытие 0,896 «pass» → уровень `reliable`, а та же симуляция по пути
обучения — 0,458 «fail» → `insufficient`. Клиенту, выключившему контроли,
показывался ЗАВЫШЕННЫЙ вердикт надёжности, причём максимально завышенный:
«надёжно» вместо «данных недостаточно».

Что сторож утверждает
---------------------
1. Выключенные праздники — в симуляции нет праздничных столбцов.
2. Выключенная сезонность — в симуляции нет рядов Фурье.
3. Включённые (и умолчание, когда полей в запросе нет) — контроли на месте:
   старые клиенты, не присылающие поля, едут ровно как раньше.
4. Два пути согласны: предполётная проверка и вызов, который делает обучение,
   на одном наборе с одинаковыми флагами дают один набор контролей и один
   вердикт.
5. Структурный рубеж: оба вызова `prior_predictive_check` в продукте передают
   мастер-флаги, а интерфейс и команда Tauri их доставляют — правка в одной
   точке из четырёх ровно этим дефектом и была.
6. Реальный путь по HTTP: тело, которое собирает команда Tauri
   (`econometrica.rs:702-715`), доезжает до вердикта, и ключ в camelCase-написании
   работает наравне со snake_case.

Дыра, найденная приёмкой правки (2026-09-08)
--------------------------------------------
Проверки выше строят `PreflightRequest` объектом напрямую — это мимо слоя, на
котором живёт риск. Прогон через `TestClient` показал: тело с ключами
`useSeasonality`/`useHolidays` (написание интерфейса) давало код 200 и уровень
`reliable` вместо `insufficient` — pydantic выбрасывал неизвестный ключ МОЛЧА,
продукт возвращался ровно к аудированному дефекту, и ни одна проверка не краснела.
Класс тот же, что чинил внешний аудит: молчаливая потеря флага между слоями.
Закрыто двумя написаниями ключа в `PreflightRequest` и сторожем на HTTP-пути.

Пороги (0,5 / 0,8 покрытия) сторож не трогает: правится ОСНОВАНИЕ вердикта,
а не критерий.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import utils.reliability_a4 as a4
from server import PreflightRequest, preflight

N_OBS = 48
FIRST_DATE = '2022-01-31'

REPO_ROOT = Path(__file__).resolve().parents[3]
SIDECAR_ROOT = Path(__file__).resolve().parents[1]


def _body(response) -> dict:
    return json.loads(response.body)


def _write_csv(path: Path) -> pd.DataFrame:
    """Месячный ряд с выраженной сезонностью — на нём набор контролей
    реально влияет на покрытие, поэтому подмена флагов заметна.
    Каналы не коллинеарны, иначе вердикт решит quick_proxy по своей причине.

    Амплитуда волны 900 выбрана замером, а не на глаз: при 300 покрытие без
    контролей выходит ровно 0,500 — впритык к порогу отказа, и вердикт `warn`
    против `fail` решался бы третьим знаком. При 900 разведение уверенное:
    оба флага включены — 0,896 `pass` → `reliable`, оба выключены — 0,458 `fail`
    → `insufficient`. Пороги при этом не трогаются, меняется только набор."""
    dates = pd.date_range(FIRST_DATE, periods=N_OBS, freq='ME')
    tv = [100 + (i * 37) % 90 for i in range(N_OBS)]
    digital = [40 + (i * 53) % 70 for i in range(N_OBS)]
    season = [900 * np.sin(2 * np.pi * i / 12) for i in range(N_OBS)]
    sales = [1000 + i * 7 + season[i] + (tv[i] % 17) * 3 for i in range(N_OBS)]
    df = pd.DataFrame({
        'date': dates.strftime('%Y-%m-%d'),
        'sales': sales,
        'tv': tv,
        'digital': digital,
    })
    df.to_csv(path, index=False, encoding='utf-8')
    return df


def _request(tmp_path: Path, csv_path: Path, **flags) -> PreflightRequest:
    """Ровно те поля, что шлёт интерфейс (ConfigPanel.svelte), плюс мастер-флаги.
    Без flags — умолчание класса запроса (прежнее поведение)."""
    return PreflightRequest(
        project_dir=str(tmp_path),
        file_path=str(csv_path),
        media_columns=['tv', 'digital'],
        kpi_column='sales',
        date_column='date',
        mode_override=None,
        skip_prior_predictive=False,
        **flags,
    )


def _controls(content: dict) -> dict:
    pp = content['breakdown']['prior_predictive']
    assert pp is not None, 'проверка приоров не выполнилась — сторож не проверил путь'
    return pp.get('control_components') or {}


class TestPreflightHonorsMasterFlags:

    def test_holidays_off_removes_holiday_columns(self, tmp_path):
        csv_path = tmp_path / 'data.csv'
        _write_csv(csv_path)

        content = _body(preflight(_request(tmp_path, csv_path, use_holidays=False)))
        assert content['status'] == 'ok'
        controls = _controls(content)

        assert 'holidays' not in controls, (
            'Праздники выключены, но симуляция предполётной проверки всё равно '
            f'построена с ними ({controls.get("holidays")}): вердикт надёжности '
            'считается по модели, которой у клиента не будет, и завышается'
        )
        assert 'fourier' in controls, (
            'Выключение праздников не должно снимать сезонность — флаги независимы'
        )

    def test_seasonality_off_removes_fourier_terms(self, tmp_path):
        csv_path = tmp_path / 'data.csv'
        _write_csv(csv_path)

        content = _body(preflight(_request(tmp_path, csv_path, use_seasonality=False)))
        assert content['status'] == 'ok'
        controls = _controls(content)

        assert 'fourier' not in controls, (
            'Сезонность выключена, но симуляция построена с рядами Фурье '
            f'({controls.get("fourier")}) — вердикт завышен'
        )
        assert 'holidays' in controls, (
            'Выключение сезонности не должно снимать праздники — флаги независимы'
        )

    def test_both_off_leaves_no_controls(self, tmp_path):
        csv_path = tmp_path / 'data.csv'
        _write_csv(csv_path)

        content = _body(preflight(_request(
            tmp_path, csv_path, use_seasonality=False, use_holidays=False)))
        assert content['status'] == 'ok'
        assert _controls(content) == {}, (
            'Оба мастер-флага выключены, а контрольные регрессоры в симуляции есть'
        )

    def test_both_on_keeps_controls(self, tmp_path):
        csv_path = tmp_path / 'data.csv'
        _write_csv(csv_path)

        content = _body(preflight(_request(
            tmp_path, csv_path, use_seasonality=True, use_holidays=True)))
        controls = _controls(content)
        assert 'fourier' in controls and 'holidays' in controls, (
            f'Флаги включены, но контроли в симуляции неполны: {controls}'
        )

    def test_absent_flags_keep_previous_behaviour(self, tmp_path):
        """Запрос старого клиента (полей нет вовсе) обязан вести себя как раньше:
        флаги включены, симуляция полная. Это условие совместимости правки."""
        csv_path = tmp_path / 'data.csv'
        _write_csv(csv_path)

        content = _body(preflight(_request(tmp_path, csv_path)))
        controls = _controls(content)
        assert 'fourier' in controls and 'holidays' in controls, (
            f'Умолчание изменилось — старые клиенты поедут иначе: {controls}'
        )

    def test_flags_actually_change_the_verdict(self, tmp_path):
        """Флаг обязан менять не только состав контролей, но и вердикт —
        иначе передача формальна и дефект вернётся незамеченным."""
        csv_path = tmp_path / 'data.csv'
        _write_csv(csv_path)

        on = _body(preflight(_request(tmp_path, csv_path)))
        off = _body(preflight(_request(
            tmp_path, csv_path, use_seasonality=False, use_holidays=False)))

        cov_on = on['breakdown']['prior_predictive']['coverage']
        cov_off = off['breakdown']['prior_predictive']['coverage']
        assert cov_off < cov_on, (
            f'Покрытие без контролей ({cov_off}) не ниже покрытия с ними ({cov_on}): '
            'похоже, флаги до симуляции не доехали'
        )


class TestTwoPathsAgree:
    """Согласие двух дорог: предполётная проверка и обучение обязаны строить
    симуляцию из одного набора контролей и приходить к одному вердикту."""

    @pytest.mark.parametrize('use_seasonality,use_holidays', [
        (True, True), (False, False), (True, False), (False, True),
    ])
    def test_preflight_matches_in_train_call(self, tmp_path, use_seasonality, use_holidays):
        csv_path = tmp_path / 'data.csv'
        df = _write_csv(csv_path)

        content = _body(preflight(_request(
            tmp_path, csv_path,
            use_seasonality=use_seasonality, use_holidays=use_holidays)))
        pf = content['breakdown']['prior_predictive']

        # Ровно тот вызов, который делает обучение (modeler.py:857-862):
        # тот же набор, те же флаги, то же число выборок и тот же посев.
        in_train = a4.prior_predictive_check(
            df['sales'].fillna(0).values.astype(float),
            df[['tv', 'digital']].fillna(0).values.astype(float),
            n_samples=300,
            dates=pd.to_datetime(df['date']).values,
            use_seasonality=use_seasonality,
            use_holidays=use_holidays,
        )

        assert (pf.get('control_components') or {}) == (in_train.get('control_components') or {}), (
            'Набор контролей предполётной проверки не совпал с набором обучения: '
            f'{pf.get("control_components")} против {in_train.get("control_components")}'
        )
        assert pf['coverage'] == in_train['coverage'], (
            f'Покрытие разошлось: предполётная {pf["coverage"]}, обучение {in_train["coverage"]}'
        )
        assert pf['status'] == in_train['status'], (
            f'Вердикт разошёлся: предполётная «{pf["status"]}», обучение «{in_train["status"]}» — '
            'клиент видит один вердикт, а получит модель с другим'
        )


class TestBothCallSitesPassFlags:
    """Структурный рубеж. Дефект был именно «правка в одной точке из двух»,
    поэтому сторож читает исходники обоих вызовов."""

    @pytest.mark.parametrize('rel_path', ['server.py', 'engines/modeler.py'])
    def test_call_site_has_master_flag_keywords(self, rel_path):
        src_path = SIDECAR_ROOT / rel_path
        tree = ast.parse(src_path.read_text(encoding='utf-8'))

        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == 'prior_predictive_check'
        ]
        assert calls, f'вызов prior_predictive_check в {rel_path} не найден'
        for call in calls:
            kwargs = {kw.arg for kw in call.keywords}
            missing = {'use_seasonality', 'use_holidays'} - kwargs
            assert not missing, (
                f'{rel_path}:{call.lineno}: prior_predictive_check вызвана без {sorted(missing)} — '
                'симуляция снова оценивает не ту модель, которую соберёт обучение'
            )

    def test_request_model_exposes_flags(self):
        fields = PreflightRequest.model_fields
        assert 'use_seasonality' in fields and 'use_holidays' in fields, (
            'PreflightRequest без мастер-флагов: интерфейс физически не может их '
            'прислать, и pydantic молча отбросит их при разборе запроса'
        )
        assert fields['use_seasonality'].default is True
        assert fields['use_holidays'].default is True


class TestClientPathDeliversFlags:
    """Клиентская дорога (то, что видит покупатель): интерфейс → команда Tauri →
    класс запроса. Питоновские рубежи выше бесполезны, если поля не отправлены."""

    def _read(self, rel_path: str) -> str:
        path = REPO_ROOT / rel_path
        if not path.exists():   # прогон из упакованного каталога движка
            pytest.skip(f'{rel_path} недоступен из этого каталога прогона')
        return path.read_text(encoding='utf-8')

    def test_config_panel_sends_flags_to_preflight(self):
        src = self._read('src/lib/components/ConfigPanel.svelte')
        call = re.search(r"invoke\('econ_preflight',\s*\{(.*?)\}\)\)", src, re.S)
        assert call, 'вызов econ_preflight в ConfigPanel.svelte не найден'
        payload = call.group(1)
        for field in ('useSeasonality', 'useHolidays'):
            assert field in payload, (
                f'ConfigPanel.svelte не шлёт {field} в econ_preflight — '
                'предполётная проверка снова получит умолчание «включено» и '
                'завысит вердикт клиенту, который контроли выключил'
            )

    def test_tauri_command_forwards_flags(self):
        src = self._read('src-tauri/src/commands/econometrica.rs')
        start = src.index('pub async fn econ_preflight')
        end = src.index('post_json("/compute/preflight"', start)
        body = src[start:end]
        for field in ('use_seasonality', 'use_holidays'):
            assert f'"{field}"' in body, (
                f'econ_preflight не кладёт {field} в тело запроса — поле теряется '
                'между интерфейсом и движком'
            )
            assert f'{field}: Option<bool>' in body, (
                f'econ_preflight не принимает {field} параметром'
            )
        assert body.count('unwrap_or(true)') >= 2, (
            'умолчание мастер-флагов в команде Tauri должно быть «включено» — '
            'иначе старые вызовы поедут иначе'
        )


class TestFlagsSurviveTheHttpLayer:
    """Сторож на слое, где живёт риск: реальный запрос по HTTP тем телом, которое
    собирает команда Tauri (`econometrica.rs:702-715`), а не объект `PreflightRequest`,
    построенный в обход разбора запроса."""

    def _client(self):
        from fastapi.testclient import TestClient
        import server
        return TestClient(server.app)

    def _rust_body(self, tmp_path: Path, csv_path: Path, *, camel: bool,
                   use_seasonality: bool, use_holidays: bool) -> dict:
        """Тело дословно как в `econometrica.rs`: те же ключи и тот же порядок.
        camel=True — написание интерфейса (`useSeasonality`), то самое, на котором
        приёмка нашла молчаливую потерю флага."""
        body = {
            'project_dir': str(tmp_path),
            'file_path': str(csv_path),
            'media_columns': ['tv', 'digital'],
            'control_columns': [],
            'kpi_column': 'sales',
            'date_column': 'date',
            'adstock_config': {},
            'mode_override': None,
            'skip_prior_predictive': False,
        }
        if camel:
            body['useSeasonality'] = use_seasonality
            body['useHolidays'] = use_holidays
        else:
            body['use_seasonality'] = use_seasonality
            body['use_holidays'] = use_holidays
        return body

    @pytest.mark.parametrize('use_seasonality,use_holidays,expected_tier', [
        (True, True, 'reliable'),
        (False, False, 'insufficient'),
    ])
    def test_snake_case_body_reaches_the_verdict(self, tmp_path, use_seasonality,
                                                 use_holidays, expected_tier):
        csv_path = tmp_path / 'data.csv'
        _write_csv(csv_path)

        response = self._client().post('/compute/preflight', json=self._rust_body(
            tmp_path, csv_path, camel=False,
            use_seasonality=use_seasonality, use_holidays=use_holidays))
        assert response.status_code == 200
        content = response.json()
        assert content['status'] == 'ok'
        assert content['overall_tier'] == expected_tier, (
            f'По HTTP при флагах {use_seasonality}/{use_holidays} уровень '
            f'«{content["overall_tier"]}» вместо «{expected_tier}» — флаги не доехали '
            'сквозь разбор запроса'
        )

    @pytest.mark.parametrize('use_seasonality,use_holidays', [
        (True, True), (False, False), (True, False), (False, True),
    ])
    def test_camel_case_keys_give_the_same_verdict(self, tmp_path, use_seasonality,
                                                   use_holidays):
        """Ключ в написании интерфейса обязан работать наравне со snake_case.
        Иначе рассинхрон слоёв (или опечатка в будущей правке команды Tauri)
        МОЛЧА вернёт продукт к аудированному дефекту: pydantic выбросит
        неизвестный ключ без ошибки, ответ останется 200, вердикт — завышенным."""
        csv_path = tmp_path / 'data.csv'
        _write_csv(csv_path)
        client = self._client()

        snake = client.post('/compute/preflight', json=self._rust_body(
            tmp_path, csv_path, camel=False,
            use_seasonality=use_seasonality, use_holidays=use_holidays))
        camel = client.post('/compute/preflight', json=self._rust_body(
            tmp_path, csv_path, camel=True,
            use_seasonality=use_seasonality, use_holidays=use_holidays))

        assert snake.status_code == camel.status_code == 200
        snake_body, camel_body = snake.json(), camel.json()
        assert camel_body['overall_tier'] == snake_body['overall_tier'], (
            f'camelCase-тело дало уровень «{camel_body["overall_tier"]}», '
            f'snake_case — «{snake_body["overall_tier"]}»: ключ потерян молча, '
            'вердикт вернулся к завышенному, а код ответа остался 200'
        )
        snake_pp = snake_body['breakdown']['prior_predictive']
        camel_pp = camel_body['breakdown']['prior_predictive']
        assert (camel_pp.get('control_components') or {}) == (snake_pp.get('control_components') or {})
        assert camel_pp['coverage'] == snake_pp['coverage']

    def test_unknown_extra_fields_are_still_accepted(self, tmp_path):
        """Границы доработки: лишние поля запроса по-прежнему не отвергаются —
        `extra='forbid'` сломал бы прочих клиентов. Правка узкая, только про
        два написания мастер-флагов."""
        csv_path = tmp_path / 'data.csv'
        _write_csv(csv_path)

        body = self._rust_body(tmp_path, csv_path, camel=False,
                               use_seasonality=True, use_holidays=True)
        body['совершенно_постороннее_поле'] = 'значение'
        response = self._client().post('/compute/preflight', json=body)
        assert response.status_code == 200
        assert response.json()['status'] == 'ok'
