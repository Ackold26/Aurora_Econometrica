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
    """Кладёт results/scenarios/<name>.json в форме, которую ждёт load_saved_forecast."""
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
        """Манифест + сценарий → load_saved_forecast читает раздел прогноза (раздел жив)."""
        _write_scenario(tmp_path, "Базовый план", kpi=5000.0)
        save_planning_manifest(str(tmp_path), ["Базовый план"], "Базовый план", [])
        loaded = load_saved_forecast(str(tmp_path))
        assert loaded is not None
        assert loaded["status"] == "ok"
        assert loaded["accepted_variant"] == "Базовый план"
        assert len(loaded["scenarios"]) == 1
        assert loaded["scenarios"][0]["total_kpi"] == 5000.0
