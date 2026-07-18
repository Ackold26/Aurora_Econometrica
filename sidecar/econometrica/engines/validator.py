"""
Data validation engine for MMM.
Reads xlsx/csv, validates structure, computes statistics, detects issues.
Returns JSON for UI display (Traffic Light format).
"""
import logging
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Column name patterns for auto-detection
# Ф-1 (аудит примеров 2026-07-05): leads/лиды/заявки — легитимный count-KPI
# (недвижимость, B2B); без него synth_real_estate падал «Не найден KPI-столбец».
# Канарейка клиентских имён (аудит 2026-07-05): 'gmv' знал classify_column
# (TARGET_MONETARY), но detect_column_role — нет → клиент с колонкой «GMV»
# получал «не найден KPI-столбец» (рассинхрон детекторов, класс Д-1).
KPI_PATTERNS = ['sales', 'revenue', 'market_share', 'conversions', 'units', 'volume',
                'leads', 'лид', 'заявк', 'gmv',
                # R1 (2026-07-05, корпус-зонд): count-KPI, что знал classify
                # (target_count), но detect_column_role — нет → рассинхрон Д-1
                # («sign up»/«app install» → unknown у validator). Все 3
                # разделителя (паритет с classify). Голое 'install' НЕ
                # добавлять (ловит «installment»/рассрочку).
                'signup', 'sign up', 'sign-up', 'app install', 'app-install',
                'продажи', 'выручка', 'конверси', 'заказ']
MEDIA_PATTERNS = ['spend', 'budget', 'trp', 'grp', 'impressions', 'clicks', 'views',
                  'бюджет', 'расход', 'показ', 'клик', 'визит', 'прочтен', 'просмотр',
                  'impression', 'click', 'visit', 'cpm', 'cpc', 'cpv',
                  'olv', 'banner', 'social', 'retail media', 'performance',
                  'радио', 'пресса', 'digital', 'programmatic',
                  # Out-of-Home: English (OOH, outdoor) + Russian (ООН, наружная)
                  'ooh', 'outdoor', 'оон', 'наружн',
                  # OTS (Opportunity To See) - impression-like metric for OOH/TV
                  'ots',
                  # Аудит примеров Д-1 (2026-07-05): контакты как Media KPI пар
                  # (OOH/indoor/аптечные экраны) + аптечная сеть как носитель.
                  'contact', 'контакт', 'apteka', 'аптек',
                  # TV (television) - English + Russian
                  'tv', 'television', 'тв ', 'тв_', 'тв-',
                  'promo', 'промо']
# NOTE v2.0.0: 'price' removed from MEDIA_PATTERNS — moved to CONTROL_PATTERNS
# (signed control factor per ADR-019, may be positive OR negative coefficient).
# 'цен' also moved.
# 'период' (рус) знал classify_column, но detect_column_role — только англ
# 'period' → клиент с колонкой «Период» получал «не найден столбец с датами»
# (рассинхрон детекторов, аудит канарейки 2026-07-05).
DATE_PATTERNS = ['date', 'week', 'month', 'period', 'time', 'дата', 'неделя', 'месяц', 'период']
CONTROL_PATTERNS = ['search', 'queries', 'competitor', 'distribution',
                    'seasonality', 'temperature', 'weather', 'holiday',
                    'som', 'sov', 'sos', 'share_of', 'share of',
                    'конкурент', 'конк.', 'конк ',
                    'сезон', 'дистрибуц', 'погод', 'праздни',
                    'запрос', 'кол-во запрос',
                    # NEW v2.0.0 — signed control factors (ADR-019 §4)
                    'price', 'цен', 'индекс_цен', 'price_index',
                    'avg_price', 'unit_price', 'mean_price',
                    'cpi', 'consumer_price', 'inflation', 'ипц', 'инфляция',
                    'gdp', 'ввп', 'gdp_growth',
                    # R1 (2026-07-05, корпус-зонд): underscore + ПРОБЕЛ + ДЕФИС
                    # формы (тройка-прецедент: 'тв '/'тв_'/'тв-'). validator —
                    # плоский substring; у курс_*/usd_rub/exchange_rate НЕТ
                    # голого фолбэка (в отличие от price/цен/gdp/cpi), потому
                    # клиентская форма с пробелом/дефисом падала в unknown —
                    # рассинхрон Д-1 с classify (у него все 3 разделителя через
                    # _sep_pattern). Специфичные компаунды — голое 'курс' НЕ
                    # добавлять (ловит «дискурс»/«экскурсия»).
                    'fx_rate', 'fx rate', 'fx-rate',
                    'exchange_rate', 'exchange rate', 'exchange-rate',
                    'usd_rub', 'usd rub', 'usd-rub',
                    'eur_rub', 'eur rub', 'eur-rub',
                    'курс_рубля', 'курс рубля', 'курс-рубля',
                    'курс_доллара', 'курс доллара', 'курс-доллара',
                    'курс_евро', 'курс евро', 'курс-евро',
                    'rain', 'snow', 'precipitation', 'осадк',
                    'temp', 'температур',
                    'svok',  # ROSST industry: share_of_voice_konkurentov
                    'event',  # additional holiday/event markers
                    ]


def detect_column_role(col_name: str) -> str:
    """Auto-detect column role from name (backward-compatible)."""
    role, _ = detect_column_role_with_confidence(col_name)
    return role


def detect_column_role_with_confidence(col_name: str) -> tuple[str, float]:
    """Auto-detect column role + confidence score (0.0–1.0).

    Returns:
        (role, confidence) where role is 'kpi'|'media'|'control'|'date'|'unknown'
    """
    # Defensive guard (audit H-19). pandas header parsing на merged cells /
    # blank Excel columns может вернуть NaN (float) или None — без guard'a
    # .lower() raises AttributeError → весь /validate endpoint крашится 500.
    if not isinstance(col_name, str):
        return 'unknown', 0.0
    lower = col_name.lower()

    # Date: high confidence for exact names
    date_exact = ['date', 'week', 'month', 'period', 'quarter']
    if lower in date_exact or any(lower.startswith(p) for p in date_exact):
        return 'date', 0.97
    if any(p in lower for p in DATE_PATTERNS):
        return 'date', 0.80

    # Priority override: "конкурент" always → control (even if contains media keywords)
    COMPETITOR_KEYS = ['конкурент', 'конк.', 'конк ', 'competitor']
    if any(k in lower for k in COMPETITOR_KEYS):
        return 'control', 0.90

    # Аудит примеров Д-2 (2026-07-05): *_indicator / индикатор — бинарный
    # флаг-контрол по семантике (promo_indicator и т.п.); без override слово
    # «promo» из MEDIA_PATTERNS утаскивало его в медиа-канал с ROI.
    if 'indicator' in lower or 'индикатор' in lower:
        return 'control', 0.85

    # BUG #3 fix (v2.0.1): derived metrics (SOM / SOV / market_share) — это
    # ratio computed from KPI (brand_sales / total_market). Использование как
    # predictor → endogeneity (predictor зависит от outcome). По умолчанию
    # исключаем из модели. Юзер может explicitly включить через Roles UI.
    # Включён trailing space / suffix чтобы не ловить 'svok'/'mosgorsovet'.
    DERIVED_KEYS = [
        'som в', 'som (', 'som_',
        'sov ', 'sov (', 'sov_',
        'share_of_market', 'share of market', 'market_share', 'market share',
        'share_of_voice', 'share of voice',
        'доля_рынка', 'доля рынка', 'доля_голоса', 'доля голоса',
    ]
    if (any(k in lower for k in DERIVED_KEYS)
            or lower in ('som', 'sov')
            or lower.endswith(' som') or lower.endswith(' sov')):
        return 'unused', 0.85

    # Фаза Б (2026-07-04): продажи ВСЕЙ категории/рынка (ОБЪЁМ, не доля) —
    # ЭКЗОГЕННЫЙ контроль спроса. Спрос всей категории (грипп-рынок, аллергия-
    # рынок) не зависит от медиа одного бренда, но задаёт сезонную волну, на
    # которую бренд «плывёт» → сильнейший прокси спроса (сильнее Фурье: реальный
    # ряд, не гладкая аппроксимация). Приоритет над KPI: «продажи категории»
    # содержит «продажи», но это контроль, не целевая метрика. Идёт ПОСЛЕ derived
    # (market_share/доля рынка → unused выше, endogenous) — сюда попадает только
    # ОБЪЁМ рынка/категории, не доля.
    # Аудит 2026-07-04: голое «категори» ловило текстовые колонки-атрибуты
    # («Категория», «Категория канала») → control для строкового столбца →
    # падение обучения на astype(float). Комбинированное условие: ТЕМА
    # (категория/рынок) И ОБЪЁМНОЕ слово (продажи/объём/руб/...) — только
    # числовой объём рынка проходит; атрибуты-классификаторы не задеваются.
    # 🔴 ПАРИТЕТ (R2 2026-07-06): используем SSOT-списки из column_detection,
    # не локальные копии. Гарантирует автоматическое подхватывание новых токенов
    # (напр. 'рыночн') без ручной синхронизации двух мест.
    from utils.column_detection import _CATEGORY_THEME, _CATEGORY_VOLUME  # noqa: PLC0415
    if (any(k in lower for k in _CATEGORY_THEME)
            and any(v in lower for v in _CATEGORY_VOLUME)):
        return 'control', 0.85

    # Аудит №4 (2026-07-05): клиентские событийные дамми БЕЗ префикса holiday_
    # (black_friday / 8_марта / чёрная_пятница) — SSOT-алиасы календаря →
    # control. Без этого колонка падала в unknown→unused, а дедуп авто-инжекта
    # гасил авто-дубль → контроль события терялся ПОЛНОСТЬЮ (OVB молча).
    from utils.holiday_calendar_ru import is_holiday_like_name
    if is_holiday_like_name(col_name):
        return 'control', 0.85

    # Count pattern matches per category
    kpi_matches = sum(1 for p in KPI_PATTERNS if p in lower)
    media_matches = sum(1 for p in MEDIA_PATTERNS if p in lower)
    control_matches = sum(1 for p in CONTROL_PATTERNS if p in lower)

    max_matches = max(kpi_matches, media_matches, control_matches)
    if max_matches == 0:
        return 'unknown', 0.0

    if kpi_matches == max_matches and kpi_matches >= media_matches:
        conf = min(0.55 + kpi_matches * 0.15, 0.95)
        return 'kpi', round(conf, 2)
    if media_matches == max_matches and media_matches >= control_matches:
        conf = min(0.55 + media_matches * 0.15, 0.95)
        return 'media', round(conf, 2)
    conf = min(0.50 + control_matches * 0.15, 0.90)
    return 'control', round(conf, 2)


def _is_numeric_parseable(series: 'pd.Series', threshold: float = 0.8) -> bool:
    """У3 (2026-07-04): ≥threshold непустых значений колонки парсятся в число?

    media/control-предикторы входят в матрицу X численно (modeler astype(float));
    текстовый столбец-атрибут (напр. «Категория А/Б») с именем-ловушкой → падение
    обучения. Этот гейт отсекает нечисловые колонки ДО назначения роли-предиктора.

    Числовой dtype → True сразу. Иначе строки чистятся от денежных/разделительных
    символов и пробуются ДВЕ стратегии запятой (для гейта важен ФАКТ парсибельности,
    не точное значение): A — запятая = разделитель тысяч (убрать); B — запятая =
    десятичная (→ точка). Берётся лучшая. Money-строки «3 836 962 ₽» / «3,836,962 ₽»
    проходят; чистый текст — нет.
    """
    s = series.dropna()
    if len(s) == 0:
        return False
    if pd.api.types.is_numeric_dtype(s):
        return True
    txt = s.astype(str).str.strip().str.replace(r'[\s\xa0₽$€%]', '', regex=True)
    a = pd.to_numeric(txt.str.replace(',', '', regex=False), errors='coerce')
    b = pd.to_numeric(txt.str.replace(',', '.', regex=False), errors='coerce')
    frac = max(int(a.notna().sum()), int(b.notna().sum())) / len(s)
    return frac >= threshold


def validate_role_compatibility(
    unit_costs: dict,
    media_columns: list,
    classifier_fn=None,
) -> tuple[bool, str, str]:
    """Cross-field validation для KPI settings save (Phase 1.2).

    Checks:
      1. Each channel in unit_costs существует в media_columns.
      2. Channel name doesn't match target/control patterns (would indicate
         user accidentally set unit_cost for non-media role).

    Args:
        unit_costs: {channel: ₽_per_unit} from frontend save request
        media_columns: list of column names classified as media in project state
        classifier_fn: optional callable(name) -> kind для unit-test substitution

    Returns:
        (is_valid: bool, error_code: str, message: str)
        error_code в {'OK', 'UNIT_COST_CHANNEL_NOT_MEDIA', 'UNIT_COST_LIKELY_TARGET'}
    """
    if not unit_costs:
        return True, 'OK', ''
    if not isinstance(media_columns, (list, tuple)):
        media_columns = list(media_columns or [])
    media_set = {str(c) for c in media_columns}

    for channel in unit_costs.keys():
        if channel in media_set:
            continue  # OK
        # Channel not in media list → likely user error (e.g., set unit_cost
        # для column которая помечена как target / control).
        # Optional: use classifier_fn для better диагностики
        kind_hint = ''
        if classifier_fn is not None:
            try:
                kind_hint = f' (classified as {classifier_fn(channel)!r})'
            except Exception:  # noqa: BLE001 — defensive против user input
                kind_hint = ''
        return (
            False,
            'UNIT_COST_CHANNEL_NOT_MEDIA',
            f'unit_cost задан для канала {channel!r}, который не в списке media{kind_hint}. '
            f'Удалите запись или измените role канала в шаге «Роли колонок».',
        )
    return True, 'OK', ''


def detect_adstock_type(col_name: str) -> str:
    """Suggest adstock type based on channel name."""
    lower = col_name.lower()
    if any(k in lower for k in ['tv', 'television', 'radio', 'ooh', 'outdoor', 'offline', 'press']):
        return 'weibull'
    return 'geometric'


def detect_date_frequency(series: 'pd.Series') -> str:
    """Detect time series frequency from a date column.

    Returns: 'daily' | 'weekly' | 'monthly' | 'quarterly' | 'unknown'
    """
    try:
        dates = pd.to_datetime(series.dropna()).sort_values()
        if len(dates) < 3:
            return 'unknown'
        diffs = dates.diff().dropna().dt.days
        median_diff = float(diffs.median())
        if median_diff <= 1.5:
            return 'daily'
        elif 5 <= median_diff <= 9:
            return 'weekly'
        elif 28 <= median_diff <= 32:
            return 'monthly'
        elif 85 <= median_diff <= 95:
            return 'quarterly'
        return 'unknown'
    except Exception:
        return 'unknown'


def compute_histogram(series: 'pd.Series', bins: int = 10) -> dict:
    """Compute histogram for a numeric series."""
    clean = series.dropna()
    if len(clean) == 0:
        return {'counts': [], 'edges': []}
    counts, edges = np.histogram(clean, bins=bins)
    return {
        'counts': counts.tolist(),
        'edges': [round(float(e), 4) for e in edges],
    }


def _read_csv_smart(path: 'Path') -> 'pd.DataFrame':
    """C1 (2026-07-03): CSV русского Excel по умолчанию с разделителем «;» —
    pd.read_csv(запятая) читал его в ОДНУ колонку → пользователь получал
    невнятное «Не найден KPI-столбец». Дешёвый детект: если после запятой
    вышла одна колонка с «;» в имени — перечитать с «;». Обычные CSV идут
    прежним быстрым путём (без sniffer-замедления engine='python').
    """
    df = pd.read_csv(path)
    if df.shape[1] == 1 and ';' in str(df.columns[0]):
        df = pd.read_csv(path, sep=';')
    return df


def data_preview(file_path: str, n_rows: int = 20) -> dict[str, Any]:
    """Read first n_rows of a file and return preview data.

    Args:
        file_path: Path to xlsx or csv file
        n_rows: Number of rows to preview (default 20)

    Returns:
        {status, headers, rows, dtypes, shape}
    """
    path = Path(file_path)
    if not path.exists():
        return {'status': 'error', 'message': f'Файл не найден: {file_path}'}

    try:
        if path.suffix in ('.xlsx', '.xls'):
            df = pd.read_excel(path)
        elif path.suffix == '.csv':
            df = _read_csv_smart(path)
        else:
            return {'status': 'error', 'message': f'Неподдерживаемый формат: {path.suffix}'}
    except Exception as e:
        return {'status': 'error', 'message': f'Ошибка чтения файла: {e}'}

    preview_df = df.head(n_rows)

    # Convert to JSON-safe format
    def safe_val(v: Any) -> Any:
        if pd.isna(v) if not isinstance(v, (list, dict)) else False:
            return None
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            return round(float(v), 4)
        return str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v

    headers = list(df.columns)
    rows = [[safe_val(cell) for cell in row] for row in preview_df.itertuples(index=False)]
    dtypes = {col: str(df[col].dtype) for col in df.columns}

    return {
        'status': 'ok',
        'headers': headers,
        'rows': rows,
        'dtypes': dtypes,
        'shape': [int(df.shape[0]), int(df.shape[1])],
        'file_name': path.name,
        'size_kb': round(path.stat().st_size / 1024, 1),
    }


def validate_data(file_path: str, project_dir: str | None = None) -> dict[str, Any]:
    """Validate dataset for MMM readiness.

    Args:
        file_path: Path to xlsx or csv file
        project_dir: Optional project directory to save results

    Returns:
        JSON-serializable validation result for UI
    """
    path = Path(file_path)
    if not path.exists():
        return {'status': 'error', 'message': f'Файл не найден: {file_path}'}

    # Read data
    try:
        if path.suffix in ('.xlsx', '.xls'):
            df = pd.read_excel(path)
        elif path.suffix == '.csv':
            df = _read_csv_smart(path)
        else:
            return {'status': 'error', 'message': f'Неподдерживаемый формат: {path.suffix}. Нужен xlsx или csv.'}
    except Exception as e:
        return {'status': 'error', 'message': f'Ошибка чтения файла: {e}'}

    n_rows, n_cols = df.shape

    # C1 (2026-07-03): полностью пустой файл — ранний понятный отказ.
    # Прежде каскад давал невпопад «Переименуйте столбец в "date"»,
    # хотя переименовывать нечего.
    if n_cols == 0 or (n_rows == 0 and n_cols == 0):
        return {
            'status': 'error',
            'message': ('Файл пуст — в нём нет данных. Загрузите файл с колонками: '
                        'дата, продажи (KPI) и медиа-каналы.'),
        }

    # ── Медиаплан-хвост: детекция до любой статистики ──────────────────────
    # Если после исторических строк (KPI заполнен) идут строки будущего (KPI пуст),
    # статистику и ratio считаем только по истории. Хвост не скрываем — возвращаем
    # media_plan_detected и при наличии project_dir пишем media_plan.json.
    _media_plan_detected: dict | None = None
    try:
        from engines.planning import detect_media_plan_tail, compute_source_hash
        # Авто-детект колонок ролей для planning детектора (минимальный набор).
        _date_col_hint = next(
            (c for c in df.columns if detect_column_role_with_confidence(str(c))[0] == 'date'),
            None,
        )
        _kpi_col_hint = next(
            (c for c in df.columns if detect_column_role_with_confidence(str(c))[0] == 'kpi'),
            None,
        )
        _media_hints = [
            c for c in df.columns if detect_column_role_with_confidence(str(c))[0] == 'media'
        ]
        # F-AVT-1 (2026-07-10, живой прогон): role-детекция по имени не ловит
        # кириллические/нестандартные каналы («ТВ»/«Онлайн-видео» → unknown) —
        # типичный русский клиент. Тогда channels пустой → медиаплан не читается.
        # Fallback: media-кандидаты = числовые колонки кроме даты и KPI (в хвосте
        # это инвестиции медиаплана). detect_media_plan_tail сам проверит заполненность.
        if not _media_hints and _date_col_hint and _kpi_col_hint:
            _media_hints = [
                c for c in df.columns
                if c not in (_date_col_hint, _kpi_col_hint)
                and pd.api.types.is_numeric_dtype(df[c])
            ]
        if _date_col_hint and _kpi_col_hint:
            _tail_result = detect_media_plan_tail(df, _date_col_hint, _kpi_col_hint, _media_hints)
            if _tail_result.get('found'):
                _src_hash = compute_source_hash(file_path)
                _media_plan_detected = {
                    'n_future_periods': _tail_result['n_future_periods'],
                    'period_labels': _tail_result['period_labels'],
                    'granularity': _tail_result['granularity'],
                    'future_dates': _tail_result['future_dates'],
                    'channels': _tail_result['channels'],
                    'warnings': _tail_result['warnings'],
                    'source_hash': _src_hash,
                    'confirmed': False,
                }
                # Статистику считаем только по истории
                df = _tail_result['history_df'].reset_index(drop=True)
                n_rows = len(df)
                # Атомарная запись media_plan.json если project_dir задан
                if project_dir and Path(project_dir).is_absolute():
                    try:
                        import json as _json
                        import tempfile as _tempfile
                        _mp_dir = Path(project_dir) / 'results'
                        _mp_dir.mkdir(parents=True, exist_ok=True)
                        _mp_path = _mp_dir / 'media_plan.json'
                        _tmp_fd, _tmp_name = _tempfile.mkstemp(
                            dir=_mp_dir, prefix='.mp_', suffix='.tmp'
                        )
                        try:
                            with open(_tmp_fd, 'w', encoding='utf-8') as _f:
                                _json.dump(_media_plan_detected, _f, ensure_ascii=False, indent=2)
                            import os as _os
                            _os.replace(_tmp_name, _mp_path)
                        except Exception:
                            try:
                                _os.unlink(_tmp_name)
                            except Exception:
                                pass
                            raise
                    except Exception:
                        logger.warning('media_plan.json write failed', exc_info=True)
    except Exception:
        logger.warning('media_plan tail detection failed — proceeding with full df', exc_info=True)

    issues = []
    warnings = []

    # ── Column detection ──
    # П1 (аудит №3 В-3): импорт единого критерия total-budget один раз, не в цикле.
    from engines.narrative_adapter import _normalize_channel_name
    columns = []
    date_col = None
    kpi_cols = []
    media_cols = []
    control_cols = []

    for col in df.columns:
        role, confidence = detect_column_role_with_confidence(col)
        # У3 (2026-07-04): числовой гейт ролей. media/control входят в X численно —
        # текстовый столбец-атрибут с именем-ловушкой («Категория А/Б», «Регион»)
        # уронил бы обучение на astype(float). Понижаем до 'unused' с подсказкой;
        # money-строки («3 836 962 ₽») парсятся → роль сохраняется.
        if role in ('media', 'control') and not _is_numeric_parseable(df[col]):
            warnings.append({
                'column': col,
                'type': 'non_numeric_role',
                'message': (
                    f'{col} — столбец текстовый (не парсится в число), не может быть '
                    f'предиктором. Роль снята; при необходимости задайте её вручную.'
                ),
                'severity': 'warning',
                # Аудит №4 Г-1: роль УЖЕ снята валидатором — кнопка «Исключить»
                # (action='exclude') предлагала бы сделать сделанное; 'acknowledge'
                # рендерится нейтральной «Принять».
                'action': 'acknowledge',
            })
            role = 'unused'
            confidence = 0.0
        # Т3-плюс П1 (2026-07-04): суммарный бюджет как media задваивает вклад.
        # Критерий ЕДИНЫЙ с фильтром таблицы каналов (_merge_channels): если после
        # снятия медиа-токенов имени инструмента НЕ остаётся (_normalize_channel_name
        # → None), это агрегатная колонка «Бюджет ДО НДС», а не отдельный канал.
        # Как media она обучается отдельной серией (в MMX — 6.45% вклада) и рвёт
        # согласованность timeline↔таблица. Понижаем до 'unused' (юзер вернёт вручную,
        # как и в non_numeric_role) → новые модели её не обучают, состав серий сходится.
        if role == 'media':
            if _normalize_channel_name(col) is None:
                warnings.append({
                    'column': col,
                    'type': 'total_budget_as_media',
                    'message': (
                        f'{col} — похоже на суммарный бюджет, а не отдельный канал '
                        f'(после снятия слов «Бюджет / до НДС» имени инструмента не '
                        f'осталось). Как медиа-канал он задвоит вклад и исказит ROI. '
                        f'Роль снята; при необходимости задайте её вручную.'
                    ),
                    'severity': 'warning',
                    'action': 'acknowledge',  # Г-1: роль уже снята — не «Исключить»
                })
                role = 'unused'
                confidence = 0.0
        col_info: dict[str, Any] = {
            'name': col,
            'role': role,
            'confidence': confidence,
            'dtype': str(df[col].dtype),
        }

        if role == 'date':
            date_col = col
            # Phase 2 audit pass 5: per-column year span detection - позволяет
            # frontend (UnitCostsPanel) показать %/год input БЕЗ зависимости от
            # обученного pickle (econ_forecast_context требует model.latest.pkl).
            try:
                _dates = pd.to_datetime(df[col], errors='coerce').dropna()
                if not _dates.empty:
                    _years = _dates.dt.year
                    _unique_years = sorted(set(int(y) for y in _years.unique()))
                    col_info['date_stats'] = {
                        'min_date': _dates.min().strftime('%Y-%m-%d'),
                        'max_date': _dates.max().strftime('%Y-%m-%d'),
                        'unique_years': _unique_years,
                        'n_years': len(_unique_years),
                    }
            except Exception:
                pass  # Non-fatal - date detection still works без stats
        elif role == 'kpi':
            kpi_cols.append(col)
        elif role == 'media':
            media_cols.append(col)
            col_info['adstock_type'] = detect_adstock_type(col)
        elif role == 'control':
            control_cols.append(col)

        # Stats + histogram for numeric columns
        if pd.api.types.is_numeric_dtype(df[col]):
            col_series = df[col].fillna(0)
            zeros_pct = round((col_series == 0).sum() / len(col_series) * 100, 1)
            col_info['stats'] = {
                'min': round(float(col_series.min()), 4),
                'max': round(float(col_series.max()), 4),
                'mean': round(float(col_series.mean()), 4),
                'std': round(float(col_series.std()), 4),
                'sum': round(float(col_series.sum()), 2),
                'zeros_pct': zeros_pct,
                'nulls': int(df[col].isna().sum()),
                'cv': round(float(col_series.std() / col_series.mean() * 100), 1) if col_series.mean() != 0 else 0,
            }
            col_info['histogram'] = compute_histogram(df[col])

            if zeros_pct > 60:
                warnings.append({
                    'column': col,
                    'type': 'high_zeros',
                    'message': f'{col} - {zeros_pct}% нулей. Рекомендуем объединить с другим каналом',
                    'severity': 'warning',
                    'action': 'merge',
                })
            if col_info['stats']['cv'] < 5 and role == 'media':
                warnings.append({
                    'column': col,
                    'type': 'low_variance',
                    'message': f'{col} - вариативность <5%. Канал не информативен для модели',
                    'severity': 'warning',
                    'action': 'exclude',
                })

        columns.append(col_info)

    # ── Structure checks ──
    if not date_col:
        issues.append({
            'type': 'no_date',
            'message': 'Не найден столбец с датами. Переименуйте столбец в "date"',
            'severity': 'critical',
        })

    if not kpi_cols:
        issues.append({
            'type': 'no_kpi',
            'message': 'Не найден KPI-столбец (sales, revenue, som). Укажите вручную',
            'severity': 'critical',
        })

    if not media_cols:
        issues.append({
            'type': 'no_media',
            'message': 'Не найдены медиа-столбцы (spend, trp, impressions). Укажите вручную',
            'severity': 'critical',
        })

    # Фаза Б (2026-07-04): подсказка загрузить продажи категории/рынка. Экзогенный
    # контроль спроса (Chan&Perry §4.2.2) — сильнейший прокси (реальный ряд спроса,
    # сильнее гладкого Фурье). Прицельно: показываем, когда клиент УЖЕ отслеживает
    # рынок (есть competitor-колонка), но объёма категории нет — тогда совет релевантен
    # (фарма / конкурентный рынок). Info-level, не блокирует.
    try:
        from utils.column_detection import classify_column
        _kinds = [classify_column(str(c)) for c in df.columns]
        if 'category' not in _kinds and 'signed_competitor' in _kinds:
            warnings.append({
                'column': '',
                'type': 'suggest_category',
                'message': (
                    'Совет: добавьте столбец «продажи категории/рынка» (в руб. или уп.) — '
                    'модель точнее отделит спрос от вклада рекламы (честнее ROI). '
                    'Особенно полезно для фармы и конкурентных рынков.'
                ),
                'severity': 'info',
                'action': 'add_column',
            })
    except Exception:
        pass

    # ── Data volume check ──
    # v2.1.0 (пилот 2026-05-17, #37): SSOT ratio thresholds + texts с
    # frontend ratio-classifier.js. 5 коридоров:
    #   < 2:1 - error/critical: «Критически мало»
    #   2-3:1 - warning-high: «Ниже минимума»
    #   3-4:1 - warning: «Ниже рекомендуемого»
    #   4-6:1 - info: «Рекомендуемый уровень» (no warning)
    #   ≥ 6:1 - success: «Идеально» (no warning)
    # Labels одинаковые с frontend - юзер видит согласованный текст
    # в Validation, инсайтах и Контроле качества.
    n_predictors = len(media_cols) + len(control_cols)
    # F-A1-5: оценочное число эффективных параметров ДО обучения.
    # Учитывает авто-инжектируемые контроли которые пользователь не видит
    # в таблице ролей, но которые реально раздувают n_params в модели:
    #   - 12 праздников РФ (дефолт use_holidays=True; disabled_holidays в конфиге
    #     не известен на этапе validate, используем дефолтные 12)
    #   - intercept (1 параметр, всегда)
    #   - Фурье-члены сезонности: условны (нужно ≥2 цикла + autocorr ≥ 0.2),
    #     здесь НЕ включаем — честнее показать минимальную оценку; при обучении
    #     фронт получит фактические данные из diagnostics.seasonality
    # Значение проброшено в ответ как отдельное поле и читается фронтом
    # вместо local (mediaCount + controlCount) для отображения ratio.
    N_HOLIDAYS_DEFAULT = 12
    N_INTERCEPT = 1
    n_params_effective_pretrain = n_predictors + N_HOLIDAYS_DEFAULT + N_INTERCEPT
    ratio = n_rows / max(n_predictors, 1)
    if ratio < 2:
        issues.append({
            'type': 'insufficient_data',
            'message': f'Ratio данных {ratio:.1f}:1 - критически мало. Модель почти наверняка переобучится - β-коэффициенты будут случайными',
            'severity': 'critical',
        })
    elif ratio < 3:
        warnings.append({
            'type': 'low_data',
            'message': f'Ratio {ratio:.1f}:1 - ниже минимума. Модель сойдётся, но правдоподобные диапазоны будут очень широкими - используйте результаты как ориентир',
            'severity': 'warning',
        })
    elif ratio < 4:
        warnings.append({
            'type': 'borderline_data',
            'message': f'Ratio {ratio:.1f}:1 - ниже рекомендуемого. Модель работает, но с широкими правдоподобными диапазонами - результаты как качественные ориентиры',
            'severity': 'warning',
        })

    # ── Date frequency + period check ──
    date_frequency = 'unknown'
    if date_col:
        date_frequency = detect_date_frequency(df[date_col])
        try:
            df[date_col] = pd.to_datetime(df[date_col])
        except Exception:
            warnings.append({
                'type': 'date_parse',
                'message': f'Не удалось распознать формат дат в "{date_col}". Убедитесь в формате YYYY-MM-DD',
                'severity': 'warning',
            })

    # Аудит примеров Д-3 (2026-07-05): раньше n_rows считались НЕДЕЛЯМИ
    # («36 наблюдений — менее 1 года» на 3 ГОДАХ месячных данных — ложный
    # испуг у любого месячного клиента). Теперь длительность — по реальному
    # диапазону дат; счёт наблюдений — второй, гранулярно-нейтральный критерий.
    span_days = None
    if date_col:
        _dc = next((c for c in columns if c.get('name') == date_col), None)
        _ds = (_dc or {}).get('date_stats') or {}
        try:
            _mn = pd.to_datetime(_ds.get('min_date'))
            _mx = pd.to_datetime(_ds.get('max_date'))
            if pd.notna(_mn) and pd.notna(_mx):
                span_days = int((_mx - _mn).days)
        except Exception:
            span_days = None
    if span_days is not None:
        if span_days < 358:  # < ~1 года по календарю
            warnings.append({
                'type': 'short_period',
                'message': (
                    f'Период данных ~{max(span_days, 0)} дн. (< 1 года): сезонность и '
                    f'длинные эффекты каналов не идентифицируются надёжно. '
                    f'Рекомендуем ≥1 год, лучше ≥2 лет.'
                ),
                'severity': 'warning',
            })
        elif n_rows < 24:
            warnings.append({
                'type': 'short_period',
                'message': (
                    f'{n_rows} наблюдений — мало точек для устойчивой оценки '
                    f'(adstock+Hill на канал). Рекомендуем ≥24 периода.'
                ),
                'severity': 'warning',
            })
    elif n_rows < 52:
        # Нет валидной даты — консервативный старый критерий.
        warnings.append({
            'type': 'short_period',
            'message': f'{n_rows} наблюдений - менее 1 года. Рекомендуем ≥52 недели (≥104 для надёжных результатов)',
            'severity': 'warning',
        })

    # ── Full correlation matrix ──
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    high_correlations = []
    full_correlation_matrix: dict[str, Any] = {'labels': [], 'matrix': []}

    if len(numeric_cols) >= 2:
        corr_df = df[numeric_cols].corr()
        # Replace NaN with 0 for JSON serialization
        corr_clean = corr_df.fillna(0)

        full_correlation_matrix = {
            'labels': numeric_cols,
            'matrix': [[round(float(v), 3) for v in row] for row in corr_clean.values],
        }

        for i, c1 in enumerate(numeric_cols):
            for j, c2 in enumerate(numeric_cols):
                if i < j:
                    r = abs(corr_df.loc[c1, c2])
                    if not np.isnan(r) and r > 0.8:
                        high_correlations.append({
                            'col1': c1, 'col2': c2,
                            'correlation': round(float(corr_df.loc[c1, c2]), 3),
                            'risk': 'Мультиколлинеарность - один из столбцов может быть избыточен',
                        })

    # ── Traffic Light verdict ──
    has_critical = any(i['severity'] == 'critical' for i in issues)
    status = 'error' if has_critical else ('warning' if warnings else 'ok')
    verdict = 'ТРЕБУЕТ ДОРАБОТКИ' if has_critical else (
        'ГОТОВ К МОДЕЛИРОВАНИЮ (с оговорками)' if warnings else 'ГОТОВ К МОДЕЛИРОВАНИЮ'
    )

    # v2.1.0 (пилот 2026-05-17 audit): available_kpi_types - набор KPI типов
    # которые соответствуют ролям колонок в данных. Frontend KPISelector
    # disable'ит cards вне этого списка - юзер не может выбрать тип leads
    # если backend нашёл только target_monetary колонку (KPI mismatch).
    #
    # v2.1.0 pilot R2 (2026-05-17 B2-04): target_count whitelist расширен до
    # 7 типов, sync с decomposer.py:357-358 (_count_types set) и frontend
    # KPISelector.svelte:74-82 (countOptions list). Раньше backend
    # whitelist'ил только 4 типа → юзер видел disabled cards для loyalty_cards
    # / subscriptions / app_installs хотя реальный data role совпадал.
    from utils.column_detection import classify_column as _classify_kpi
    _COUNT_KPI_TYPES = [
        'sales_packs', 'leads', 'registrations',
        'loyalty_cards', 'subscriptions', 'app_installs', 'count_custom',
    ]
    _MONETARY_KPI_TYPES = ['sales', 'revenue', 'profit']
    available_kpi_types: set[str] = set()
    for c in columns:
        nm = c.get('name') or ''
        kind = _classify_kpi(nm)
        if kind == 'target_count':
            available_kpi_types.update(_COUNT_KPI_TYPES)
        elif kind == 'target_monetary':
            available_kpi_types.update(_MONETARY_KPI_TYPES)
    # Fallback: backend не нашёл явный target target_* → не блокируем выбор
    # (юзер сам решит roles в Roles Mapper).
    if not available_kpi_types:
        available_kpi_types = set(_COUNT_KPI_TYPES) | set(_MONETARY_KPI_TYPES)

    result: dict[str, Any] = {
        'status': status,
        'verdict': verdict,
        'file': {
            'name': path.name,
            'rows': n_rows,
            'cols': n_cols,
            'size_kb': round(path.stat().st_size / 1024, 1),
        },
        'columns': columns,
        'detected': {
            'date': date_col,
            'kpi': kpi_cols,
            'media': media_cols,
            'control': control_cols,
            'n_predictors': n_predictors,
            'n_params_effective_pretrain': n_params_effective_pretrain,
            'ratio': round(ratio, 1),
            'date_frequency': date_frequency,
        },
        'available_kpi_types': sorted(available_kpi_types),
        'issues': issues,
        'warnings': warnings,
        'high_correlations': high_correlations,
        'full_correlation_matrix': full_correlation_matrix,
        'media_plan_detected': _media_plan_detected,
    }

    # Save to project dir if provided.
    # Под RemoteApp/roaming profile запись может упасть с PermissionError /
    # OSError / invalid path - GUI всё равно получает result через return.
    # default=str страхует numpy-типы, которые json не умеет сериализовать.
    if project_dir:
        # LOAD-1 (B2) harden: относительный project_dir → запись ушла бы в CWD
        # сайдкара, а не в папку проекта (validation.json «терялся» молча, что
        # ломало реоткрытие проекта). Резолв в абсолютный путь делает Rust
        # (resolve_project_dir_arg); сюда относительный путь приходить не должен.
        # Не пишем в относительный путь — превращаем молчаливую запись-не-туда в
        # видимый лог (result всё равно возвращается в GUI).
        if not Path(project_dir).is_absolute():
            logger.warning(
                'validation.json NOT saved: project_dir is not absolute (%s) — '
                'expected resolved abs path from Rust', project_dir,
            )
        else:
            try:
                out_path = Path(project_dir) / 'results' / 'validation.json'
                out_path.parent.mkdir(parents=True, exist_ok=True)
                import json
                # NaN-safe (2026-06-04 аудит): NaN→null, иначе Rust serde_json роняет файл.
                from utils.safe_io import sanitize_nonfinite
                with open(out_path, 'w', encoding='utf-8') as f:
                    json.dump(sanitize_nonfinite(result), f, ensure_ascii=False, indent=2, default=str)
            except Exception:
                logger.warning(
                    'validation.json write failed, result still returned to GUI',
                    exc_info=True,
                )

    return result
