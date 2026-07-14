"""Регресс-тест A3: run_rolling_backtest передаёт 'forecast_periods' в predict_scenario.

Дыра A3 (закрыта): backtest активирует planning-режим carry-in через
  'forecast_periods': len(test_df)
в двух местах: single-holdout (~строка 176) и rolling-окна (~строка 668).

Без этого ключа первые точки окна занижаются (adstock-хвост не переносится),
MAPE завышается и вердикт несправедливо становится worse_than_naive.

Подход (spy): монкипатчим engines.ols_modeler.train_ols и
engines.scenario.predict_scenario на быстрые заглушки, которые:
  - train_stub: немедленно возвращает {'status': 'ok', ...} без MCMC/OLS
  - predict_stub: захватывает полученный config в список, возвращает
    валидный {'status': 'ok', 'predictions': [float]*len} нужной длины

Затем Assert: для КАЖДОГО захваченного config есть ключ 'forecast_periods',
значение == числу периодов в media_plan (= len(test-окна)).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# ─── Синтетические данные и обучение OLS ─────────────────────────────────────

def _make_data(tmp_path: Path, n: int = 40) -> Path:
    """40 месяцев синтетики — достаточно для ≥2 rolling-окон."""
    rng = np.random.RandomState(0)
    dates = pd.date_range("2021-01-01", periods=n, freq="MS")
    tv = rng.uniform(1e6, 3e6, n)
    digital = rng.uniform(5e5, 2e6, n)
    sales = 5_000_000 + 0.3 * tv + 0.2 * digital + rng.normal(0, 200_000, n)
    df = pd.DataFrame({"date": dates, "tv": tv, "digital": digital, "sales": sales})
    p = tmp_path / "data.xlsx"
    df.to_excel(p, index=False)
    return p


def _train_real(data_file: Path, project_dir: str) -> dict:
    """Реальное OLS-обучение — нужно только для подготовки pickle модели."""
    from engines.ols_modeler import train_ols
    return train_ols(
        {
            "data_file": str(data_file),
            "kpi_column": "sales",
            "media_columns": ["tv", "digital"],
            "control_columns": [],
            "date_column": "date",
            "adstock_config": {"tv": "geometric", "digital": "geometric"},
            "unit_costs": {},
            "kpi_type": "sales",
            "kpi_unit_cost": None,
            "merge_rules": {},
            "channel_categories": {},
        },
        project_dir,
    )


# ─── Заглушки ────────────────────────────────────────────────────────────────

def _make_train_stub():
    """Возвращает заглушку train_ols, которая мгновенно отвечает status=ok."""

    def train_stub(config: dict, project_dir: str) -> dict:
        return {
            "status": "ok",
            "diagnostics": {
                "metrics": {"r_squared": 0.9, "mape": 5.0},
            },
            "model_path": str(Path(project_dir) / "models" / "latest.pkl"),
        }

    return train_stub


def _make_predict_stub(captured_configs: list):
    """Возвращает заглушку predict_scenario, захватывающую config в список.

    Возвращает валидный результат нужной длины — бэктест доходит до конца.
    """

    def predict_stub(config: dict, project_dir: str) -> dict[str, Any]:
        captured_configs.append(dict(config))  # deep-copy ключей config
        # Определяем длину по media_plan (первый канал)
        media_plan = config.get("media_plan", {})
        first_channel = next(iter(media_plan.values()), [])
        n = len(first_channel)
        base_val = 5_000_000.0
        return {
            "status": "ok",
            "predictions": [base_val] * n,
            "predictions_ci_low": None,
            "predictions_ci_high": None,
            "carry_in_applied": True,
            "totals": {
                "predicted_kpi": base_val * n,
                "predicted_kpi_ci_low": None,
                "predicted_kpi_ci_high": None,
                "total_spend": 0.0,
                "total_spend_money": None,
                "roas": 0.0,
                "roas_money": None,
            },
            "disclaimers": ["Прогноз при неизменных прочих условиях"],
        }

    return predict_stub


# ─── Тест: rolling-бэктест передаёт forecast_periods ────────────────────────

class TestBacktestCarryInActivation:
    """A3 регресс: run_rolling_backtest передаёт forecast_periods=len(test_df)
    в каждый вызов predict_scenario (активирует carry-in adstock).
    """

    def test_forecast_periods_passed_to_predict_scenario(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Главный assert: forecast_periods присутствует в каждом захваченном config
        и равен числу периодов media_plan (= длине test-окна).
        """
        # 1. Реальное обучение — нужен pickle для run_rolling_backtest
        data_file = _make_data(tmp_path, n=40)
        result = _train_real(data_file, str(tmp_path))
        assert result["status"] == "ok", f"Обучение упало: {result}"

        # 2. Захватываем конфиги predict_scenario
        captured_configs: list[dict] = []

        # Патчим обучение окон (быстро, без реальной OLS в каждом окне)
        monkeypatch.setattr(
            "engines.ols_modeler.train_ols", _make_train_stub()
        )
        # Патчим predict_scenario на spy-обёртку
        monkeypatch.setattr(
            "engines.scenario.predict_scenario", _make_predict_stub(captured_configs)
        )

        # 3. Запускаем rolling-backtest
        from engines.backtest import run_rolling_backtest
        bt_result = run_rolling_backtest(
            str(tmp_path),
            mode="ols",
            max_windows=4,
            save=False,
        )

        # Smoke: бэктест дошёл до конца (не упал на мок-данных)
        assert bt_result.get("status") in ("ok", "insufficient", "validated", "worse_than_naive"), (
            f"run_rolling_backtest вернул неожиданный статус: {bt_result}"
        )

        # 4. Spy должен был захватить хотя бы один вызов
        assert len(captured_configs) >= 1, (
            "predict_scenario не был вызван — spy не сработал. "
            f"Статус бэктеста: {bt_result.get('status')}, "
            f"message: {bt_result.get('message', '')}"
        )

        # 5. ГЛАВНЫЙ ASSERT: каждый config имеет forecast_periods == len(media_plan[ch])
        for i, cfg in enumerate(captured_configs):
            # Ключ обязателен
            assert "forecast_periods" in cfg, (
                f"Окно #{i}: 'forecast_periods' отсутствует в config predict_scenario. "
                f"Ключи: {list(cfg.keys())}. "
                "Это означает, что A3-правка (активация carry-in) не применяется."
            )

            # Значение совпадает с длиной media_plan (= длина test-окна)
            media_plan = cfg.get("media_plan", {})
            assert media_plan, f"Окно #{i}: media_plan пустой в config"
            expected_len = len(next(iter(media_plan.values())))
            actual_fp = cfg["forecast_periods"]
            assert actual_fp == expected_len, (
                f"Окно #{i}: forecast_periods={actual_fp} != len(test_window)={expected_len}. "
                "Carry-in активируется на неверную длину."
            )

    def test_forecast_periods_equals_test_window_length(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Точный контроль: forecast_periods совпадает с horizon_periods бэктеста.

        Если мы передаём horizon_periods=3, каждое test-окно имеет 3 точки,
        и именно 3 должно быть в forecast_periods.
        """
        data_file = _make_data(tmp_path, n=40)
        result = _train_real(data_file, str(tmp_path))
        assert result["status"] == "ok", f"Обучение упало: {result}"

        captured_configs: list[dict] = []
        monkeypatch.setattr("engines.ols_modeler.train_ols", _make_train_stub())
        monkeypatch.setattr(
            "engines.scenario.predict_scenario", _make_predict_stub(captured_configs)
        )

        from engines.backtest import run_rolling_backtest
        horizon = 3
        bt_result = run_rolling_backtest(
            str(tmp_path),
            horizon_periods=horizon,
            mode="ols",
            max_windows=4,
            save=False,
        )

        # Только если бэктест дошёл до окон
        if bt_result.get("status") in ("insufficient",):
            pytest.skip(f"Истории недостаточно для окон с horizon={horizon}: {bt_result.get('message')}")

        assert len(captured_configs) >= 1, (
            f"predict_scenario не вызван. Статус: {bt_result}"
        )

        for i, cfg in enumerate(captured_configs):
            assert "forecast_periods" in cfg, (
                f"Окно #{i}: forecast_periods отсутствует. Ключи: {list(cfg.keys())}"
            )
            fp = cfg["forecast_periods"]
            # forecast_periods должен совпадать с заданным horizon
            assert fp == horizon, (
                f"Окно #{i}: forecast_periods={fp}, ожидается horizon={horizon}"
            )

    def test_no_regression_without_forecast_periods_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Антирегресс: если в будущем код уберёт forecast_periods, тест красный.

        Проверяем что scenario_config строится с ключом, а не без него (проверка
        через spy-перехват фактического dict, переданного predict_scenario).
        """
        data_file = _make_data(tmp_path, n=40)
        result = _train_real(data_file, str(tmp_path))
        assert result["status"] == "ok"

        all_keys_sets: list[set] = []

        def spy_keys(config: dict, project_dir: str) -> dict:
            all_keys_sets.append(set(config.keys()))
            media_plan = config.get("media_plan", {})
            n = len(next(iter(media_plan.values()), []))
            return {
                "status": "ok",
                "predictions": [5_000_000.0] * n,
                "predictions_ci_low": None,
                "predictions_ci_high": None,
                "carry_in_applied": bool(config.get("forecast_periods")),
                "totals": {
                    "predicted_kpi": 5_000_000.0 * n,
                    "predicted_kpi_ci_low": None,
                    "predicted_kpi_ci_high": None,
                    "total_spend": 0.0,
                    "total_spend_money": None,
                    "roas": 0.0,
                    "roas_money": None,
                },
                "disclaimers": ["Прогноз при неизменных прочих условиях"],
            }

        monkeypatch.setattr("engines.ols_modeler.train_ols", _make_train_stub())
        monkeypatch.setattr("engines.scenario.predict_scenario", spy_keys)

        from engines.backtest import run_rolling_backtest
        bt_result = run_rolling_backtest(
            str(tmp_path), mode="ols", max_windows=3, save=False
        )

        if not all_keys_sets:
            # Бэктест не дошёл до predict_scenario (нет окон) — smoke-only
            assert bt_result.get("status") in ("insufficient",), (
                f"Неожиданный статус при 0 вызовах predict_scenario: {bt_result}"
            )
            return

        # Все вызовы должны содержать forecast_periods
        for i, keys in enumerate(all_keys_sets):
            assert "forecast_periods" in keys, (
                f"Вызов #{i} predict_scenario не содержит 'forecast_periods'. "
                f"Ключи: {keys}. "
                "РЕГРЕССИЯ A3: carry-in adstock не активируется в бэктесте."
            )
