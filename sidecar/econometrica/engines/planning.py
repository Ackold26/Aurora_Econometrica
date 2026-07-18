"""SSOT-модуль детекции хвоста медиаплана (planning mode).

Задача: в одном Excel-файле после исторических строк (KPI заполнен) может
идти «хвост будущего» — строки с пустым KPI и заполненными инвестициями.
Этот модуль распознаёт границу истории/будущего и возвращает чистые DataFrame
без сайд-эффектов.

Публичное API:
  detect_media_plan_tail(df, date_col, kpi_col, media_cols) -> dict
  compute_source_hash(data_file) -> str
  load_frames(data_file, date_col, kpi_col, media_cols) -> dict
  load_saved_forecast(project_dir) -> dict | None
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Размер блока для хэша (первые 512 КБ — дёшево, детерминированно)
_HASH_READ_BYTES = 512 * 1024


# ─── Вспомогательные ────────────────────────────────────────────────────────


def _period_label(dt: "pd.Timestamp", granularity: str) -> str:
    """Человекочитаемый ярлык периода по гранулярности."""
    if granularity == "M":
        return dt.strftime("%Y-%m")
    if granularity == "W":
        iso = dt.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if granularity == "D":
        return dt.strftime("%Y-%m-%d")
    if granularity == "Q":
        q = (dt.month - 1) // 3 + 1
        return f"{dt.year}-Q{q}"
    if granularity == "Y":
        return str(dt.year)
    return dt.strftime("%Y-%m-%d")


def _expected_next(last_hist: "pd.Timestamp", granularity: str) -> "pd.Timestamp":
    """Ожидаемая первая дата будущего (ровно один период за последней историей)."""
    if granularity == "D":
        return last_hist + pd.Timedelta(days=1)
    if granularity == "W":
        return last_hist + pd.Timedelta(weeks=1)
    if granularity == "M":
        return last_hist + pd.DateOffset(months=1)
    if granularity == "Q":
        return last_hist + pd.DateOffset(months=3)
    if granularity == "Y":
        return last_hist + pd.DateOffset(years=1)
    # Для «unknown» / прочих — используем медианный шаг как запас, возвращаем None-sentinel
    return last_hist + pd.Timedelta(days=1)


def _days_gap_tolerance(granularity: str) -> float:
    """Допустимое отклонение от «ровного» следующего периода (в днях).

    Месяцы имеют 28-31 день — нужен более широкий допуск.
    """
    return {
        "D": 0.5,
        "W": 1.0,
        "M": 5.0,
        "Q": 10.0,
        "Y": 30.0,
    }.get(granularity, 3.0)


# ─── Основная функция ────────────────────────────────────────────────────────


def detect_media_plan_tail(
    df: "pd.DataFrame",
    date_col: str,
    kpi_col: str,
    media_cols: list[str],
) -> dict[str, Any]:
    """Обнаружить хвост медиаплана в DataFrame.

    Аргументы:
        df: DataFrame со смешанными историческими строками и строками плана.
        date_col: имя колонки с датами.
        kpi_col: имя KPI-колонки (продажи).
        media_cols: список колонок инвестиций/медиа.

    Возвращает dict:
        {found: False}  — хвоста нет.
        {found: False, error: 'no_history'}  — весь KPI пуст.
        {found: False, reason: 'internal_gaps'}  — NaN в середине истории (не хвост).
        {
            found: True,
            n_future_periods: int,
            history_df: DataFrame,
            future_df: DataFrame,
            future_dates: [isoformat str],
            period_labels: [str],
            granularity: str ('D'|'W'|'M'|'Q'|'Y'|'unknown'),
            channels: {col: [float]},
            continuous: bool,
            warnings: [{type, message}],
        }
    """
    # Работаем на копии, не трогаем оригинал
    work = df.copy()

    # Приводим даты и сортируем
    work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
    work = work.sort_values(date_col).reset_index(drop=True)

    kpi = work[kpi_col]

    # Случай 1: весь KPI пуст
    if kpi.last_valid_index() is None:
        return {"found": False, "error": "no_history"}

    last_idx = len(work) - 1

    # Случай 2: хвоста нет — последняя строка заполнена
    if pd.notna(kpi.iloc[-1]):
        return {"found": False}

    # Граница истории: последний индекс с непустым KPI
    boundary = int(kpi.last_valid_index())  # type: ignore[arg-type]

    # Хвост = строки после boundary
    tail_kpi = kpi.iloc[boundary + 1:]

    # Случай 3: проверка непрерывности хвоста.
    # Все строки ПОСЛЕ boundary должны иметь пустой KPI.
    # Если хоть одна строка хвоста имеет непустой KPI — это дыры в середине, не хвост.
    if tail_kpi.notna().any():
        return {"found": False, "reason": "internal_gaps"}

    history_df = work.iloc[: boundary + 1].copy()
    future_df = work.iloc[boundary + 1 :].copy()

    # Определяем гранулярность по истории
    from utils.forecast_validation import detect_granularity  # SSOT

    gran_result = detect_granularity(history_df[date_col])
    granularity: str = gran_result.get("granularity", "W")

    warnings: list[dict[str, str]] = []

    # Проверка непрерывности дат (A8)
    last_hist_date = history_df[date_col].dropna().iloc[-1]
    first_future_date = future_df[date_col].dropna().iloc[0]
    expected = _expected_next(last_hist_date, granularity)
    gap_days = abs((first_future_date - expected).total_seconds()) / 86400
    tolerance = _days_gap_tolerance(granularity)
    continuous = gap_days <= tolerance

    if not continuous:
        warnings.append(
            {
                "type": "date_gap",
                "message": (
                    f"Разрыв дат между историей и будущим: ожидалась {expected.date()}, "
                    f"получена {first_future_date.date()} "
                    f"(отклонение {gap_days:.1f} дн. при допуске {tolerance} дн.)."
                ),
            }
        )

    # Предупреждение: пустые медиа в будущем
    for col in media_cols:
        if col in future_df.columns:
            if future_df[col].isna().any():
                warnings.append(
                    {
                        "type": "empty_media_in_future",
                        "message": f"Колонка «{col}» содержит пустые значения в строках плана.",
                    }
                )

    # Собираем каналы: {col: [float]} — NaN → None для JSON-безопасности
    channels: dict[str, list[Any]] = {}
    for col in media_cols:
        if col in future_df.columns:
            vals = future_df[col].tolist()
            channels[col] = [float(v) if pd.notna(v) else None for v in vals]

    future_dates = [
        ts.isoformat() if pd.notna(ts) else None
        for ts in future_df[date_col]
    ]
    period_labels = [
        _period_label(ts, granularity) if pd.notna(ts) else ""
        for ts in future_df[date_col]
    ]

    return {
        "found": True,
        "n_future_periods": len(future_df),
        "history_df": history_df,
        "future_df": future_df,
        "future_dates": future_dates,
        "period_labels": period_labels,
        "granularity": granularity,
        "channels": channels,
        "continuous": continuous,
        "warnings": warnings,
    }


# ─── Хэш файла ──────────────────────────────────────────────────────────────


def compute_source_hash(data_file: str) -> str:
    """SHA-256 первых 512 КБ + размер файла.

    Детерминирован, дёшев — для сверки «тот ли файл был при обучении».

    Args:
        data_file: путь к xlsx/csv.

    Returns:
        hex-строка SHA-256 (64 символа).
    """
    p = Path(data_file)
    file_size = p.stat().st_size
    h = hashlib.sha256()
    with open(p, "rb") as f:
        chunk = f.read(_HASH_READ_BYTES)
        h.update(chunk)
    # Добавляем размер файла в хэш для устойчивости к коротким файлам
    h.update(file_size.to_bytes(8, "big"))
    return h.hexdigest()


# ─── Обёртка для чтения файла ────────────────────────────────────────────────


def _read_file(path: Path) -> "pd.DataFrame":
    """Читаем xlsx/csv в DataFrame (переиспользуем логику validator)."""
    if path.suffix in (".xlsx", ".xls"):
        return pd.read_excel(path)
    if path.suffix == ".csv":
        # C1: CSV русского Excel с «;» в качестве разделителя
        df = pd.read_csv(path)
        if df.shape[1] == 1 and ";" in str(df.columns[0]):
            df = pd.read_csv(path, sep=";")
        return df
    raise ValueError(f"Неподдерживаемый формат: {path.suffix}. Нужен xlsx или csv.")


def load_frames(
    data_file: str,
    date_col: str | None = None,
    kpi_col: str | None = None,
    media_cols: list[str] | None = None,
) -> dict[str, Any]:
    """SSOT-точка входа: читает файл, авто-детектирует роли, разделяет историю/план.

    Аргументы:
        data_file: путь к xlsx/csv.
        date_col: имя колонки дат (если None — автодетект).
        kpi_col: имя KPI-колонки (если None — автодетект).
        media_cols: список медиа-колонок (если None — автодетект).

    Возвращает:
        {
            history_df: DataFrame с историческими строками,
            future_df: DataFrame | None — строки медиаплана или None,
            detection: dict — результат detect_media_plan_tail,
            source_hash: str,
        }

    Без сайд-эффектов: никакой записи файлов.
    """
    path = Path(data_file)
    df = _read_file(path)

    # Автодетект ролей при необходимости
    if date_col is None or kpi_col is None or media_cols is None:
        from engines.validator import detect_column_role_with_confidence

        detected_date: str | None = None
        detected_kpi: str | None = None
        detected_media: list[str] = []

        for col in df.columns:
            role, _conf = detect_column_role_with_confidence(col)
            if role == "date" and detected_date is None:
                detected_date = str(col)
            elif role == "kpi" and detected_kpi is None:
                detected_kpi = str(col)
            elif role == "media":
                detected_media.append(str(col))

        if date_col is None:
            date_col = detected_date
        if kpi_col is None:
            kpi_col = detected_kpi
        if media_cols is None:
            media_cols = detected_media

    if not date_col:
        raise ValueError("Не удалось определить колонку дат. Передайте date_col явно.")
    if not kpi_col:
        raise ValueError("Не удалось определить KPI-колонку. Передайте kpi_col явно.")
    if not media_cols:
        media_cols = []

    src_hash = compute_source_hash(data_file)
    detection = detect_media_plan_tail(df, date_col, kpi_col, media_cols)

    if detection.get("found"):
        history_df = detection["history_df"]
        future_df = detection["future_df"]
    else:
        history_df = df.copy()
        future_df = None

    return {
        "history_df": history_df,
        "future_df": future_df,
        "detection": detection,
        "source_hash": src_hash,
    }


# ─── Прогноз-план: загрузка сохранённого артефакта ──────────────────────────


def load_saved_forecast(project_dir: str) -> dict[str, Any] | None:
    """Прочитать сохранённый план-прогноз из results/planning.json.

    Структура planning.json:
        {
          "variant_ids": ["v1", "v2", ...],
          "accepted_variant": "v1" | null,
          "disclaimers": [...]
        }

    Для каждого variant_id читается results/scenarios/<variant_id>.json —
    РЕАЛЬНАЯ схема сценария, которую пишет scenario-движок (P-2 fix 2026-07-16:
    прежняя версия читала top-level ключи total_kpi/total_spend_money/roas_money,
    которых в файле нет — движок кладёт суммы в totals.* — и подменяла их 0.0,
    поэтому слайд/HTML показывали ложные нули):
        {
          "scenario_name": str,
          "predictions": [...],
          "predictions_ci_low": [...],           # per-period серии
          "predictions_ci_high": [...],
          "totals": {
            "predicted_kpi": float,              # сумма KPI за горизонт
            "predicted_kpi_ci_low": float,       # интервал СУММЫ за горизонт
            "predicted_kpi_ci_high": float,
            "total_spend_money": float | null,   # null для физметрик (TRP/показы)
            "roas_money": float | null,
            ...
          },
          "disclaimers": [...],
          "future_dates": [...]
        }
    Легаси top-level ключи (name/total_kpi/...) читаются как fallback.

    Возвращает None если planning.json отсутствует или не загружается.
    Возвращает None если ни один сценарий не загрузился.
    INV-50: никаких wireframe-суррогатов — только живые данные; отсутствующее
    значение остаётся None (в отчёте «—»), НЕ подменяется нулём.
    """
    base = Path(project_dir)
    planning_path = base / 'results' / 'planning.json'

    if not planning_path.exists():
        return None

    try:
        with open(planning_path, encoding='utf-8') as f:
            planning = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning('planning.json повреждён (%s) — прогноз считается отсутствующим', e)
        return None

    variant_ids: list[str] = planning.get('variant_ids') or []
    accepted_variant: str | None = planning.get('accepted_variant')
    plan_disclaimers: list[str] = list(planning.get('disclaimers') or [])

    if not variant_ids:
        logger.warning('planning.json: variant_ids пуст — прогноз не загружен')
        return None

    scenarios_dir = base / 'results' / 'scenarios'
    scenarios: list[dict] = []
    all_disclaimers: list[str] = list(plan_disclaimers)

    def _first_float(*vals) -> float | None:
        """Первое не-None значение как float; иначе None (не 0 — INV-50)."""
        for v in vals:
            if v is not None:
                return float(v)
        return None

    for vid in variant_ids:
        sc_path = scenarios_dir / f'{vid}.json'
        if not sc_path.exists():
            logger.warning('Сценарий %s не найден: %s', vid, sc_path)
            continue
        try:
            with open(sc_path, encoding='utf-8') as f:
                sc = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning('Сценарий %s повреждён (%s) — пропускаем', vid, e)
            continue

        sc_disclaimers: list[str] = list(sc.get('disclaimers') or [])
        for d in sc_disclaimers:
            if d not in all_disclaimers:
                all_disclaimers.append(d)

        totals = sc.get('totals') or {}

        scenarios.append({
            'name': str(sc.get('scenario_name') or sc.get('name') or vid),
            'variant_id': vid,
            'predictions': list(sc.get('predictions') or []),
            'ci_low': list(sc.get('predictions_ci_low') or []),
            'ci_high': list(sc.get('predictions_ci_high') or []),
            'total_kpi': _first_float(totals.get('predicted_kpi'), sc.get('total_kpi')),
            'total_spend_money': _first_float(totals.get('total_spend_money'), sc.get('total_spend_money')),
            'roas_money': _first_float(totals.get('roas_money'), sc.get('roas_money')),
            # Интервал СУММЫ за горизонт (тот же, что в GUI-карточке варианта —
            # SSOT чисел клиенту; per-period серии выше — для графиков).
            'total_kpi_ci_low': _first_float(totals.get('predicted_kpi_ci_low')),
            'total_kpi_ci_high': _first_float(totals.get('predicted_kpi_ci_high')),
            'period_labels': list(sc.get('period_labels') or sc.get('future_dates') or []),
            'disclaimers': sc_disclaimers,
        })

    if not scenarios:
        logger.warning('planning.json: ни один сценарий не загрузился')
        return None

    return {
        'status': 'ok',
        'scenarios': scenarios,
        'historical_actual': [],
        'historical_dates': [],
        'cutoff_index': 0,
        'accepted_variant': accepted_variant,
        'disclaimers': all_disclaimers,
    }


# ─── Шаблон медиаплана ───────────────────────────────────────────────────────


def generate_media_plan_template(project_dir: str, n_future_periods: int = 12) -> dict[str, Any]:
    """Генерирует Excel-шаблон медиаплана на основе обученной модели.

    Логика:
    1. Читает models/latest.pkl → получает media_columns, kpi_column, date_column, data_file.
    2. Читает data_file через load_frames → историческая часть.
    3. Строит Excel: все исторические строки как есть + n_future_periods строк будущего:
       - даты продолжены от последней исторической с правильной гранулярностью,
       - медиа-колонки и KPI — пустые (NaN).
    4. Атомарная запись в <project_dir>/exports/media_plan_template.xlsx.
    5. Возвращает {'status': 'ok', 'path': '<абс. путь к файлу>'}.

    Ошибки: {'status': 'error', 'message': '...'}.
    """
    import tempfile

    import openpyxl

    base = Path(project_dir)
    model_path = base / "models" / "latest.pkl"
    if not model_path.exists():
        return {"status": "error", "message": "Модель не найдена: models/latest.pkl. Сначала обучите модель."}

    # F-AVT-3 (2026-07-10): модели Econometrica сохраняются кастомным pickle
    # (persistent_id для posterior) — голый pickle.load падает на реальных моделях.
    # Грузим через централизованный compat-хелпер (как scenario/decomposer).
    try:
        from engines.persistence import load_model_with_compat
        model_obj = load_model_with_compat(model_path)
    except Exception as e:
        return {"status": "error", "message": f"Не удалось загрузить модель: {e}"}

    # Мета-данные лежат в model_obj['config'] (реальный формат), с fallback
    # на корень dict (упрощённые тестовые pickle) и на __dict__ (объекты).
    if isinstance(model_obj, dict):
        config = model_obj.get("config") if isinstance(model_obj.get("config"), dict) else model_obj
    elif hasattr(model_obj, "__dict__"):
        config = model_obj.__dict__
    else:
        config = {}

    media_columns: list[str] = list(config.get("media_columns") or config.get("channel_columns") or [])
    kpi_column: str = str(config.get("kpi_column") or config.get("target_column") or "sales")
    date_column: str = str(config.get("date_column") or "date")
    data_file: str | None = config.get("data_file") or config.get("file_path")
    control_columns: list[str] = list(config.get("control_columns") or [])

    if not data_file or not Path(data_file).exists():
        # Пробуем найти data_file в project_dir
        for ext in ("*.xlsx", "*.xls", "*.csv"):
            candidates = list((base / "data").glob(ext)) + list(base.glob(ext))
            if candidates:
                data_file = str(candidates[0])
                break

    if not data_file or not Path(data_file).exists():
        return {"status": "error", "message": "Исходный файл данных не найден. Загрузите данные снова."}

    # F-AVT-3: config не всегда хранит date_column (обучение его не сохраняет) —
    # детектим колонку даты из файла, если дефолт 'date' в нём отсутствует.
    try:
        _probe = (
            pd.read_excel(data_file, nrows=0)
            if str(data_file).endswith((".xlsx", ".xls"))
            else pd.read_csv(data_file, nrows=0)
        )
        if date_column not in _probe.columns:
            from engines.validator import detect_column_role_with_confidence as _role
            _date_cands = [c for c in _probe.columns if _role(str(c))[0] == "date"]
            date_column = _date_cands[0] if _date_cands else None
    except Exception:
        date_column = None if date_column not in ("date",) else date_column

    try:
        frames = load_frames(data_file, date_col=date_column, kpi_col=kpi_column, media_cols=media_columns or None)
    except Exception as e:
        return {"status": "error", "message": f"Не удалось прочитать файл данных: {e}"}
    # Резолвим фактическую колонку даты (load_frames мог авто-детектить при None)
    if not date_column or date_column not in frames["history_df"].columns:
        _hist_cols = list(frames["history_df"].columns)
        from engines.validator import detect_column_role_with_confidence as _role2
        _dc = [c for c in _hist_cols if _role2(str(c))[0] == "date"]
        date_column = _dc[0] if _dc else _hist_cols[0]

    history_df: "pd.DataFrame" = frames["history_df"]
    if history_df.empty:
        return {"status": "error", "message": "Исторические данные пусты — нечего продолжать."}

    # Определяем гранулярность по истории
    from utils.forecast_validation import detect_granularity  # SSOT

    gran_result = detect_granularity(history_df[date_column])
    granularity: str = gran_result.get("granularity", "M")

    # Строим будущие даты
    last_date = pd.to_datetime(history_df[date_column].dropna().iloc[-1])
    future_dates: list["pd.Timestamp"] = []
    cur = last_date
    for _ in range(n_future_periods):
        cur = _expected_next(cur, granularity)
        future_dates.append(cur)

    # Все колонки: дата + KPI + медиа + контроли
    all_cols = [date_column, kpi_column] + media_columns + [c for c in control_columns if c not in media_columns]
    # Убираем дубли, сохраняем порядок
    seen: set[str] = set()
    ordered_cols: list[str] = []
    for c in all_cols:
        if c not in seen and c in history_df.columns:
            ordered_cols.append(c)
            seen.add(c)
    # Добавляем колонки из истории, которые не попали
    for c in history_df.columns:
        if c not in seen:
            ordered_cols.append(c)
            seen.add(c)

    # Строим Excel через openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Медиаплан"

    # Заголовок
    ws.append(ordered_cols)

    # Исторические строки как есть
    for _, row in history_df[ordered_cols].iterrows():
        ws.append([
            (v.date() if isinstance(v, pd.Timestamp) else (None if pd.isna(v) else v))
            for v in row
        ])

    # Будущие строки: дата заполнена, всё остальное — пусто
    for fd in future_dates:
        future_row: list[Any] = []
        for col in ordered_cols:
            if col == date_column:
                future_row.append(fd.date())
            else:
                future_row.append(None)
        ws.append(future_row)

    # Атомарная запись
    exports_dir = base / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    out_path = exports_dir / "media_plan_template.xlsx"

    tmp_fd, tmp_name = tempfile.mkstemp(dir=exports_dir, prefix=".mpt_", suffix=".tmp")
    try:
        import os as _os
        _os.close(tmp_fd)
        wb.save(tmp_name)
        _os.replace(tmp_name, out_path)
    except Exception:
        try:
            import os as _os2
            _os2.unlink(tmp_name)
        except Exception:
            pass
        raise

    logger.info("media_plan_template: записан %s (%d history + %d future)", out_path, len(history_df), n_future_periods)
    return {"status": "ok", "path": str(out_path)}


# ─── Подтверждение медиаплана ─────────────────────────────────────────────────


def confirm_media_plan(project_dir: str, confirmed: bool) -> dict[str, Any]:
    """Устанавливает поле 'confirmed' в results/media_plan.json.

    Аргументы:
        project_dir: абсолютный путь к папке проекта.
        confirmed: True — медиаплан подтверждён, False — отклонён/проигнорирован.

    Возвращает {'status': 'ok'} или {'status': 'error', 'message': '...'}.
    Атомарная запись через tempfile.mkstemp + os.replace.
    """
    import os as _os
    import tempfile

    mp_path = Path(project_dir) / "results" / "media_plan.json"
    if not mp_path.exists():
        return {"status": "error", "message": "media_plan.json not found"}

    try:
        with open(mp_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {"status": "error", "message": f"Не удалось прочитать media_plan.json: {e}"}

    data["confirmed"] = confirmed

    mp_dir = mp_path.parent
    tmp_fd, tmp_name = tempfile.mkstemp(dir=mp_dir, prefix=".mp_confirm_", suffix=".tmp")
    try:
        with open(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _os.replace(tmp_name, mp_path)
    except Exception:
        try:
            _os.unlink(tmp_name)
        except Exception:
            pass
        raise

    logger.info("confirm_media_plan: confirmed=%s записан в %s", confirmed, mp_path)
    return {"status": "ok"}


# ─── Манифест прогноза-плана ──────────────────────────────────────────────────


def save_planning_manifest(
    project_dir: str,
    variant_ids: list[str],
    accepted_variant: str | None = None,
    disclaimers: list[str] | None = None,
) -> dict[str, Any]:
    """Записывает results/planning.json — манифест прогноза-плана.

    Манифест связывает сохранённые сценарии (results/scenarios/<id>.json) с
    отчётностью: PPTX/HTML/XLSX-раздел прогноза появляется только при наличии
    planning.json с непустым variant_ids (см. load_saved_forecast). Без него
    сценарии на диске есть, а раздел «не найден» — корень жалобы приёмки
    2026-07-10 (P-1: авто-прогноз базового плана пишет манифест сам).

    Аргументы:
        project_dir: абсолютный путь к папке проекта.
        variant_ids: имена сценариев (совпадают с results/scenarios/<id>.json).
        accepted_variant: выбранный вариант для витрины; по умолчанию — первый.
        disclaimers: оговорки прогноза (INV-50), показываются в отчёте.

    Возвращает {'status': 'ok', 'accepted_variant': ...} или
    {'status': 'error', 'message': '...'}. Атомарная запись (mkstemp + os.replace).
    """
    import os as _os
    import tempfile

    ids = [str(v) for v in (variant_ids or []) if v is not None and str(v) != '']
    if not ids:
        return {"status": "error", "message": "variant_ids пуст — нечего сохранять"}

    accepted = accepted_variant if accepted_variant in ids else ids[0]

    manifest = {
        "variant_ids": ids,
        "accepted_variant": accepted,
        "disclaimers": list(disclaimers or []),
    }

    results_dir = Path(project_dir) / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    planning_path = results_dir / "planning.json"

    tmp_fd, tmp_name = tempfile.mkstemp(dir=results_dir, prefix=".planning_", suffix=".tmp")
    try:
        with open(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        _os.replace(tmp_name, planning_path)
    except Exception:
        try:
            _os.unlink(tmp_name)
        except Exception:
            pass
        raise

    logger.info(
        "save_planning_manifest: %d вариант(ов), accepted=%s → %s",
        len(ids), accepted, planning_path,
    )
    return {"status": "ok", "accepted_variant": accepted}
