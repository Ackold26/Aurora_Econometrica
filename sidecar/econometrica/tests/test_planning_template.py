"""Тесты для planning-mode команд: генерация шаблона + подтверждение медиаплана.

Покрытие:
  1. generate_media_plan_template: N строк будущего, даты продолжены верно,
     медиа/KPI пусты в будущих строках, исторические строки сохранены.
  2. confirm_media_plan(confirmed=True): записывает confirmed=true в media_plan.json.
  3. confirm_media_plan(confirmed=False): записывает confirmed=false.
  4. confirm_media_plan без файла: возвращает status='error'.

Тесты не используют реальные данные — только синтетические fixtures (tmp_path).
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.planning import confirm_media_plan, generate_media_plan_template


# ─── Вспомогательные фабрики ─────────────────────────────────────────────────


def _make_project(tmp_path: Path, n_history: int = 24) -> Path:
    """Создаёт минимальный проект: models/latest.pkl + data/data.xlsx.

    Pickle содержит ключи, которые generate_media_plan_template умеет читать.
    Возвращает project_dir.
    """
    project_dir = tmp_path / "project"
    data_dir = project_dir / "data"
    models_dir = project_dir / "models"
    data_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    # Генерируем синтетический xlsx (только исторические строки)
    rng = np.random.RandomState(42)
    dates = pd.date_range("2022-01-01", periods=n_history, freq="MS")
    df = pd.DataFrame(
        {
            "date": dates,
            "sales": rng.uniform(100, 1000, n_history),
            "tv_spend": rng.uniform(10, 100, n_history),
            "digital_spend": rng.uniform(5, 50, n_history),
        }
    )
    data_file = data_dir / "data.xlsx"
    df.to_excel(data_file, index=False)

    # Минимальный pickle-конфиг
    model_config = {
        "media_columns": ["tv_spend", "digital_spend"],
        "kpi_column": "sales",
        "date_column": "date",
        "data_file": str(data_file),
        "control_columns": [],
    }
    with open(models_dir / "latest.pkl", "wb") as f:
        pickle.dump(model_config, f)

    return project_dir


def _make_media_plan_json(project_dir: Path, confirmed: bool = False) -> Path:
    """Создаёт results/media_plan.json с минимальной структурой."""
    results_dir = project_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    mp_path = results_dir / "media_plan.json"
    data = {
        "n_future_periods": 12,
        "period_labels": ["2024-01"],
        "granularity": "M",
        "future_dates": ["2024-01-01T00:00:00"],
        "channels": {"tv_spend": [None] * 12, "digital_spend": [None] * 12},
        "warnings": [],
        "source_hash": "a" * 64,
        "confirmed": confirmed,
    }
    mp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return mp_path


# ─── Тест 1: генерация шаблона — N строк будущего ────────────────────────────


def test_template_generates_n_future_rows(tmp_path):
    """generate_media_plan_template: N строк будущего существуют в xlsx."""
    project_dir = _make_project(tmp_path, n_history=24)
    n_future = 12

    result = generate_media_plan_template(str(project_dir), n_future_periods=n_future)

    assert result["status"] == "ok", f"Ожидали status=ok, получили: {result}"
    out_path = Path(result["path"])
    assert out_path.exists(), f"Файл шаблона не создан: {out_path}"

    df_out = pd.read_excel(out_path)
    assert len(df_out) == 24 + n_future, (
        f"Ожидали {24 + n_future} строк (24 история + {n_future} будущее), "
        f"получили {len(df_out)}"
    )


def test_template_future_dates_are_continued(tmp_path):
    """generate_media_plan_template: даты будущего продолжают ряд месячной гранулярности."""
    project_dir = _make_project(tmp_path, n_history=24)  # последний месяц = 2023-12-01

    result = generate_media_plan_template(str(project_dir), n_future_periods=3)
    assert result["status"] == "ok"

    df_out = pd.read_excel(out_path := Path(result["path"]))
    df_out["date"] = pd.to_datetime(df_out["date"])
    future_dates = df_out["date"].iloc[24:]  # первые 3 строки будущего

    # Первая дата будущего должна быть 2024-01-01 (следующий месяц за 2023-12-01)
    first_future = future_dates.iloc[0]
    assert first_future.year == 2024 and first_future.month == 1, (
        f"Ожидали 2024-01, получили {first_future.date()}"
    )
    # Следующий месяц
    second_future = future_dates.iloc[1]
    assert second_future.year == 2024 and second_future.month == 2, (
        f"Ожидали 2024-02, получили {second_future.date()}"
    )


def test_template_media_kpi_empty_in_future_rows(tmp_path):
    """generate_media_plan_template: медиа и KPI пусты в строках будущего."""
    project_dir = _make_project(tmp_path, n_history=24)
    n_future = 6

    result = generate_media_plan_template(str(project_dir), n_future_periods=n_future)
    assert result["status"] == "ok"

    df_out = pd.read_excel(Path(result["path"]))
    future_slice = df_out.iloc[24:]  # последние n_future строк

    for col in ["sales", "tv_spend", "digital_spend"]:
        assert col in df_out.columns, f"Колонка {col!r} отсутствует в шаблоне"
        assert future_slice[col].isna().all(), (
            f"Колонка {col!r} должна быть пустой в строках будущего, "
            f"но содержит: {future_slice[col].dropna().tolist()}"
        )


def test_template_historical_rows_preserved(tmp_path):
    """generate_media_plan_template: исторические строки сохраняются без изменений."""
    project_dir = _make_project(tmp_path, n_history=24)

    # Читаем оригинальный файл
    data_file = project_dir / "data" / "data.xlsx"
    df_original = pd.read_excel(data_file)

    result = generate_media_plan_template(str(project_dir), n_future_periods=12)
    assert result["status"] == "ok"

    df_out = pd.read_excel(Path(result["path"]))
    history_slice = df_out.iloc[:24]

    # KPI в исторических строках должны совпадать с оригиналом
    assert history_slice["sales"].notna().all(), "KPI истории не должны быть пустыми"
    np.testing.assert_allclose(
        history_slice["sales"].values,
        df_original["sales"].values,
        rtol=1e-5,
        err_msg="Исторические KPI-значения изменились в шаблоне",
    )


def test_template_no_model_returns_error(tmp_path):
    """generate_media_plan_template без модели → status='error'."""
    project_dir = tmp_path / "empty_project"
    project_dir.mkdir()

    result = generate_media_plan_template(str(project_dir), n_future_periods=12)

    assert result["status"] == "error", f"Ожидали status=error, получили: {result}"
    assert "message" in result


def test_template_atomic_write_creates_exports_dir(tmp_path):
    """generate_media_plan_template: создаёт exports/ если её не было."""
    project_dir = _make_project(tmp_path, n_history=12)
    exports_dir = project_dir / "exports"
    assert not exports_dir.exists(), "exports/ уже существовал — тест невалиден"

    result = generate_media_plan_template(str(project_dir), n_future_periods=6)
    assert result["status"] == "ok"
    assert exports_dir.exists(), "exports/ должна быть создана автоматически"
    assert (exports_dir / "media_plan_template.xlsx").exists()


# ─── Тест 2: confirm_media_plan(confirmed=True) ───────────────────────────────


def test_confirm_true_writes_confirmed_flag(tmp_path):
    """confirm_media_plan(confirmed=True) записывает confirmed=true в media_plan.json."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    mp_path = _make_media_plan_json(project_dir, confirmed=False)

    result = confirm_media_plan(str(project_dir), confirmed=True)

    assert result["status"] == "ok", f"Ожидали status=ok, получили: {result}"
    data = json.loads(mp_path.read_text(encoding="utf-8"))
    assert data["confirmed"] is True, f"confirmed должен быть True, получили: {data['confirmed']}"


# ─── Тест 3: confirm_media_plan(confirmed=False) ──────────────────────────────


def test_confirm_false_writes_confirmed_flag(tmp_path):
    """confirm_media_plan(confirmed=False) записывает confirmed=false."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    mp_path = _make_media_plan_json(project_dir, confirmed=True)

    result = confirm_media_plan(str(project_dir), confirmed=False)

    assert result["status"] == "ok", f"Ожидали status=ok, получили: {result}"
    data = json.loads(mp_path.read_text(encoding="utf-8"))
    assert data["confirmed"] is False, f"confirmed должен быть False, получили: {data['confirmed']}"


def test_confirm_preserves_other_fields(tmp_path):
    """confirm_media_plan не затирает другие поля media_plan.json."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    mp_path = _make_media_plan_json(project_dir, confirmed=False)

    original = json.loads(mp_path.read_text(encoding="utf-8"))
    confirm_media_plan(str(project_dir), confirmed=True)
    updated = json.loads(mp_path.read_text(encoding="utf-8"))

    # source_hash, n_future_periods и т.д. не должны измениться
    for key in ("n_future_periods", "granularity", "source_hash"):
        assert updated[key] == original[key], (
            f"Поле {key!r} изменилось после confirm: {original[key]!r} → {updated[key]!r}"
        )


# ─── Тест 4: confirm_media_plan без файла ────────────────────────────────────


def test_confirm_missing_file_returns_error(tmp_path):
    """confirm_media_plan без media_plan.json → status='error'."""
    project_dir = tmp_path / "empty_project"
    project_dir.mkdir()
    # media_plan.json НЕ создаём

    result = confirm_media_plan(str(project_dir), confirmed=True)

    assert result["status"] == "error", f"Ожидали status=error, получили: {result}"
    assert "message" in result
    assert "not found" in result["message"] or "не найд" in result["message"].lower()


def test_template_closed_loop_on_trained_model(tmp_path):
    """F-AVT-3 (живой прогон): замкнутый цикл U5 на РЕАЛЬНОЙ обученной модели.
    Скачал шаблон → заполнил media в будущих строках → validate_data →
    media_plan_detected.channels непустой. Ловит: голый pickle.load падал на
    моделях с posterior; date_column не в config → детект даты из файла."""
    import numpy as np
    import pandas as pd
    from engines.validator import validate_data
    from engines.ols_modeler import train_ols
    from engines.planning import generate_media_plan_template

    # обучающая фикстура с кириллическими каналами (без хвоста — чистая история)
    rng = np.random.default_rng(11)
    n = 24
    dates = pd.date_range('2024-01-31', periods=n, freq='ME')
    tv = rng.uniform(2e6, 5e6, n).round(-3)
    olv = rng.uniform(1e6, 3e6, n).round(-3)
    sales = (8e6 + 1.2 * tv + 2.0 * olv).round(-3)
    train_file = tmp_path / 'train.xlsx'
    pd.DataFrame({'Дата': dates, 'Продажи': sales, 'ТВ': tv, 'Онлайн-видео': olv}).to_excel(train_file, index=False)
    proj = tmp_path / 'proj'
    proj.mkdir()
    validate_data(str(train_file), str(proj))
    train_ols({'data_file': str(train_file), 'kpi_column': 'Продажи',
               'media_columns': ['ТВ', 'Онлайн-видео'], 'control_columns': [],
               'kpi_type': 'sales', 'mode': 'ols'}, str(proj))

    # 1. генерим шаблон на обученной модели (не голый pickle — load_model_with_compat)
    r = generate_media_plan_template(str(proj), 6)
    assert r.get('status') == 'ok', r.get('message')
    tmpl = pd.read_excel(r['path'])
    assert tmpl.shape[0] == 30  # 24 истории + 6 будущих
    media_cols = ['ТВ', 'Онлайн-видео']
    fut = tmpl['Продажи'].isna()
    assert int(fut.sum()) == 6
    assert bool(tmpl.loc[fut, media_cols].isna().all().all()), 'media в будущем должны быть пустыми'

    # 2. клиент заполняет будущие инвестиции
    for c in media_cols:
        tmpl.loc[fut, c] = 3_000_000.0
    filled = tmp_path / 'filled.xlsx'
    tmpl.to_excel(filled, index=False)

    # 3. замкнутый цикл: validate → детекция хвоста
    proj2 = tmp_path / 'proj2'
    proj2.mkdir()
    v = validate_data(str(filled), str(proj2))
    mpd = v.get('media_plan_detected') or {}
    assert mpd.get('n_future_periods') == 6, 'заполненный шаблон должен детектироваться'
    assert set(mpd.get('channels', {})) == set(media_cols), 'channels должны совпасть с каналами модели'
