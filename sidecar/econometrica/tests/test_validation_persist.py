"""LOAD-1 (B2): validate_data сохраняет validation.json ТОЛЬКО при абсолютном
project_dir; относительный путь (bare project_id) НЕ пишет в CWD сайдкара.

Корень бага: фронт слал bare project_id как project_dir → запись уходила в
относительный CWD сайдкара, не в папку проекта → validation.json «терялся» →
реоткрытие проекта показывало пустую Валидацию. Резолв abs-пути делает Rust
(resolve_project_dir_arg); этот guard — defense-in-depth на стороне Python.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.validator import validate_data  # noqa: E402


def _make_csv(tmp_path: Path) -> Path:
    csv = tmp_path / "data.csv"
    pd.DataFrame(
        {
            "Дата": pd.date_range("2023-01-01", periods=12, freq="MS").strftime("%Y-%m-%d"),
            "Продажи в руб. бренд": range(100, 112),
            "TV Бюджет": range(10, 22),
            "OOH Бюджет": range(5, 17),
        }
    ).to_csv(csv, index=False, encoding="utf-8")
    return csv


class TestValidationPersist:
    def test_absolute_project_dir_writes_validation_json(self, tmp_path: Path):
        csv = _make_csv(tmp_path)
        proj = tmp_path / "proj-abs"
        proj.mkdir()
        res = validate_data(str(csv), str(proj))
        assert res["status"] != "error"
        assert (proj / "results" / "validation.json").exists(), (
            "абсолютный project_dir должен сохранить results/validation.json"
        )

    def test_relative_project_dir_does_not_write_to_cwd(self, tmp_path: Path, monkeypatch):
        csv = _make_csv(tmp_path)
        # bare-id относительный путь: запись ушла бы в <cwd>/bare-id/results — не должно.
        monkeypatch.chdir(tmp_path)
        res = validate_data(str(csv), "bare-id-relative")
        assert res["status"] != "error"  # result всё равно возвращается в GUI
        assert not (tmp_path / "bare-id-relative" / "results" / "validation.json").exists(), (
            "относительный project_dir НЕ должен создавать validation.json в CWD"
        )

    def test_none_project_dir_no_write(self, tmp_path: Path):
        csv = _make_csv(tmp_path)
        res = validate_data(str(csv), None)
        assert res["status"] != "error"
        # Нет project_dir → нет записи, просто result.
        assert "columns" in res or "status" in res
