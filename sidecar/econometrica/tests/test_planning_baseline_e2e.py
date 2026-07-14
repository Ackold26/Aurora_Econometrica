"""E2E прокси-гейт P-1: авто-прогноз базового плана + манифест на РЕАЛЬНОМ движке.

Проксирует живой прогон P-1 без GUI (proxy_gate-паттерн): весь backend-путь,
который PlanningStep.computeBaseline вызывает через IPC —
  predict_scenario(baseline, carry_in=True) -> results/scenarios/<name>.json
  -> save_planning_manifest -> results/planning.json
  -> load_saved_forecast -> раздел прогноза для PPTX/HTML/XLSX оживает.
Переиспользует каркас _make_model_with_posterior из test_planning_carryin_e2e.
"""
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from test_planning_carryin_e2e import _make_model_with_posterior  # noqa: E402

BASELINE = 'Базовый план'


class TestBaselineForecastPlusManifestE2E:
    """Полная backend-цепочка P-1 на реальном движке (то, что делает
    PlanningStep.computeBaseline + saveManifest), доказанная числами."""

    def test_baseline_scenario_then_manifest_then_section(self, tmp_path: Path):
        # 1. Реальная OLS-модель + синтетический posterior (CI-веер) + высокий
        #    TV-хвост (carry-in ощутим) — как настоящий проект пользователя.
        project_dir = _make_model_with_posterior(tmp_path, with_posterior=True, tv_decay=0.9)

        from engines.scenario import predict_scenario
        from engines.planning import save_planning_manifest, load_saved_forecast

        # 2. Baseline: медиаплан «из файла» (P-1 берёт mp.channels as-is), carry_in=True.
        media_plan = {'tv': [2e6] * 6, 'digital': [1e6] * 6}
        future_dates = [d.strftime('%Y-%m-%d')
                        for d in pd.date_range('2026-01-01', periods=6, freq='MS')]
        sc = predict_scenario({
            'scenario_name': BASELINE,
            'media_plan': media_plan,
            'forecast_periods': 6,
            'future_dates': future_dates,
            'carry_in': True,
        }, project_dir)

        assert sc['status'] == 'ok', sc
        # Форма, которую PlanningStep кладёт в baselineForecast + ContinuationChart:
        assert len(sc['predictions']) == 6
        assert sc['predictions_ci_low'] is not None and sc['predictions_ci_high'] is not None
        assert len(sc['predictions_ci_low']) == 6 and len(sc['predictions_ci_high']) == 6
        # carry-in реально применён (P-1 передаёт carry_in=True)
        assert sc['carry_in_applied'] is True
        # disclaimers (INV-50) присутствуют — уедут в раздел отчёта
        assert sc.get('disclaimers') and any('неизменных' in d for d in sc['disclaimers'])
        # future_dates проброшены (ось графика)
        assert sc.get('future_dates') == future_dates
        # scenario-файл записан под именем базового плана (= ключ манифеста)
        sc_path = Path(project_dir) / 'results' / 'scenarios' / f'{BASELINE}.json'
        assert sc_path.exists(), 'econ_scenario должен сохранить scenarios/<baseline>.json'

        # A-2: tv/digital без unit_costs → total_spend_money None (карточка ₽ скрыта).
        assert sc['totals'].get('total_spend_money') is None

        # 3. Автозапись манифеста (P-1 saveManifest -> econ_save_planning).
        res = save_planning_manifest(project_dir, [BASELINE], BASELINE, sc['disclaimers'])
        assert res['status'] == 'ok'
        assert res['accepted_variant'] == BASELINE
        assert (Path(project_dir) / 'results' / 'planning.json').exists()

        # 4. Раздел прогноза ОЖИВАЕТ: load_saved_forecast читает манифест + сценарий
        #    (без этого PPTX/HTML/XLSX-раздел «не найден» — корень жалобы приёмки).
        loaded = load_saved_forecast(project_dir)
        assert loaded is not None, 'раздел прогноза должен грузиться из манифеста'
        assert loaded['status'] == 'ok'
        assert loaded['accepted_variant'] == BASELINE
        assert len(loaded['scenarios']) == 1
        assert loaded['scenarios'][0]['variant_id'] == BASELINE
        assert len(loaded['scenarios'][0]['predictions']) == 6
        assert loaded['disclaimers'], 'disclaimers должны доехать до раздела'

    def test_baseline_carryin_actually_raises_vs_off(self, tmp_path: Path):
        """Разделяющий зонд: carry_in=True (P-1) поднимает прогноз vs carry_in=False.
        Доказывает, что baseline-путь P-1 реально прогоняет медиаэффект хвоста."""
        project_dir = _make_model_with_posterior(tmp_path, with_posterior=True, tv_decay=0.9)
        from engines.scenario import predict_scenario

        plan = {'tv': [2e6] * 6, 'digital': [1e6] * 6}
        on = predict_scenario({
            'scenario_name': BASELINE, 'media_plan': plan,
            'forecast_periods': 6, 'carry_in': True,
        }, project_dir)
        off = predict_scenario({
            'scenario_name': 'baseline_off', 'media_plan': plan,
            'forecast_periods': 6, 'carry_in': False,
        }, project_dir)

        assert on['status'] == 'ok' and off['status'] == 'ok'
        assert on['predictions'][0] > off['predictions'][0], (
            f"carry-in P-1 должен поднять predictions[0]: "
            f"on={on['predictions'][0]:.0f} off={off['predictions'][0]:.0f}"
        )
