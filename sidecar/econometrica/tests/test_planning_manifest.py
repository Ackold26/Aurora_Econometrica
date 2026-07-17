"""Тесты save_planning_manifest — запись results/planning.json (P-1).

Манифест planning.json связывает сохранённые сценарии с отчётностью: без него
PPTX/HTML/XLSX-раздел прогноза «не найден», даже когда scenarios/*.json есть.
"""
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engines.planning import save_planning_manifest, load_saved_forecast  # noqa: E402


def _write_scenario(project_dir: Path, name: str, kpi: float = 1000.0) -> None:
    """Кладёт results/scenarios/<name>.json в ЛЕГАСИ-схеме (top-level ключи).

    P-2 (2026-07-16): реальный scenario-движок пишет суммы в totals.* — эта
    форма покрыта в _write_scenario_real ниже; легаси-форма осталась тестом
    fallback-чтения.
    """
    sc_dir = project_dir / "results" / "scenarios"
    sc_dir.mkdir(parents=True, exist_ok=True)
    with open(sc_dir / f"{name}.json", "w", encoding="utf-8") as f:
        json.dump({
            "name": name,
            "predictions": [10.0, 20.0],
            "predictions_ci_low": [8.0, 16.0],
            "predictions_ci_high": [12.0, 24.0],
            "total_kpi": kpi,
            "total_spend_money": 500.0,
            "roas_money": 2.0,
            "disclaimers": ["прогноз при неизменных прочих условиях"],
            "future_dates": ["2025-01-01", "2025-02-01"],
        }, f, ensure_ascii=False)


def _write_scenario_real(project_dir: Path, name: str) -> None:
    """Реальная схема сценария — как её пишет scenario-движок (см. демо
    «Базовый план.json»): суммы в totals.*, имя в scenario_name, spend для
    физметрик отсутствует (null)."""
    sc_dir = project_dir / "results" / "scenarios"
    sc_dir.mkdir(parents=True, exist_ok=True)
    with open(sc_dir / f"{name}.json", "w", encoding="utf-8") as f:
        json.dump({
            "status": "ok",
            "scenario_name": name,
            "n_periods": 2,
            "predictions": [100.0, 110.0],
            "predictions_ci_low": [90.0, 99.0],
            "predictions_ci_high": [110.0, 121.0],
            "totals": {
                "predicted_kpi": 210.0,
                "predicted_kpi_ci_low": 189.0,
                "predicted_kpi_ci_high": 231.0,
                "total_spend": 30.0,          # native units (TRP) — НЕ деньги
                "total_spend_money": None,    # физметрики: денег нет
                "roas_money": None,
            },
            "disclaimers": ["прогноз при неизменных прочих условиях"],
            "future_dates": ["2026-01-31T00:00:00", "2026-02-28T00:00:00"],
        }, f, ensure_ascii=False)


class TestSavePlanningManifest:
    def test_writes_planning_json(self, tmp_path: Path):
        _write_scenario(tmp_path, "Базовый план")
        res = save_planning_manifest(str(tmp_path), ["Базовый план"], "Базовый план", ["оговорка"])
        assert res["status"] == "ok"
        assert res["accepted_variant"] == "Базовый план"
        pj = tmp_path / "results" / "planning.json"
        assert pj.exists()
        data = json.loads(pj.read_text(encoding="utf-8"))
        assert data["variant_ids"] == ["Базовый план"]
        assert data["accepted_variant"] == "Базовый план"
        assert data["disclaimers"] == ["оговорка"]

    def test_accepted_defaults_to_first(self, tmp_path: Path):
        _write_scenario(tmp_path, "v1")
        res = save_planning_manifest(str(tmp_path), ["v1", "v2"], None, None)
        assert res["accepted_variant"] == "v1"

    def test_accepted_invalid_falls_back_to_first(self, tmp_path: Path):
        res = save_planning_manifest(str(tmp_path), ["v1"], "nonexistent", None)
        assert res["accepted_variant"] == "v1"

    def test_empty_variant_ids_is_error_no_file(self, tmp_path: Path):
        res = save_planning_manifest(str(tmp_path), [], None, None)
        assert res["status"] == "error"
        assert not (tmp_path / "results" / "planning.json").exists()

    def test_blank_ids_filtered_out(self, tmp_path: Path):
        res = save_planning_manifest(str(tmp_path), ["", None], None, None)  # type: ignore[list-item]
        assert res["status"] == "error"

    def test_roundtrip_with_load_saved_forecast(self, tmp_path: Path):
        """Манифест + легаси-сценарий → fallback-чтение top-level ключей живо."""
        _write_scenario(tmp_path, "Базовый план", kpi=5000.0)
        save_planning_manifest(str(tmp_path), ["Базовый план"], "Базовый план", [])
        loaded = load_saved_forecast(str(tmp_path))
        assert loaded is not None
        assert loaded["status"] == "ok"
        assert loaded["accepted_variant"] == "Базовый план"
        assert len(loaded["scenarios"]) == 1
        assert loaded["scenarios"][0]["total_kpi"] == 5000.0

    def test_load_saved_forecast_real_scenario_schema(self, tmp_path: Path):
        """P-2 регресс (2026-07-16): реальная схема сценария (totals.*) обязана
        мапиться в builder-поля — прежний код читал вымышленные top-level ключи
        и слайд получал нули."""
        _write_scenario_real(tmp_path, "Базовый план")
        save_planning_manifest(str(tmp_path), ["Базовый план"], "Базовый план", [])
        loaded = load_saved_forecast(str(tmp_path))
        assert loaded is not None
        sc = loaded["scenarios"][0]
        assert sc["name"] == "Базовый план"          # из scenario_name
        assert sc["total_kpi"] == 210.0               # из totals.predicted_kpi
        assert sc["total_kpi_ci_low"] == 189.0        # интервал СУММЫ за горизонт
        assert sc["total_kpi_ci_high"] == 231.0
        # INV-50: отсутствующие деньги остаются None («—» в отчёте), НЕ 0.0
        assert sc["total_spend_money"] is None
        assert sc["roas_money"] is None

    def test_load_saved_forecast_missing_values_stay_none(self, tmp_path: Path):
        """INV-50: сценарий без totals и без легаси-ключей → None, не ложный 0."""
        sc_dir = tmp_path / "results" / "scenarios"
        sc_dir.mkdir(parents=True, exist_ok=True)
        with open(sc_dir / "v1.json", "w", encoding="utf-8") as f:
            json.dump({"predictions": [1.0], "disclaimers": []}, f)
        save_planning_manifest(str(tmp_path), ["v1"], "v1", [])
        loaded = load_saved_forecast(str(tmp_path))
        assert loaded is not None
        sc = loaded["scenarios"][0]
        assert sc["total_kpi"] is None
        assert sc["total_spend_money"] is None
        assert sc["roas_money"] is None
        assert sc["total_kpi_ci_low"] is None
        assert sc["total_kpi_ci_high"] is None
