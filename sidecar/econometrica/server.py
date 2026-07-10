"""
Aurora AI Econometrica - Python Sidecar Server.
FastAPI server for local MMM computations (0 Claude tokens).

Port: принимается через sys.argv[1] (fallback 7430 для back-compat).
Version: из env AURORA_PRODUCT_VERSION (fallback '1.0.9').
Product ID: из env AURORA_PRODUCT_ID (fallback 'com.aurora.econometrica').

Per-user RDP изоляция обеспечивается на Rust-стороне - этот сервер
просто слушает переданный ему порт.
"""
# ── JAX multi-core setup - MUST be before any `import jax` ──────────────
# На CPU JAX по умолчанию видит 1 host device → NumPyro NUTS свёртывает все
# цепи в 1 ядро (vectorized). Выставляем N виртуальных devices → NumPyro
# раскладывает цепи через pmap по реальным ядрам.
# Override: env AURORA_MCMC_CORES=N (по умолчанию min(cpu_count, 8)).
import os as _os_early
_mcmc_cores = int(_os_early.environ.get(
    'AURORA_MCMC_CORES',
    min(_os_early.cpu_count() or 1, 8)
))
_os_early.environ.setdefault(
    'XLA_FLAGS',
    f'--xla_force_host_platform_device_count={_mcmc_cores}'
)

import json
import logging
import logging.handlers
import os
import signal
import sys
import threading
import uuid
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

# Ensure sidecar root is in sys.path for absolute imports (engines.*, utils.*, charts.*)
_sidecar_root = str(Path(__file__).parent)
if _sidecar_root not in sys.path:
    sys.path.insert(0, _sidecar_root)

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator


def _friendly_error(e: Exception) -> str:
    """П6 (UX-волна, 2026-07-03): последняя миля ошибок. Generic-обработчики
    прежде отдавали голый str(e) — английский технотекст доезжал до клиента.
    Теперь: что случилось + что делать; техдеталь остаётся для поддержки
    (полный стек в логах через logger.exception)."""
    detail = str(e) or type(e).__name__
    return (
        f'Внутренняя ошибка при расчёте: {detail[:200]}. '
        f'Повторите действие; если ошибка повторится — перезапустите программу '
        f'или напишите в поддержку.'
    )

# ── Identity & session (required by handshake protocol v1.0.9+) ──────────────
# Session_id меняется при каждом cold start. Rust сверяет его с sidecar.json
# и live /health, несовпадение → force kill + respawn (защита от stale/foreign).
PRODUCT_ID = os.environ.get('AURORA_PRODUCT_ID', 'com.aurora.econometrica')
VERSION = os.environ.get('AURORA_PRODUCT_VERSION', '1.0.9')
SESSION_ID = uuid.uuid4().hex
STARTED_AT = datetime.now(timezone.utc).isoformat()

# Configure logging - dual output: stderr + rotating file в %LOCALAPPDATA%.
# %LOCALAPPDATA% (AppData\Local) гарантированно НЕ роумит в AD-доменах,
# в отличие от %APPDATA% (AppData\Roaming) - критично для RDP-серверов.
_local_appdata = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA') or '.'
_log_dir = Path(_local_appdata) / 'aurora-econometrica-gui' / 'logs'
try:
    _log_dir.mkdir(parents=True, exist_ok=True)
except Exception:
    _log_dir = Path('.')
_log_file = _log_dir / 'sidecar.log'

_log_format = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
_stderr_handler = logging.StreamHandler(sys.stderr)
_stderr_handler.setFormatter(logging.Formatter(_log_format))
# Rotation: 10MB × 7 backups = max 70MB/user. На RDP с 10+ юзерами роуминг/диск
# не лопается (при %APPDATA% + 5MB/день × 365 дней × 10 юзеров = 18GB).
_file_handler = logging.handlers.RotatingFileHandler(
    _log_file, maxBytes=10 * 1024 * 1024, backupCount=7, encoding='utf-8'
)
_file_handler.setFormatter(logging.Formatter(_log_format))

logging.basicConfig(
    level=logging.INFO,
    handlers=[_stderr_handler, _file_handler],
    force=True,
)
logger = logging.getLogger('econometrica')

# ── Silence known-benign Windows asyncio spam ───────────────────────────
# uvicorn on Windows + HTTP client disconnect = hundreds of
# `_ProactorBasePipeTransport._call_connection_lost` tracebacks per session.
# Surgical filter - preserves legitimate asyncio errors, убирает только этот тип.
class _SkipProactorNoise(logging.Filter):
    def filter(self, record):
        return '_ProactorBasePipeTransport._call_connection_lost' not in record.getMessage()

logging.getLogger('asyncio').addFilter(_SkipProactorNoise())

logger.info(
    f'=== Sidecar starting: product={PRODUCT_ID} version={VERSION} '
    f'session={SESSION_ID[:8]}… pid={os.getpid()} log={_log_file} ==='
)
logger.info(f'AURORA_MCMC_CORES={_mcmc_cores} (XLA_FLAGS={_os_early.environ.get("XLA_FLAGS")})')

# Dump bundle integrity + PyTensor/MSVC diagnostic on startup.
# Purpose: when sidecar fails at /health or model training, these logs tell
# the IT-admin exactly which bundled resource is missing (not "cannot import X").
try:
    logger.info(f'sys.executable = {sys.executable}')
    logger.info(f'sys.frozen = {getattr(sys, "frozen", False)}')
    logger.info(f'_MEIPASS = {getattr(sys, "_MEIPASS", "(not frozen)")}')

    # Known-risk bundle paths - if any missing, the sidecar WILL crash later.
    # These are the files that disappear when PyInstaller gets --hidden-import
    # but not --collect-data for the corresponding package.
    _bundle_root = Path(getattr(sys, '_MEIPASS', _sidecar_root))
    _required_files = [
        'arviz/static/html/icons-svg-inline.html',
        'arviz/data/example_data/data_local.json',
        'pytensor/__init__.py',  # pytensor always needs templates/configs alongside
        # v1.0.9: NumPyro + JAX (Tier-1 NUTS sampler)
        'numpyro/__init__.py',
        'jax/__init__.py',
        # v2.0.1 Phase 1.6 + 1.7 — JCS canonical hash + multi-tab file lock
        # (audit C-01: bundle ships silently broken without these).
        'rfc8785/__init__.py',
        'filelock/__init__.py',
    ]
    for rel in _required_files:
        p = _bundle_root / rel
        logger.info(f'bundle check: {rel} - {"OK" if p.exists() else "MISSING"} ({p})')

    # Hard probe — import обоих модулей. Lazy import inside utility functions
    # пропускает ImportError до первого вызова → silent bundle break. Здесь
    # ловим at startup и логируем явно.
    for mod_name in ('rfc8785', 'filelock'):
        try:
            __import__(mod_name)
            logger.info(f'bundle check: {mod_name} import OK')
        except ImportError as e:
            logger.error(f'bundle check: {mod_name} IMPORT FAILED — {e}')

    # PyTensor compiler probe
    from engines.modeler import check_compiler as _check_compiler
    _has_cc = _check_compiler()
    logger.info(f'check_compiler() = {_has_cc}')
    logger.info(f'PATH (first 300 chars): {os.environ.get("PATH", "")[:300]}')
    logger.info(f'INCLUDE (first 200 chars): {os.environ.get("INCLUDE", "(not set)")[:200]}')
    logger.info(f'LIB (first 200 chars): {os.environ.get("LIB", "(not set)")[:200]}')
    import pytensor
    logger.info(f'pytensor.config.cxx = "{pytensor.config.cxx}"')
    logger.info(f'pytensor.config.mode = "{pytensor.config.mode}"')
    logger.info(f'pytensor.config.compiledir = "{pytensor.config.compiledir}"')
    # Probe arviz to surface its FileNotFoundError early with a clear message
    import arviz  # noqa: F401
    logger.info('arviz import: OK')

    # Probe JAX devices - подтверждение что XLA_FLAGS применился до init.
    # Если XLA_FLAGS не сработал (старый jax, ручной override) - devices=1,
    # NumPyro chain_method auto-fallback на 'vectorized' в modeler.py.
    try:
        import jax as _jax  # noqa: F401
        _devices = _jax.devices()
        logger.info(
            f'JAX devices: {len(_devices)} × {_jax.default_backend()} '
            f'(expected={_mcmc_cores})'
        )
    except Exception as _e:
        logger.warning(f'JAX probe failed: {_e}')
except Exception as e:
    logger.exception(f'Startup diagnostic failed: {e}')

app = FastAPI(
    title='Aurora AI Econometrica Sidecar',
    version=VERSION,
    description='Local MMM computation engine (0 tokens)',
)


# ── Stale backup cleanup (H-07) ──────────────────────────────────────────────
# Phase 0.3 + 1.4 created `.pre_2.0.1` backups per migration but `cleanup_stale_backups`
# never gets called → unbounded backup accumulation on terminal-server / RDP installs
# with 100+ projects migrated over time. Run once on sidecar startup, keep last 3
# per project.
@app.on_event('startup')
async def _startup_cleanup_stale_backups():
    try:
        # Lazy import — utils.safe_io доступен только после basic startup probes.
        from utils.safe_io import cleanup_stale_backups
        # Канонический projects root — единый источник для всех проектов.
        appdata = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
        if not appdata:
            return
        projects_root = Path(appdata) / 'aurora-econometrica-gui' / 'projects'
        if not projects_root.exists():
            return
        total_removed = 0
        for project_dir in projects_root.iterdir():
            if not project_dir.is_dir():
                continue
            try:
                removed = cleanup_stale_backups(project_dir, keep_last=3)
                total_removed += len(removed)
            except OSError:
                continue
        if total_removed:
            logger.info(f'startup cleanup: removed {total_removed} stale backup file(s)')
    except Exception as e:
        logger.warning(f'startup backup cleanup failed: {e}')


# ── Global exception handler (JSON envelope) ─────────────────────────────────
# Без него любая необработанная ошибка возвращается uvicorn'ом как plain text
# `Internal Server Error`. Rust-сторона валится на парсинге с «expected value
# at line 1 column 1». Под RemoteApp (другой профиль/env/тайминги) вероятность
# неожиданных ошибок выше - пример: PermissionError на записи результата.
#
# HTTPException и RequestValidationError обрабатываются встроенными handler'ами
# FastAPI - явно пропускаем их (re-raise) чтобы не перехватить 400/404/422.
from starlette.exceptions import HTTPException as _StarletteHTTPException

@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, _StarletteHTTPException):
        raise exc
    logger.exception(f'Unhandled exception on {request.method} {request.url.path}')
    return JSONResponse(
        status_code=500,
        content={
            'status': 'error',
            'message': str(exc)[:500],  # truncate - избегаем длинных путей в body
            'type': type(exc).__name__,
            'path': str(request.url.path),
        },
    )


# ── Session middleware (handshake protection) ────────────────────────────────
# Каждый API-запрос от GUI может включать заголовок `X-Expected-Session: <uuid>`.
# Если он не совпадает с текущим SESSION_ID - это значит GUI разговаривает с
# процессом, которого он не создавал (переиспользованный чужой sidecar).
# Отвечаем 409 Conflict - GUI перехватывает и делает re-handshake + retry once.
@app.middleware('http')
async def session_guard(request: Request, call_next):
    # Health и shutdown пропускаем - они сами служат для разрешения рассинхрона
    if request.url.path in ('/health', '/shutdown'):
        return await call_next(request)

    expected = request.headers.get('X-Expected-Session')
    if expected and expected != SESSION_ID:
        logger.warning(
            f'session_guard: 409 for {request.url.path} '
            f'(header={expected[:8]}… vs self={SESSION_ID[:8]}…)'
        )
        return JSONResponse(
            status_code=409,
            content={
                'status': 'session_mismatch',
                'expected': expected,
                'actual': SESSION_ID,
                'product': PRODUCT_ID,
                'version': VERSION,
            },
        )
    return await call_next(request)


# ── Graceful shutdown ────────────────────────────────────────────────────────
# Signal от родителя (Rust закрывает GUI) или HTTP /shutdown - cleanup + exit.
# Без этого сигналa child.kill() оставляет corrupted PyInstaller temp + pickle.
_shutdown_event = threading.Event()


def _shutdown_requested(reason: str):
    if _shutdown_event.is_set():
        return
    _shutdown_event.set()
    logger.info(f'Shutdown requested ({reason}), cleaning up and exiting')
    # Flush logs
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:
            pass
    # Даём uvicorn ~500ms на отдачу текущих ответов, затем exit
    def _exit_soon():
        time.sleep(0.5)
        os._exit(0)
    threading.Thread(target=_exit_soon, daemon=True).start()


def _install_signal_handlers():
    try:
        signal.signal(signal.SIGTERM, lambda *_: _shutdown_requested('SIGTERM'))
    except Exception as e:
        logger.debug(f'SIGTERM handler not installable: {e}')
    try:
        signal.signal(signal.SIGINT, lambda *_: _shutdown_requested('SIGINT'))
    except Exception as e:
        logger.debug(f'SIGINT handler not installable: {e}')


_install_signal_handlers()


# ── Pydantic models ──────────────────────────────────

class ValidateRequest(BaseModel):
    file_path: str
    project_dir: str | None = None


class PreviewRequest(BaseModel):
    file_path: str
    n_rows: int = 20


class TrainRequest(BaseModel):
    project_dir: str
    data_file: str
    kpi_column: str
    media_columns: list[str]
    control_columns: list[str] = []
    date_column: str = 'date'
    adstock_config: dict[str, str] = {}
    mcmc_override: dict | None = None
    # Sprint 2 (small-data path): 'bayesian' (default, NUTS) | 'ols' (closed-form, n<30 fallback)
    mode: str | None = None
    # Sprint 2 / A3: opt-in horseshoe priors для sparse channel selection.
    # Когда True, каналы с истинным β≈0 получают strong shrinkage to zero,
    # уменьшая overfit на small N. Не влияет на mode='ols'.
    use_horseshoe: bool = False
    # Стоимость 1 юнита канала в валюте KPI для не-денежных каналов (CPP/CPM).
    # {channel: cost_per_unit}. Если задано - decomposer/optimizer используют
    # spend × unit_cost для отображения и расчёта ROI. На обучение модели не
    # влияет (Hill работает на нативных единицах канала).
    unit_costs: dict[str, float] = {}
    # v2.1.0 (ADR-020): KPI type для smart math + future kpi_kind awareness.
    # 'sales'/'profit'/'revenue' → monetary; 'sales_packs'/'leads'/'registrations'/
    # 'count_custom' → count (β в этих units, без ROI money conversion).
    # 'aided_awareness'/'top_of_mind'/'unaided_awareness' → reject через
    # KPI_TYPE_NOT_IMPLEMENTED (требуют Phase A1a logit-Normal likelihood).
    kpi_type: str = 'sales'
    # v2.1.0 (ADR-021): средняя цена единицы count KPI в ₽ для money ROI
    # conversion. None = ROI/contribution в native KPI units (legacy).
    # Применимо только когда kpi_kind == 'count' (sales_packs/leads/etc).
    kpi_unit_cost: float | None = None
    # Виртуальные merged каналы (например «Малые медиа» из 4 источников).
    # Frontend InsightsPanel создаёт их как metadata. Backend создаёт
    # df[merged_name] = sum(df[sources]) до column guard. См. utils/merge_rules.py.
    merge_rules: dict[str, list[str]] = {}
    # Trust Level 3 (v1.1.0): brand vs performance split.
    # {channel_name: 'brand' | 'performance' | 'mixed'}
    # Empty / all-mixed → backward compat single-prior path. ≥2 brand or ≥2 perf →
    # hierarchical priors с group-conditional sigma + decay mu.
    channel_categories: dict[str, str] = {}
    # E2 (2026-07-03): калибровка lift-тестами (Robyn §4.3 / Jin 2017) —
    # [{channel, date_from, date_to, lift_abs, lift_low?, lift_high?,
    #   confidence_level?, sigma_abs?, test_type?}]. Только bayesian.
    calibrations: list[dict] | None = None
    # F-AUD-1 (аудит 2026-07-04): Pydantic v2 МОЛЧА отбрасывает поля вне схемы —
    # тумблер «Авто-праздники РФ» и opt-out слались фронтом, но терялись здесь
    # (боевое доказательство: Кагоцел use_holidays=false в project.json, а в
    # pickle 12 инжектированных праздников). Флаги объявлены явно; движок
    # читает config.get(..., default) — семантика не меняется, доставка чинится.
    use_holidays: bool = True
    disabled_holidays: list[str] = []
    # Автосезонность (2026-07-04): мастер-флаг Фурье-компоненты сезонной волны.
    # 🔴 ЯКОРЬ (У2): флаги обучения обязаны быть в ОБЕИХ схемах (Train+TrainStart)
    # И в train-config.js buildTrainConfig — иначе поле теряется (F-AUD-1).
    # Стережёт tools/test_frontend_schema_parity.py.
    use_seasonality: bool = True


class TrainStartRequest(BaseModel):
    project_dir: str
    data_file: str
    kpi_column: str
    media_columns: list[str]
    control_columns: list[str] = []
    date_column: str = 'date'
    adstock_config: dict[str, str] = {}
    mcmc_override: dict | None = None
    # Sprint 2: 'bayesian' | 'ols'
    mode: str | None = None
    # Sprint 2 / A3: opt-in horseshoe priors
    use_horseshoe: bool = False
    unit_costs: dict[str, float] = {}
    # v2.1.0 (ADR-020): см. TrainRequest.kpi_type
    kpi_type: str = 'sales'
    # v2.1.0 (ADR-021): см. TrainRequest.kpi_unit_cost
    kpi_unit_cost: float | None = None
    merge_rules: dict[str, list[str]] = {}
    # Trust Level 3 (v1.1.0): channel_categories propagated в train_model config.
    channel_categories: dict[str, str] = {}
    # E2 (2026-07-03): см. TrainRequest.calibrations.
    calibrations: list[dict] | None = None
    # F-AUD-1: см. TrainRequest — async-путь (GUI) страдал той же потерей флагов.
    use_holidays: bool = True
    disabled_holidays: list[str] = []
    use_seasonality: bool = True


class DecomposeRequest(BaseModel):
    project_dir: str
    # Trust Level 2: override unit_costs поверх pickle-config.
    # Нужно когда user изменил CPP после тренировки - pickle содержит старые значения.
    unit_costs: dict[str, float] | None = None
    # Phase 2 audit pass 4 - per-channel annual CPP/CPM inflation rate (e.g.
    # {'TV': 25.0, 'OLV': 18.0}). Customer-entered current cost (latest training
    # year) gets adjusted к training-period weighted-average via inflation
    # rollback. None → no adjustment (legacy behavior).
    unit_cost_inflation_pct: dict[str, float] | None = None
    # v2.1.0 (ADR-021): override kpi_unit_cost из current UI (не из pickle).
    # Нужно когда юзер изменил «среднюю цену единицы» после тренировки и хочет
    # видеть money ROI с новым значением. None = используем pickle snapshot.
    kpi_unit_cost: float | None = None


class OptimizeRequest(BaseModel):
    project_dir: str
    total_budget: float | None = None
    # Альтернатива total_budget: constraint в money (Σ x × unit_cost == total_budget_money).
    # Используется в Forecast режиме «Сохранить бюджет» - чтобы сумма в рублях
    # после оптимизации оставалась точно равной currentMoney.
    total_budget_money: float | None = None
    min_pct: float = 50
    max_pct: float = 150
    # Per-channel constraints (экспертный режим). Перекрывают глобальные min_pct/max_pct
    # для указанных каналов. Если канал отсутствует в dict - используется глобальный лимит.
    min_per_channel: dict[str, float] | None = None
    max_per_channel: dict[str, float] | None = None
    # D.3 - Per-group constraints (Trust 3 brand vs performance).
    # Optional. Unset = behavior identical к pre-D.3 (single global slider).
    # Mixed/uncategorized channels всегда fall back к global регардлесс этих полей.
    # Constraint hierarchy: brand_max ≤ global_max + perf_max ≤ global_max enforced.
    brand_min_pct: float | None = None
    brand_max_pct: float | None = None
    perf_min_pct: float | None = None
    perf_max_pct: float | None = None
    # Override unit_costs (аналогично DecomposeRequest).
    unit_costs: dict[str, float] | None = None
    # L9 (math-fix v1.4 Section C, 2026-04-29): forward-compat budget_mode.
    # Currently only 'fixed' supported (optimizer always preserves budget).
    # 'free' planned для v1.1 - optimizer chooses any total в каналах bounds.
    # Validation rejects 'free' с TODO error чтобы early callers не shipped
    # against unimplemented behavior.
    budget_mode: str = 'fixed'
    # ─── Phase 2 (Planning Mode) - audit pass 2 2026-05-02 ───
    # Opt-in planning mode. Absence of forecast_periods → analyst mode (current
    # behavior preserved byte-exact). Integer ≥ 1 → planning mode (Option C
    # per-period Hill summation, см. docs/MATH_AUDIT_v2_0_FORECAST_HORIZON.md).
    # Hard cap forecast ≤ train_n × 2 enforced inline в optimizer.
    forecast_periods: int | None = None
    # Optional UI label echoed в result (Год/Полугодие/Квартал/Custom). Pure
    # display - backend logic uses forecast_periods only.
    forecast_period_label: str | None = None
    # Phase 2 audit pass 4 - per-channel annual CPP/CPM inflation rate.
    unit_cost_inflation_pct: dict[str, float] | None = None
    # v2.1.0 (ADR-021): см. DecomposeRequest.kpi_unit_cost
    kpi_unit_cost: float | None = None


class ScenarioRequest(BaseModel):
    project_dir: str
    scenario_name: str = 'custom'
    media_plan: dict[str, list[float]] = {}
    # Phase 2 - planning context (audit pass 4 2026-05-02). Когда forecast_periods
    # задан, scenario engine распределяет single-period mediaPlan totals по
    # forecast_periods (вместо training_n_periods) - matches optimizer planning
    # mode + reports «бюджет 2026 года» (не training horizon).
    forecast_periods: int | None = None
    forecast_period_label: str | None = None
    media_plan_file: str | None = None
    unit_costs: dict[str, float] | None = None
    # Phase 2 audit pass 4 - per-channel annual CPP/CPM inflation rate.
    unit_cost_inflation_pct: dict[str, float] | None = None
    # v2.1.0 (ADR-021): см. DecomposeRequest.kpi_unit_cost
    kpi_unit_cost: float | None = None
    # Task 7: planning carry-in + holiday injection context.
    # future_dates: ISO-даты будущих периодов для holiday calendar injection.
    # carry_in: True (default) = использовать adstock carry-in из истории.
    future_dates: list[str] | None = None
    carry_in: bool = True


# ──────────────────────────────────────────────────────────────────
# Sprint 3 Pharma Causal - request models (per ADR §4.2)
# Per ADR §1: EXTEND-not-rewrite. New endpoints в /compute/causal/* namespace,
# не touching existing /compute/{train,decompose,optimize,scenario,...}.
# ──────────────────────────────────────────────────────────────────


class CausalPreflightRequest(BaseModel):
    """Sprint 3 M4: Unified validation + method recommendation."""
    file_path: str
    unit_column: str
    time_column: str
    kpi_column: str
    treatment_column: str | None = None
    treated_unit: Any = None
    treatment_period: Any = None
    feature_columns: list[str] | None = None
    sheet_name: str | None = None


class CausalListRequest(BaseModel):
    """Sprint 3 M4: List causal artifacts in project."""
    project_dir: str


class CausalConsistencyRequest(BaseModel):
    """Sprint 3 M4: Cross-method consistency check."""
    project_dir: str


class CausalForestRequest(BaseModel):
    """Sprint 3 M3: Causal Forest для Heterogeneous Treatment Effects (HTE)."""
    project_dir: str
    data_file: str
    kpi_column: str
    treatment_column: str
    feature_columns: list[str]
    confounder_columns: list[str] | None = None
    confidence: float = 0.9
    n_estimators: int = 200
    sheet_name: str | None = None
    random_state: int = 42
    unit_column: str | None = None  # optional, для panel context
    time_column: str | None = None


class CausalSCMRequest(BaseModel):
    """Sprint 3 M2: Synthetic Control Method (Abadie classic).

    treated_unit must exist в data; treatment_period splits panel into
    pre/post (≥6 pre-periods, ≥1 post-period). Inference via permutation
    placebo test.
    """
    project_dir: str
    data_file: str
    unit_column: str
    time_column: str
    kpi_column: str
    treated_unit: Any  # type matching unit_column dtype (str typical)
    treatment_period: Any  # type matching time_column dtype (str/date/int)
    confidence: float = 0.9
    sheet_name: str | None = None
    run_placebo: bool = True


class CausalDiDRequest(BaseModel):
    """Sprint 3 M1: Difference-in-Differences (TWFE).

    treatment_column convention: 1 if (unit treated AND time >= treatment_start),
    else 0. User responsible for proper encoding before passing to endpoint.
    """
    project_dir: str
    data_file: str
    unit_column: str
    time_column: str
    kpi_column: str
    treatment_column: str
    control_columns: list[str] = []
    confidence: float = 0.9
    sheet_name: str | None = None  # Excel sheet selector (used для MMX dataset Афала/etc)


class AwarenessRequest(BaseModel):
    project_dir: str
    data_file: str
    awareness_column: str = 'awareness_%'
    media_columns: list[str] = []
    forecast_periods: int = 12


class AwarenessSalesRequest(BaseModel):
    project_dir: str
    data_file: str
    awareness_column: str = 'awareness_%'
    sales_column: str = 'sales'


class ChartRequest(BaseModel):
    project_dir: str
    chart_type: str  # 'waterfall', 'response_curves', 'awareness', 's_curve', 'mqs'


class AdstockSelectRequest(BaseModel):
    file_path: str
    kpi_column: str
    media_columns: list[str]
    date_column: str | None = None


class PptxExportRequest(BaseModel):
    project_id: str
    model_data: dict
    decompose_data: dict
    optimize_data: dict
    # Абсолютный путь к project_dir - передаётся Rust-стороной чтобы
    # учесть Settings override (econometrica_projects_root). Fallback на
    # вычисление из %APPDATA% если None для обратной совместимости со старым Rust.
    project_dir: str | None = None
    # INV-50 NEW-2: явный флаг для разработчиков — разрешает wireframe-режим
    # (builder генерирует ДЕМОНСТРАЦИОННЫЕ числа) при отсутствии decompose_data.
    # Без флага пустой decompose_data → 400 (honest-fail, не тихая фикция).
    allow_wireframe: bool = False


class HtmlExportRequest(BaseModel):
    project_id: str
    model_data: dict
    decompose_data: dict
    optimize_data: dict
    project_name: str = 'Marketing Mix Model'
    project_dir: str | None = None
    # INV-50 NEW-2: явный флаг для разработчиков — разрешает wireframe-режим
    # при отсутствии decompose_data (только dev-превью, числа ДЕМОНСТРАЦИОННЫЕ).
    allow_wireframe: bool = False


class ModelHistoryRequest(BaseModel):
    project_dir: str


# ── Async training state ─────────────────────────────
# task_id → {status, phase, pct, elapsed_sec, result, error, started_at}
_training_tasks: dict[str, dict] = {}
_training_lock = threading.Lock()


# ── Health ───────────────────────────────────────────

@app.get('/health')
async def health():
    """Extended /health (v1.0.9+) - handshake protocol.

    Возвращает product/session_id/pid/started_at для version-handshake
    в Rust-стороне. Старые GUI-клиенты (pre-v1.0.9) игнорируют новые поля.
    """
    packages = {}
    for pkg in ['pymc', 'pymc_marketing', 'pandas', 'scipy', 'matplotlib', 'numpy',
                'numpyro', 'jax', 'arviz', 'pytensor']:
        try:
            mod = __import__(pkg)
            packages[pkg] = getattr(mod, '__version__', 'installed')
        except Exception:  # ImportError | AttributeError | RuntimeError
            packages[pkg] = None

    return {
        'status': 'ok',
        'product': PRODUCT_ID,
        'version': VERSION,
        'session_id': SESSION_ID,
        'pid': os.getpid(),
        'started_at': STARTED_AT,
        'python': sys.version,
        'packages': packages,
    }


@app.post('/shutdown')
async def shutdown():
    """Graceful shutdown. Rust вызывает при GUI close перед force-kill.
    Возвращает сразу, cleanup+exit выполняются в фоне через 500ms."""
    _shutdown_requested('HTTP /shutdown')
    return {'status': 'shutting_down', 'session_id': SESSION_ID}


# ── Static asset endpoints (v2.0.1 SSOT) ─────────────

class ProjectMigrateRequest(BaseModel):
    """Phase 1.4 — project.json schema migration request."""
    project_dir: str


@app.post('/project/migrate')
def project_migrate_endpoint(req: ProjectMigrateRequest):
    """Sync migration project.json к schema_version 2.0.1 (Phase 1.4).

    Идемпотентен: повторный вызов на уже migrated project возвращает
    {status: 'no_migration_needed'}. Pre-mutation backup с SHA-256
    checksum (recoverable on failure). Atomic write через Phase 0.3
    safe_io.

    NB: sync version. Async progress UI с modal — defer к v2.0.2.
    Expected duration <100ms для project.json <50KB.
    """
    try:
        from pathlib import Path
        from engines.project_migration import migrate_project_file
        from utils.log_config import setup_module_logger, log_event

        m_logger = setup_module_logger('migration')
        # H-01 path traversal guard — reject если project_dir вне projects root.
        proj_dir = _assert_project_dir_safe(req.project_dir)
        proj_json = proj_dir / 'project.json'

        # C-02 multi-tab safety: lock на время read-modify-write.
        # Если другая вкладка / процесс уже мигрирует тот же project —
        # ждём до 5s, потом 423 Locked.
        from utils.file_lock import project_lock, LockTimeout
        try:
            with project_lock(proj_dir, timeout=5.0):
                result = migrate_project_file(proj_json)
        except LockTimeout as lt:
            log_event(
                m_logger, 'project_migrate_lock_timeout',
                level=logging.WARNING, project_dir=str(proj_dir),
            )
            return JSONResponse(status_code=423, content={
                'status': 'error',
                'error_code': 'LOCK_TIMEOUT',
                'message': str(lt),
            })

        log_event(
            m_logger,
            'project_migrate_invoked',
            project_dir=str(proj_dir),
            status=result.get('status'),
            from_version=result.get('from_version'),
            to_version=result.get('to_version'),
            moved_count=len(result.get('migrated_columns', [])),
        )

        return result
    except Exception as e:
        logger.exception('Migration endpoint FAILED')
        return JSONResponse(status_code=500, content={
            'status': 'error',
            'message': _friendly_error(e),
            'type': type(e).__name__,
        })


@app.get('/api/static/classifier-patterns-v1.json')
async def get_classifier_patterns_v1():
    """SSOT classifier patterns export для frontend (Phase 1.1).

    Frontend (src/lib/services/classifier-patterns.js) fetches это once на
    startup, cache в localStorage, falls back к embedded patterns если
    endpoint unavailable. Заменяет regex duplication между Python и
    ValidateStepV13.svelte / AppliedModeSummary.svelte (audit P-04/P-05).

    Versioned (v1) — future pattern updates ship с v2 endpoint + Sunset
    header для graceful migration.
    """
    from utils.column_detection import export_patterns_as_json
    payload = export_patterns_as_json()
    payload['generated_at'] = STARTED_AT
    payload['sidecar_session'] = SESSION_ID
    return payload


# ── Compute endpoints ────────────────────────────────

@app.post('/compute/validate')
def validate_data(req: ValidateRequest):
    """Validate dataset for MMM readiness."""
    from engines.validator import validate_data as _validate
    result = _validate(req.file_path, req.project_dir)
    return JSONResponse(content=result)


@app.post('/compute/validate/preview')
def validate_preview(req: PreviewRequest):
    """Read first N rows of a file for preview in Import step UI.

    Returns {status, headers, rows, dtypes, shape, file_name, size_kb}.
    """
    from engines.validator import data_preview as _preview
    result = _preview(req.file_path, req.n_rows)
    return JSONResponse(content=result)


_VALID_MODES = ('bayesian', 'ols')


def _validate_mode(mode: str | None) -> tuple[str | None, dict | None]:
    """Audit H5 (2026-04-26): whitelist mode values + return user-friendly error.

    Returns (resolved_mode, error_response).
    error_response is None on success - caller proceeds with resolved_mode.
    """
    if mode is None:
        return 'bayesian', None
    normalized = str(mode).strip().lower()
    if normalized not in _VALID_MODES:
        return None, {
            'status': 'error',
            'error_code': 'INVALID_MODE',
            'message': (
                f'Неизвестный режим обучения "{mode}". '
                f'Допустимые: {", ".join(_VALID_MODES)}. '
                f'Опечатки в API call могут silently отправить вас на wrong engine - '
                f'этот guard защищает от такого.'
            ),
        }
    return normalized, None


@app.post('/compute/train')
def train_model(req: TrainRequest):
    """Train Bayesian MMM или OLS small-data model.

    Mode selection (Sprint 2):
      - config.mode == 'ols' → engines/ols_modeler.train_ols (closed-form, < 1 sec)
      - config.mode == 'bayesian' or absent → engines/modeler.train_model (NUTS, 3-15 min)
      - When mode absent, server can call /compute/recommend для auto-recommend hint.

    Audit H5 (2026-04-26): mode value validated against whitelist -
    typo 'olss' returns 422-style error instead of silently routing к Bayesian.

    sync def - FastAPI runs in thread pool, event loop stays free for /health polling."""
    config = req.model_dump()
    project_dir = config.pop('project_dir')
    mode, err = _validate_mode(config.get('mode'))
    if err is not None:
        return JSONResponse(content=err)
    if mode == 'ols':
        from engines.ols_modeler import train_ols as _train
    else:
        from engines.modeler import train_model as _train
    result = _train(config, project_dir)
    # F-MC-1 (2026-07-04, Венарус-зонд): NaN в диагностике (вырожденный канал)
    # валил СЕРИАЛИЗАЦИЮ ответа 500-кой «Out of range float values» — файлы
    # санитайзились (NaN→null), а HTTP-ответ нет. Класс P3 NaN-blindspot.
    from utils.safe_io import sanitize_nonfinite
    return JSONResponse(content=sanitize_nonfinite(result))


class CategorizeRequest(BaseModel):
    """Trust Level 3: batch auto-suggest channel categorization (issue H).

    Frontend Validate шаг calls этот endpoint при mount → instantly заполняет
    badges 🎯/📊/⚪ + confidence score. Single source of truth - Python heuristic
    в utils/channel_categorization.py.
    """
    channels: list[str]


@app.post('/utils/auto_suggest_categories')
def auto_suggest_categories_endpoint(req: CategorizeRequest):
    """Returns {channel: {category, confidence, reasoning}} per channel."""
    from utils.channel_categorization import auto_suggest_categories
    suggestions = auto_suggest_categories(req.channels)
    return JSONResponse(content={'status': 'ok', 'suggestions': suggestions})


class RecommendRequest(BaseModel):
    """Sprint 2: auto-recommend Bayesian vs OLS based on n_obs."""
    n_obs: int
    override: str | None = None  # 'bayesian' | 'ols' | None


@app.post('/compute/recommend')
def recommend_engine_endpoint(req: RecommendRequest):
    """Sprint 2 - return engine recommendation for given dataset size.

    UI calls this after user selects data file (n_obs from validate result)
    to render banner: "Рекомендуем Bayesian" / "Рекомендуем OLS (small data)".
    """
    from engines.ols_modeler import recommend_engine
    return JSONResponse(content=recommend_engine(req.n_obs, override=req.override))


class PreflightRequest(BaseModel):
    """S1 (audit synergy 2026-04-26): unified pre-train orchestration.

    UI один call вместо 3 (validate + recommend + quick_proxy + prior_predictive).
    Backend chains all reliability checks + returns aggregated tier + recommendation.
    """
    project_dir: str
    file_path: str
    media_columns: list[str]
    control_columns: list[str] = []
    kpi_column: str
    date_column: str = 'date'
    adstock_config: dict[str, str] = {}
    mode_override: str | None = None  # 'bayesian' | 'ols' | None - для recommend
    skip_prior_predictive: bool = False  # для fast iteration UI


@app.post('/compute/preflight')
def preflight(req: PreflightRequest):
    """Unified pre-train reliability pipeline (S1 audit synergy).

    Orchestrates в правильном порядке:
      1. Engine recommendation (n_obs based)
      2. A4 quick proxy - multicollinearity + variance + correlation (~1 sec)
      3. (Bayesian only, if not skipped) Prior predictive check (~5-15 sec)

    Returns aggregated tier ('reliable' | 'directional' | 'insufficient') +
    recommended_mode + breakdown of all checks + actionable recommendation +
    overrideable flag. UI renders single banner вместо five individual.

    Skip prior_predictive_check для OLS recommendations (frequentist mode не
    использует priors). Also skipped explicitly via skip_prior_predictive=True
    (for fast iteration when user экспериментирует с config).
    """
    import logging as _logging
    _preflight_logger = _logging.getLogger(__name__)

    # Validate mode override first
    mode_override, mode_err = _validate_mode(req.mode_override)
    if mode_err is not None:
        return JSONResponse(content=mode_err)

    # Step 1: read data + basic shape check
    try:
        if req.file_path.endswith('.csv'):
            import pandas as _pd
            df = _pd.read_csv(req.file_path)
        else:
            import pandas as _pd
            df = _pd.read_excel(req.file_path)
    except Exception as e:
        return JSONResponse(content={
            'status': 'error', 'error_code': 'DATA_LOAD_FAILED',
            'message': f'Не удалось прочитать файл: {type(e).__name__}: {e}',
        })

    n_obs = len(df)
    missing_cols = [c for c in req.media_columns + [req.kpi_column] if c not in df.columns]
    if missing_cols:
        return JSONResponse(content={
            'status': 'error', 'error_code': 'COLUMNS_MISSING',
            'message': f'Колонки не найдены в файле: {missing_cols}',
            'available_columns': df.columns.tolist(),
        })

    # Step 2: engine recommendation
    from engines.ols_modeler import recommend_engine
    recommend = recommend_engine(n_obs, override=mode_override)
    recommended_mode = recommend['recommended']

    # Step 3: A4 quick proxy на media matrix
    from utils.reliability_quick_proxy import quick_proxy_check
    media_matrix = df[req.media_columns].fillna(0).values.astype(float)
    quick_proxy = quick_proxy_check(media_matrix, req.media_columns)

    # Step 4: prior predictive (Bayesian only, optional skip)
    prior_predictive = None
    if recommended_mode == 'bayesian' and not req.skip_prior_predictive:
        try:
            from utils.reliability_a4 import prior_predictive_check
            y_obs = df[req.kpi_column].fillna(0).values.astype(float)
            prior_predictive = prior_predictive_check(
                y_obs, media_matrix, n_samples=300,  # 300 fast enough для preflight
            )
        except Exception as e:
            _preflight_logger.warning(
                f"Prior predictive check failed in preflight (degrading к quick_proxy only): "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )
            prior_predictive = None

    # ── Aggregate tier ──────────────────────────────────────────────────
    # Conservative aggregation: tier = worst of (recommend, quick_proxy, prior_predictive).
    # Mapping:
    #   recommend.banner_tone: good→reliable, warn→directional, bad→insufficient
    #   quick_proxy.tier: reliable | directional | insufficient (already correct)
    #   prior_predictive.status: pass→reliable, warn→directional, fail→insufficient
    tier_rank = {'reliable': 0, 'directional': 1, 'insufficient': 2}
    tone_to_tier = {'good': 'reliable', 'warn': 'directional', 'bad': 'insufficient'}
    status_to_tier = {'pass': 'reliable', 'warn': 'directional', 'fail': 'insufficient'}

    tiers = ['reliable']  # baseline
    tiers.append(tone_to_tier.get(recommend.get('banner_tone'), 'reliable'))
    tiers.append(quick_proxy.get('tier', 'reliable'))
    if prior_predictive is not None:
        tiers.append(status_to_tier.get(prior_predictive.get('status'), 'reliable'))
    overall_tier = max(tiers, key=lambda t: tier_rank.get(t, 0))

    # Aggregate warnings + recommendation
    all_warnings = []
    if recommend.get('reason') and recommend['banner_tone'] != 'good':
        all_warnings.append(recommend['reason'])
    all_warnings.extend(quick_proxy.get('warnings', []))
    if prior_predictive and prior_predictive.get('warning'):
        all_warnings.append(prior_predictive['warning'])

    # Override flag - when overall not reliable but user can still train
    overrideable = quick_proxy.get('overrideable', True)

    return JSONResponse(content={
        'status': 'ok',
        'overall_tier': overall_tier,
        'recommended_mode': recommended_mode,
        'allowed_modes': recommend.get('allowed', ['bayesian', 'ols']),
        'overrideable': overrideable,
        'n_obs': n_obs,
        'n_channels': len(req.media_columns),
        'breakdown': {
            'engine_recommend': recommend,
            'quick_proxy': quick_proxy,
            'prior_predictive': prior_predictive,
        },
        'warnings': all_warnings,
        'recommendation': _aggregate_recommendation(overall_tier, recommended_mode, len(all_warnings)),
    })


def _ru_problems(n: int) -> str:
    """Склонение: 1 проблема / 2-4 проблемы / 5+ проблем."""
    if n % 10 == 1 and n % 100 != 11:
        return f'{n} проблема'
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f'{n} проблемы'
    return f'{n} проблем'


def _aggregate_recommendation(tier: str, mode: str, n_warnings: int) -> str:
    """Build single human-readable recommendation from aggregated tier + mode.

    C3-полутон (2026-07-03): текст уходит в КЛИЕНТСКИЙ preflight-баннер —
    без тех-жаргона («см. breakdown.warnings», «multicollinearity», «fragile»)
    и с правильным склонением («1 проблем» → «1 проблема»).
    """
    if tier == 'reliable':
        return (
            f'Данные прошли все проверки. Рекомендуемый режим обучения: '
            f'{"Bayesian MMM" if mode == "bayesian" else "OLS (малые данные)"}.'
        )
    if tier == 'directional':
        return (
            f'По данным есть предупреждения ({_ru_problems(n_warnings)} — перечислены выше). '
            f'Обучение возможно, но используйте результаты как направление, '
            f'а не точную оценку.'
        )
    # insufficient
    return (
        f'Данные требуют внимания ({_ru_problems(n_warnings)} — перечислены выше). '
        f'Перед обучением рекомендуется: собрать больше данных, упростить медиа-микс '
        f'либо убрать сильно связанные между собой каналы. Можно обучить и так — '
        f'результаты будут помечены как ненадёжные.'
    )


def _cleanup_stale_training_tasks(now: float | None = None) -> int:
    """Мат-аудит 2026-07-02 (F-21): чистка _training_tasks. Вызывать ПОД _training_lock.

    Два критерия:
    1. consumed_at старше 5 мин (прежнее поведение, C3: result забрали — держим
       короткое окно для ретраев фронта);
    2. терминальный статус (done/error/cancelled) старше 60 мин БЕЗ consumed_at —
       раньше такие задачи жили вечно вместе с полным result в памяти (фронт
       закрыли до done / error никто не забрал / cancelled result не читается).
       Модель при этом НЕ теряется — она на диске (latest.pkl + diagnostics).

    Returns: число удалённых задач.
    """
    ts = now if now is not None else time.time()
    consumed_cutoff = ts - 300
    terminal_cutoff = ts - 3600
    stale = [
        k for k, v in _training_tasks.items()
        if (v.get('consumed_at', 0) and v['consumed_at'] < consumed_cutoff)
        or (v.get('status') in ('done', 'error', 'cancelled')
            and not v.get('consumed_at')
            and v.get('started_at', 0) < terminal_cutoff)
    ]
    for k in stale:
        del _training_tasks[k]
    return len(stale)


@app.post('/compute/train/start')
def train_start(req: TrainStartRequest):
    """Start async training. Returns task_id immediately."""
    task_id = str(uuid.uuid4())
    config = req.model_dump()
    config.pop('project_dir')
    project_dir = req.project_dir
    logger.info(f'/compute/train/start: kpi={req.kpi_column}, media={len(req.media_columns)} channels, merge_rules={req.merge_rules!r}')

    with _training_lock:
        _cleanup_stale_training_tasks()

        _training_tasks[task_id] = {
            'status': 'running',
            'phase': 'loading',
            'pct': 0,
            'elapsed_sec': 0,
            'started_at': time.time(),
            'result': None,
            'error': None,
        }

    # Audit H5: validate mode BEFORE async run starts - fail-fast user feedback.
    _resolved_mode, _mode_err = _validate_mode(config.get('mode'))
    if _mode_err is not None:
        with _training_lock:
            _training_tasks[task_id] = {
                'status': 'error', 'phase': 'invalid_mode', 'pct': 0,
                'elapsed_sec': 0, 'started_at': time.time(),
                'result': _mode_err, 'error': _mode_err.get('message'),
            }
        return JSONResponse(content={'task_id': task_id, 'status': 'error', 'message': _mode_err['message']})

    def run():
        # Sprint 2: route to OLS engine when config.mode == 'ols'
        if _resolved_mode == 'ols':
            from engines.ols_modeler import train_ols as _train
        else:
            from engines.modeler import train_model as _train

        def progress_callback(info: dict):
            with _training_lock:
                task = _training_tasks.get(task_id)
                if task:
                    task['phase'] = info.get('phase', task['phase'])
                    task['pct'] = info.get('pct', task['pct'])
                    task['elapsed_sec'] = round(time.time() - task['started_at'], 1)

        try:
            result = _train(config, project_dir, progress_callback=progress_callback)
            with _training_lock:
                task = _training_tasks.get(task_id)
                if task:
                    task['status'] = 'done' if result.get('status') == 'ok' else 'error'
                    task['pct'] = 100
                    task['elapsed_sec'] = round(time.time() - task['started_at'], 1)
                    task['result'] = result
                    task['error'] = result.get('message') if result.get('status') == 'error' else None
        except Exception as e:
            logger.exception('Async training failed')
            with _training_lock:
                task = _training_tasks.get(task_id)
                if task:
                    task['status'] = 'error'
                    task['error'] = str(e)

    threading.Thread(target=run, daemon=True).start()
    return {'task_id': task_id, 'status': 'running'}


@app.get('/compute/train/progress')
def train_progress():
    """Get current training progress (latest task)."""
    with _training_lock:
        if not _training_tasks:
            return {'status': 'idle', 'pct': 0}
        # Return the most recently started task
        task_id = max(_training_tasks, key=lambda k: _training_tasks[k]['started_at'])
        task = _training_tasks[task_id].copy()
        task['elapsed_sec'] = round(time.time() - task['started_at'], 1)
    return {'task_id': task_id, **{k: v for k, v in task.items() if k not in ('result', 'started_at')}}


@app.post('/compute/train/cancel/{task_id}')
def train_cancel(task_id: str):
    """Mark training task as cancelled. MCMC thread finishes in background but result discarded."""
    with _training_lock:
        task = _training_tasks.get(task_id)
        if not task:
            return {'status': 'not_found'}
        if task['status'] == 'running':
            task['status'] = 'cancelled'
            task['error'] = 'Обучение остановлено пользователем'
        return {'status': task['status'], 'task_id': task_id}


@app.get('/compute/train/result/{task_id}')
def train_result(task_id: str):
    """Get training result. C3: cleans up task after consumption."""
    with _training_lock:
        task = _training_tasks.get(task_id)
        if not task:
            return {'status': 'not_found'}
        if task['status'] in ('done', 'error'):
            result = task.get('result') or {'status': 'error', 'message': task.get('error', 'Unknown error')}
            task['consumed_at'] = time.time()  # Mark consumed, keep for retries
            # F-MC-1: NaN-safe ответ (см. /compute/train).
            from utils.safe_io import sanitize_nonfinite
            return sanitize_nonfinite(result)
    return {'status': 'pending'}


@app.post('/compute/decompose')
def decompose_sales(req: DecomposeRequest):
    """Decompose sales into baseline + channel contributions."""
    from engines.decomposer import decompose as _decompose
    from pathlib import Path as _Path
    pickle_exists = (_Path(req.project_dir) / 'models' / 'latest.pkl').exists()
    logger.info(f'/compute/decompose project_dir={req.project_dir} pickle_exists={pickle_exists}')
    result = _decompose(
        req.project_dir,
        unit_costs_override=req.unit_costs,
        unit_cost_inflation_pct=req.unit_cost_inflation_pct,
        kpi_unit_cost_override=req.kpi_unit_cost,
    )
    if result.get('status') != 'ok':
        logger.warning(f'/compute/decompose returned error: {result.get("message")}')
    # F-MC-1: NaN-safe ответ (файл decomposition.json уже санитайзился, ответ — нет).
    from utils.safe_io import sanitize_nonfinite
    return JSONResponse(content=sanitize_nonfinite(result))


@app.post('/compute/optimize')
def optimize_budget(req: OptimizeRequest):
    """Optimize budget allocation across channels."""
    # L9 (math-fix v1.4 Section C, 2026-04-29): explicit reject 'free' mode
    # until v1.1 implementation. UI checkbox disabled with tooltip - but if
    # caller bypasses UI (direct API), error message points к v1.1 plan.
    if req.budget_mode != 'fixed':
        return JSONResponse(content={
            'status': 'error',
            'error_code': 'BUDGET_MODE_NOT_IMPLEMENTED',
            'message': (
                f"budget_mode='{req.budget_mode}' пока не реализован. "
                f"Доступен только budget_mode='fixed'. Free-budget mode "
                f"запланирован в v1.1 (см. roadmap)."
            ),
        }, status_code=400)
    from engines.optimizer import optimize as _optimize
    config = {
        'total_budget': req.total_budget,
        'total_budget_money': req.total_budget_money,
        'min_pct': req.min_pct,
        'max_pct': req.max_pct,
        'min_per_channel': req.min_per_channel,
        'max_per_channel': req.max_per_channel,
        # D.3 per-group passthrough (None → optimizer falls back к global).
        'brand_min_pct': req.brand_min_pct,
        'brand_max_pct': req.brand_max_pct,
        'perf_min_pct': req.perf_min_pct,
        'perf_max_pct': req.perf_max_pct,
        'unit_costs': req.unit_costs,  # None → decomposer fallback на pickle config
        # Phase 2 - None preserves analyst mode byte-exact (verified 162/162 tests).
        'forecast_periods': req.forecast_periods,
        'forecast_period_label': req.forecast_period_label,
        'unit_cost_inflation_pct': req.unit_cost_inflation_pct,
        # v2.1.0 (ADR-021): override kpi_unit_cost из UI для money lift conversion.
        'kpi_unit_cost': req.kpi_unit_cost,
    }
    result = _optimize(config, req.project_dir)
    return JSONResponse(content=result)


# ─── Phase 2 (Planning Mode) - preview endpoints ──────────────────────────


class ForecastContextRequest(BaseModel):
    """Preview helper для frontend ForecastHorizonPicker.

    Returns granularity + seasonality + per-channel calibration zones (x_norm
    quantiles) detected/persisted in pickle. Used to populate smart suggestions
    before customer commits к full optimize call.
    """
    project_dir: str


@app.post('/compute/forecast-context')
def forecast_context(req: ForecastContextRequest):
    """Phase 2 preview - granularity + seasonality + calibration zones."""
    from pathlib import Path
    from engines.persistence import (
        get_seasonality, get_training_granularity,
        infer_x_norm_quantiles_at_load, load_model_with_compat,
    )
    project_path = Path(req.project_dir)
    model_path = project_path / 'models' / 'latest.pkl'
    if not model_path.exists():
        return JSONResponse(content={
            'status': 'error',
            'error_code': 'MODEL_NOT_FOUND',
            'message': 'Модель не обучена - обучите MMM перед planning mode.',
        }, status_code=400)
    model_data = load_model_with_compat(model_path)
    granularity = get_training_granularity(model_data)
    seasonality = get_seasonality(model_data)
    media_cols = (model_data.get('config') or {}).get('media_columns') or []
    # Audit pass 3 fix (BUG 11): N² regression. Per-channel get_x_norm_quantiles
    # recomputed adstock for ALL channels per call → 5 channels = 25 adstock comps.
    # Pre-compute once: persisted dict if available, else single inference pass.
    persisted_quantiles = model_data.get('train_x_norm_quantiles') or {}
    if persisted_quantiles and all(col in persisted_quantiles for col in media_cols):
        quantiles = {col: persisted_quantiles[col] for col in media_cols}
    else:
        # Legacy pickle (or partial) - single inference pass for all channels
        inferred = infer_x_norm_quantiles_at_load(model_data) or {}
        quantiles = {col: persisted_quantiles.get(col) or inferred.get(col) for col in media_cols}
    train_n = len(model_data.get('y_actual') or [])
    # Phase 2 (audit pass 4 - Антон 2026-05-02): multi-year detection. При денежной
    # оценке любого медиа важно учесть, что данные могут быть приведены за
    # несколько лет - стоимость единицы может значительно отличаться год от года
    # (медиаинфляция 25-30%). Бэкенд возвращает год-range info для UI prep;
    # full per-year unit_costs editing → Phase 2.5.
    training_year_ranges = _detect_training_year_ranges(model_data)
    return JSONResponse(content={
        'status': 'ok',
        'training_granularity': granularity,
        'seasonality_detected': seasonality,
        'train_n_periods': train_n,
        'train_x_norm_quantiles': quantiles,
        # S7 - KPI-aware horizon caps (sales 2.0× / awareness 1.5× и т.п.)
        'forecast_horizon_max_multiplier': _kpi_aware_max_multiplier(model_data),
        'forecast_horizon_warn_multiplier': _kpi_aware_warn_multiplier(model_data),
        # Multi-year structural data - UI uses для inflation disclosure
        'training_year_ranges': training_year_ranges,
    })


def _detect_training_year_ranges(model_data: dict) -> list[dict] | None:
    """Return per-year breakdown of training data, или None if unable.

    Phase 2 audit pass 4 - Антон's требование: при денежной оценке учесть, что
    данные могут быть за несколько лет. UI prep: surface это customer'у.

    Returns:
        [{'year': 2024, 'n_periods': 52, 'start_date': '2024-01-01',
          'end_date': '2024-12-31'}, ...] or None.
    """
    config = model_data.get('config') or {}
    data_file = config.get('data_file')
    date_col = config.get('date_column', 'date')
    if not data_file:
        return None
    try:
        import pandas as pd
        df = pd.read_excel(data_file) if str(data_file).endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)
        if date_col not in df.columns:
            return None
        dates = pd.to_datetime(df[date_col], errors='coerce').dropna()
        if dates.empty:
            return None
        groups = dates.groupby(dates.dt.year)
        ranges = []
        for year, group in groups:
            ranges.append({
                'year': int(year),
                'n_periods': int(len(group)),
                'start_date': group.min().strftime('%Y-%m-%d'),
                'end_date': group.max().strftime('%Y-%m-%d'),
            })
        return ranges
    except Exception:
        return None


def _kpi_aware_max_multiplier(model_data: dict) -> float:
    """S7 - read kpi_registry forecast_horizon_max_multiplier для pickle's KPI."""
    from engines.persistence import get_kpi_type
    from utils.forecast_validation import get_forecast_horizon_max_multiplier
    return get_forecast_horizon_max_multiplier(get_kpi_type(model_data))


def _kpi_aware_warn_multiplier(model_data: dict) -> float:
    """S7 - read kpi_registry forecast_horizon_warn_multiplier для pickle's KPI."""
    from engines.persistence import get_kpi_type
    try:
        from utils.kpi_registry import get_kpi_config
        cfg = get_kpi_config(get_kpi_type(model_data))
        return float(getattr(cfg, 'forecast_horizon_warn_multiplier', 1.5))
    except Exception:
        return 1.5


class ForecastScalingRequest(BaseModel):
    """Preview ratio + warnings без full optimize.

    Used by frontend для quick «what-if» feedback when customer adjusts
    forecast_periods / forecast_budget - emits drift warnings + horizon
    extrapolation status БЕЗ запуска SLSQP (~12ms vs ~3s full optimize).
    """
    project_dir: str
    forecast_periods: int
    forecast_budget_money: float | None = None  # None → use training current total


@app.post('/compute/forecast-scaling')
def forecast_scaling_preview(req: ForecastScalingRequest):
    """Phase 2 preview - drift checks + horizon warnings без full optimize."""
    from pathlib import Path
    from engines.persistence import (
        get_kpi_type, get_x_norm_quantiles, load_model_with_compat,
    )
    from utils.forecast_validation import (
        get_forecast_horizon_max_multiplier,
        horizon_extrapolation_check,
        resolve_warning_priority,
        saturation_drift_check,
    )

    project_path = Path(req.project_dir)
    model_path = project_path / 'models' / 'latest.pkl'
    if not model_path.exists():
        return JSONResponse(content={
            'status': 'error',
            'error_code': 'MODEL_NOT_FOUND',
            'message': 'Модель не обучена.',
        }, status_code=400)

    model_data = load_model_with_compat(model_path)
    train_n = len(model_data.get('y_actual') or [])
    if train_n < 1:
        return JSONResponse(content={
            'status': 'error',
            'error_code': 'INVALID_TRAIN_DATA',
            'message': 'Обучающие данные пусты - preview невозможен.',
        }, status_code=400)

    # Validate forecast_periods (mirror optimizer.py:329+ rules).
    forecast_n = int(req.forecast_periods)
    if forecast_n < 1:
        return JSONResponse(content={
            'status': 'error',
            'error_code': 'INVALID_FORECAST_PERIODS',
            'message': 'forecast_periods должно быть ≥ 1.',
        }, status_code=400)

    kpi_type = get_kpi_type(model_data)
    max_mult = get_forecast_horizon_max_multiplier(kpi_type)
    if forecast_n > train_n * max_mult:
        return JSONResponse(content={
            'status': 'error',
            'error_code': 'FORECAST_HORIZON_TOO_LONG',
            'message': (
                f'Период планирования ({forecast_n}) превышает {max_mult:.1f}× обучающего '
                f'горизонта ({int(train_n * max_mult)}). Допущение стационарности нарушено.'
            ),
        }, status_code=400)

    warnings: list[dict] = []
    horizon_warn = horizon_extrapolation_check(
        forecast_n, train_n,
        warn_factor=_kpi_aware_warn_multiplier(model_data),
    )
    if horizon_warn:
        warnings.append(horizon_warn)

    # Drift detection per channel - needs forecast per-period spend per channel.
    # Use proportional split of forecast_budget_money matching training proportions.
    media_cols = (model_data.get('config') or {}).get('media_columns') or []
    channel_params = model_data.get('channel_params') or {}
    norm = model_data.get('normalization') or {}
    media_means = norm.get('media_means', {}) or {}

    per_channel_drift: dict[str, dict] = {}
    if req.forecast_budget_money is not None and req.forecast_budget_money > 0 and media_cols:
        # Read training spend totals to derive proportions
        try:
            import pandas as pd
            data_file = (model_data.get('config') or {}).get('data_file')
            if data_file:
                df = pd.read_excel(data_file) if str(data_file).endswith(('.xlsx', '.xls')) else pd.read_csv(data_file)
                from utils.merge_rules import apply_merge_rules
                apply_merge_rules(df, (model_data.get('config') or {}).get('merge_rules'))
                training_totals = {col: float(df[col].fillna(0).sum()) for col in media_cols if col in df.columns}
                training_total_sum = sum(training_totals.values())
                if training_total_sum > 0:
                    for col in media_cols:
                        share = training_totals.get(col, 0) / training_total_sum
                        forecast_total = float(req.forecast_budget_money) * share
                        forecast_per_period = forecast_total / forecast_n
                        train_avg = (training_totals.get(col, 0) / train_n) if train_n else 0
                        drift = saturation_drift_check(
                            forecast_per_period_spend=forecast_per_period,
                            train_avg_spend=train_avg,
                        )
                        if drift:
                            drift['channel'] = col
                            per_channel_drift[col] = drift
                            warnings.append({**drift, 'message_ru': drift['message_ru']})
        except Exception:
            pass  # Drift detection optional - failure не блокирует preview

    composed = resolve_warning_priority(warnings)
    return JSONResponse(content={
        'status': 'ok',
        'forecast_n_periods': forecast_n,
        'train_n_periods': train_n,
        'horizon_ratio': forecast_n / train_n,
        'horizon_max_multiplier': max_mult,
        'per_channel_drift': per_channel_drift,
        'top_warning': composed['top_warning'],
        'secondary_warnings': composed['secondary'],
        'warnings_total': composed['total_count'],
    })


class HierarchicalWarningRequest(BaseModel):
    """L5 (Phase 2.0 Part 2) - surface hierarchical β-pooling extrapolation warning.

    Customer post-optimize check: при planning_budget > 3× training, brand-channel
    estimates may underestimate top-performer на 5-15%. Endpoint reads pickle +
    training totals и calls helper. Returns {status, warning|null}. Frontend shows
    panel когда warning != null.

    `train_total_money` (optional) - bypass backend pickle sum. Frontend uses
    decompose channels.spend total для consistency с tem что customer видит в
    Block A («Текущий бюджет»). Иначе backend считает sum по media_cols, что
    может расходиться с visual currentBudget после apply_merge_rules / filter.
    """
    project_dir: str
    forecast_budget_money: float
    train_total_money: float | None = None


@app.post('/compute/hierarchical-warning')
def hierarchical_warning_endpoint(req: HierarchicalWarningRequest):
    """L5 - non-blocking advisory check для customer planning workflow."""
    from pathlib import Path
    from engines.persistence import load_model_with_compat
    from utils.forecast_validation import hierarchical_extrapolation_warning

    project_path = Path(req.project_dir)
    model_path = project_path / 'models' / 'latest.pkl'
    if not model_path.exists():
        return JSONResponse(content={
            'status': 'error',
            'error_code': 'MODEL_NOT_FOUND',
            'message': 'Модель не обучена.',
        }, status_code=400)

    model_data = load_model_with_compat(model_path)

    # FIX 2026-05-04: train_total_money теперь приходит от frontend (=decompose
    # channels.spend total). Backend pickle sum через media_cols мог давать
    # subset (только brand после merge_rules) → ratio несогласованный с UI
    # currentBudget. Fallback к pickle sum если frontend не прислал.
    if req.train_total_money is not None and req.train_total_money > 0:
        train_total_money = float(req.train_total_money)
    else:
        train_total_money = 0.0
        media_cols = (model_data.get('config') or {}).get('media_columns') or []
        data_file = (model_data.get('config') or {}).get('data_file')
        if data_file and media_cols:
            try:
                import pandas as pd
                df = (
                    pd.read_excel(data_file)
                    if str(data_file).endswith(('.xlsx', '.xls'))
                    else pd.read_csv(data_file)
                )
                from utils.merge_rules import apply_merge_rules
                apply_merge_rules(df, (model_data.get('config') or {}).get('merge_rules'))
                train_total_money = float(sum(
                    df[col].fillna(0).sum() for col in media_cols if col in df.columns
                ))
            except Exception:
                pass  # train_total_money=0 → helper returns None gracefully

    warning = hierarchical_extrapolation_warning(
        model_data,
        forecast_budget_money=float(req.forecast_budget_money),
        train_total_money=train_total_money,
    )
    return JSONResponse(content={
        'status': 'ok',
        'warning': warning,
        'train_total_money': train_total_money,
    })


@app.post('/compute/scenario')
def predict_scenario(req: ScenarioRequest):
    """Predict KPI for a media plan scenario."""
    from engines.scenario import predict_scenario as _predict
    config = req.model_dump()
    project_dir = config.pop('project_dir')
    result = _predict(config, project_dir)
    return JSONResponse(content=result)


class CompareRequest(BaseModel):
    project_dir: str
    unit_costs: dict[str, float] | None = None


@app.post('/compute/compare')
def compare_scenarios(req: CompareRequest):
    """Compare all saved scenarios side-by-side. unit_costs used for legacy migration."""
    from engines.scenario import compare_scenarios as _compare
    result = _compare(req.project_dir, req.unit_costs)
    return JSONResponse(content=result)


class ScenarioDeleteRequest(BaseModel):
    project_dir: str
    scenario_name: str


@app.post('/compute/scenario/delete')
def delete_scenario(req: ScenarioDeleteRequest):
    """Delete a saved scenario JSON file."""
    from engines.scenario import delete_scenario as _delete
    result = _delete(req.project_dir, req.scenario_name)
    return JSONResponse(content=result)


# ──────────────────────────────────────────────────────────────────
# Planning mode: шаблон медиаплана + подтверждение
# ──────────────────────────────────────────────────────────────────


class MediaPlanTemplateRequest(BaseModel):
    project_dir: str
    n_future_periods: int = Field(default=12, ge=1, le=120)


@app.post('/compute/media-plan-template')
def media_plan_template_endpoint(req: MediaPlanTemplateRequest):
    """Генерирует Excel-шаблон медиаплана: история + N пустых строк будущего.

    Читает модель из models/latest.pkl, исходный файл из data_file модели,
    строит xlsx с продолженными датами и пустыми медиа/KPI колонками.
    Возвращает {status, path} или {status: 'error', message}.
    """
    from engines.planning import generate_media_plan_template
    try:
        result = generate_media_plan_template(req.project_dir, req.n_future_periods)
        return JSONResponse(content=result)
    except Exception as e:
        logger.exception('media_plan_template: ошибка')
        return JSONResponse(content={'status': 'error', 'message': _friendly_error(e)})


class ConfirmMediaPlanRequest(BaseModel):
    project_dir: str
    confirmed: bool


@app.post('/compute/confirm-media-plan')
def confirm_media_plan_endpoint(req: ConfirmMediaPlanRequest):
    """Устанавливает поле confirmed в results/media_plan.json.

    При confirmed=True — медиаплан принят, False — отклонён.
    Возвращает {status: 'ok'} или {status: 'error', message}.
    """
    from engines.planning import confirm_media_plan
    try:
        result = confirm_media_plan(req.project_dir, req.confirmed)
        return JSONResponse(content=result)
    except Exception as e:
        logger.exception('confirm_media_plan: ошибка')
        return JSONResponse(content={'status': 'error', 'message': _friendly_error(e)})


# ──────────────────────────────────────────────────────────────────
# Sprint 3 Pharma Causal - endpoints (M1 ship)
# ──────────────────────────────────────────────────────────────────


@app.post('/compute/causal/preflight')
def causal_preflight_endpoint(req: CausalPreflightRequest):
    """Sprint 3 M4: Unified pre-causal validation + method recommendation.

    Returns: applicable methods (DiD/SCM/Forest), per-method validation
    breakdown, recommended order, common caveats. Analogous к existing
    /compute/preflight для MMM training.
    """
    from engines.causal.preflight import causal_preflight
    cfg = req.model_dump()
    file_path = cfg.pop('file_path')
    result = causal_preflight(file_path, **cfg)
    return JSONResponse(content=result)


@app.post('/compute/causal/list')
def causal_list_endpoint(req: CausalListRequest):
    """Sprint 3 M4: List causal artifacts в project.

    Returns artifacts sorted by created_at desc with method, ATT, CI summary.
    UI uses for history view + cross-method comparison.
    """
    from engines.causal.preflight import list_causal_artifacts
    return JSONResponse(content=list_causal_artifacts(req.project_dir))


@app.post('/compute/causal/consistency')
def causal_consistency_endpoint(req: CausalConsistencyRequest):
    """Sprint 3 M4: Cross-method consistency check.

    Compares latest ATT estimates across DiD/SCM/Forest для same project.
    Triangulation: methods should agree (CI overlap, low divergence). Significant
    disagreement signals identification problem.
    """
    from engines.causal.preflight import cross_method_consistency
    return JSONResponse(content=cross_method_consistency(req.project_dir))


@app.post('/compute/causal/forest')
def causal_forest(req: CausalForestRequest):
    """Sprint 3 M3: Causal Forest для HTE estimation.

    Returns ATE с honest-split CI + heterogeneity diagnostics + feature
    importance. Surfaces в каких сегментах (по features) treatment effect
    сильнее. Honest disclosure: CIA, overlap, SUTVA assumptions.

    See docs/SPRINT3_PHARMA_CAUSAL_ADR.md §4 для request/response schema.
    """
    from engines.causal.causal_forest import estimate_causal_forest
    cfg = req.model_dump()
    project_dir = cfg.pop('project_dir')
    file_path = cfg.pop('data_file')
    result = estimate_causal_forest(file_path, project_dir=project_dir, **cfg)
    return JSONResponse(content=result)


@app.post('/compute/causal/scm')
def causal_scm(req: CausalSCMRequest):
    """Sprint 3 M2: Synthetic Control Method (Abadie classic) ATT estimation.

    Returns ATT с placebo-permutation CI + honest_disclosure (convex-hull,
    pre-treatment RMSE quality, donor weight concentration HHI).

    Per ADR §3.1 + Q2(B): manual scipy SLSQP via _solve_scm_weights() interface
    - clean swap path к cvxpy (Augmented SCM, Sprint 4+).

    See docs/SPRINT3_PHARMA_CAUSAL_ADR.md §4 для request/response schema.
    """
    from engines.causal.scm import estimate_scm
    cfg = req.model_dump()
    project_dir = cfg.pop('project_dir')
    file_path = cfg.pop('data_file')
    result = estimate_scm(file_path, project_dir=project_dir, **cfg)
    return JSONResponse(content=result)


@app.post('/compute/causal/did')
def causal_did(req: CausalDiDRequest):
    """Sprint 3 M1: Difference-in-Differences (TWFE) ATT estimation.

    Returns ATT с frequentist cluster-robust CI + honest_disclosure (parallel-
    trends test, staggered detection per Goodman-Bacon 2021, SUTVA assumption).

    For staggered adoption treatment timing, returns ATT с warning flag in
    diagnostics_failed - consider Sprint 4+ Callaway-Santanna для proper estimator.

    See docs/SPRINT3_PHARMA_CAUSAL_ADR.md §4 для request/response schema.
    """
    from engines.causal.did import estimate_did
    cfg = req.model_dump()
    project_dir = cfg.pop('project_dir')
    file_path = cfg.pop('data_file')
    result = estimate_did(file_path, project_dir=project_dir, **cfg)
    return JSONResponse(content=result)


@app.post('/compute/awareness/forecast')
def awareness_forecast(req: AwarenessRequest):
    """Forecast brand awareness."""
    from engines.awareness import forecast_awareness as _forecast
    config = req.model_dump()
    project_dir = config.pop('project_dir')
    result = _forecast(config, project_dir)
    return JSONResponse(content=result)


@app.post('/compute/awareness/sales')
def awareness_to_sales(req: AwarenessSalesRequest):
    """Model awareness → sales S-curve."""
    from engines.awareness import awareness_to_sales as _a2s
    config = req.model_dump()
    project_dir = config.pop('project_dir')
    result = _a2s(config, project_dir)
    return JSONResponse(content=result)


# ── Chart endpoints ──────────────────────────────────

@app.post('/chart')
def generate_chart(req: ChartRequest):
    """Generate matplotlib chart as base64 PNG.

    chart_type: 'waterfall', 'response_curves', 'awareness', 's_curve', 'mqs'
    """
    from charts.generators import (
        waterfall_chart, response_curves_chart, awareness_chart, s_curve_chart, mqs_gauge,
    )

    project_path = Path(req.project_dir)
    results_dir = project_path / 'results'

    try:
        if req.chart_type == 'waterfall':
            with open(results_dir / 'decomposition.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
            png = waterfall_chart(data['waterfall'])

        elif req.chart_type == 'response_curves':
            with open(results_dir / 'optimization.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
            png = response_curves_chart(data['response_curves'])

        elif req.chart_type == 'awareness':
            with open(results_dir / 'awareness-forecast.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
            png = awareness_chart(data['historical'], data['forecast'],
                                  data['ci_lower'], data['ci_upper'])

        elif req.chart_type == 's_curve':
            with open(results_dir / 'awareness-to-sales.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
            png = s_curve_chart(data['curve_data'])

        elif req.chart_type == 'mqs':
            with open(results_dir / 'model-diagnostics.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
            mqs = data['mqs']
            png = mqs_gauge(mqs['score'], mqs['tier_label'], mqs['color'])

        else:
            raise HTTPException(status_code=400, detail=f'Unknown chart type: {req.chart_type}')

        return {'status': 'ok', 'chart': png, 'chart_type': req.chart_type}

    except FileNotFoundError:
        return {'status': 'error', 'message': f'Результаты для {req.chart_type} не найдены. Сначала выполните соответствующий расчёт'}
    except Exception as e:
        logger.exception(f'Chart generation failed: {req.chart_type}')
        return {'status': 'error', 'message': _friendly_error(e)}


# ── Adstock Auto-Select ──────────────────────────────────

@app.post('/compute/adstock_select')
def adstock_select(req: AdstockSelectRequest):
    """Auto-select best adstock type per channel using BIC comparison."""
    from engines.adstock_selector import select_adstock
    result = select_adstock(req.file_path, req.kpi_column, req.media_columns, req.date_column)
    return JSONResponse(content=result)


# ── Model History ────────────────────────────────────────

@app.post('/compute/model_history')
def model_history(req: ModelHistoryRequest):
    """List archived model versions with summary diagnostics."""
    history_dir = Path(req.project_dir) / 'models' / 'history'
    if not history_dir.exists():
        return {'status': 'ok', 'versions': []}

    versions = []
    for params_file in sorted(history_dir.glob('params-*.json'), reverse=True):
        try:
            with open(params_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            ts_str = params_file.stem.replace('params-', '')
            diag = data.get('diagnostics', {}) or {}
            mqs = diag.get('mqs', {}) or {}
            metrics = diag.get('metrics', {}) or {}
            channels = list(data.get('channel_params', {}).keys())
            versions.append({
                'timestamp': ts_str,
                'mqs_score': mqs.get('score', 0),
                'mqs_label': mqs.get('tier_label', ''),
                'r_squared': metrics.get('r_squared', diag.get('r_squared', 0)),
                'mape': metrics.get('mape_pct', diag.get('mape', 0)),
                'n_channels': len(channels),
                'channels': channels,
                'config': data.get('config', {}),
            })
        except Exception:
            continue

    return {'status': 'ok', 'versions': versions}


# ── Path traversal guard (H-01) ──────────────────────────

def _get_projects_roots() -> list[Path]:
    """Canonical projects roots for path validation (H-01).

    Returns LIST потому что валидный путь может быть под одним из нескольких
    roots (зависит от installation / Tauri config / pilot env). Mirror Rust
    `projects_dir()` priority chain (src-tauri/src/commands/project.rs):

    1. `AURORA_PROJECTS_ROOT` env var override (tests / advanced users)
    2. `user_config.json::econometrica_projects_root` override (user-set)
    3. Default: `APPDATA/aurora-econometrica-gui/projects` (matches Rust
       `env::var("APPDATA")` — это Roaming на Windows)
    4. Fallback: `LOCALAPPDATA/aurora-econometrica-gui/projects` (legacy
       installs / RDP environments)
    5. Dev: `<repo>/sidecar/econometrica/projects`

    Pilot 2026-05-15 выявил bug — раньше returned ТОЛЬКО LOCALAPPDATA на
    Windows (or APPDATA fallback), а Rust пишет в APPDATA Roaming → guard
    rejected все legitimate projects как traversal.
    """
    roots: list[Path] = []

    # 1. Env override (highest priority)
    env_root = os.environ.get('AURORA_PROJECTS_ROOT', '').strip()
    if env_root:
        roots.append(Path(env_root).resolve())

    # 2. user_config.json override (read same as Rust)
    appdata = os.environ.get('APPDATA', '')
    if appdata:
        config_path = Path(appdata) / 'aurora-econometrica-gui' / 'user_config.json'
        if config_path.exists():
            try:
                with open(config_path, encoding='utf-8') as f:
                    cfg = json.load(f)
                cfg_root = cfg.get('econometrica_projects_root', '')
                if isinstance(cfg_root, str) and cfg_root.strip():
                    roots.append(Path(cfg_root.strip()).resolve())
            except (OSError, json.JSONDecodeError):
                pass

    # 3. APPDATA Roaming default (matches Rust CARGO_PKG_NAME identifier)
    if appdata:
        roots.append((Path(appdata) / 'aurora-econometrica-gui' / 'projects').resolve())

    # 4. LOCALAPPDATA fallback (some installs / RDP)
    localappdata = os.environ.get('LOCALAPPDATA', '')
    if localappdata and localappdata != appdata:
        roots.append((Path(localappdata) / 'aurora-econometrica-gui' / 'projects').resolve())

    # 5. Dev fallback — `_sidecar_root` is a str (module-level constant),
    # wrap в Path первым чтобы избежать str/str TypeError.
    roots.append((Path(_sidecar_root) / 'projects').resolve())

    return roots


def _assert_project_dir_safe(project_dir: str | Path) -> Path:
    """H-01: validate project_dir is inside one of expected projects roots.

    Защита от path traversal — `project_dir` приходит из webview JS, который
    может быть скомпрометирован через XSS or malformed import. Без guard'a
    malicious payload (`../../etc/passwd`, `C:/Windows/System32`) может
    triggernut atomic_write_json на arbitrary disk locations.

    Accepts path если under ЛЮБОГО из allowed roots (env / user_config /
    APPDATA / LOCALAPPDATA / dev). Mismatch между Python и Rust roots
    был обнаружен pilot 2026-05-15.

    Raises HTTPException 400 если path вне любого root.
    Returns resolved absolute Path.
    """
    from fastapi import HTTPException
    try:
        p = Path(project_dir).resolve(strict=False)
    except (OSError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=f'invalid project_dir: {e}') from e
    roots = _get_projects_roots()
    for root in roots:
        try:
            p.relative_to(root)
            return p  # match — under this root, safe.
        except ValueError:
            continue
    # No root matched.
    roots_str = ', '.join(str(r) for r in roots)
    raise HTTPException(
        status_code=400,
        detail=(
            f'project_dir outside expected projects roots '
            f'({p} not under any of: {roots_str}). Path traversal blocked.'
        ),
    )


# ── PPTX Export ──────────────────────────────────────────

def _resolve_project_dir(project_dir: str | None, project_id: str) -> Path:
    """Вычислить путь к project_dir с учётом Settings override.

    Приоритет:
      1. Явно переданный project_dir (из Rust с учётом Settings override)
      2. Fallback на %APPDATA%\\<identifier>\\projects\\<project_id>\\ для
         обратной совместимости со старыми клиентами Rust.

    NB: для endpoint-level path traversal guards используйте отдельный
    `_assert_project_dir_safe()` (audit H-01).
    """
    if project_dir:
        return Path(project_dir)
    appdata = os.environ.get('APPDATA', '')
    identifier = 'aurora-econometrica-gui'
    return Path(appdata) / identifier / 'projects' / project_id


def _assert_decompose_present(decompose_data: dict, allow_wireframe: bool) -> None:
    """INV-50 NEW-2: гейт честности экспорта.

    Правило: пустой decompose_data без явного allow_wireframe=True —
    это клиентский запрос без реальных результатов декомпозиции.
    Тихо строить wireframe-документ с ВЫДУМАННЫМИ числами (builder-дефолты:
    TRP, mROAS 1.9×, 22%) и отдавать его как результат — нарушение INV-50
    (честность метрик) и API-гигиены.

    Контракт:
      - has_decomp=False, allow_wireframe=False → HTTPException 400
      - has_decomp=False, allow_wireframe=True  → pass (dev wireframe)
      - has_decomp=True,  любой флаг            → pass (live данные)
    """
    has_decomp = bool(decompose_data)
    if not has_decomp and not allow_wireframe:
        raise HTTPException(
            status_code=400,
            detail=(
                'Экспорт без результатов декомпозиции невозможен. '
                'Для каркасного превью (dev) передайте allow_wireframe=true — '
                'документ будет содержать ДЕМОНСТРАЦИОННЫЕ числа.'
            ),
        )


@app.post('/export/pptx')
def export_pptx(req: PptxExportRequest):
    """Generate branded PPTX presentation from MMM results."""
    logger.info(f'PPTX export START project_id={req.project_id}')
    # INV-50 NEW-2: гейт до любых тяжёлых операций (создание директорий,
    # чтение с диска). HTTPException пробрасывается напрямую FastAPI → 400.
    _assert_decompose_present(req.decompose_data, req.allow_wireframe)
    try:
        from engines.pptx_export import build_pptx

        project_path = _resolve_project_dir(req.project_dir, req.project_id)
        exports_dir = project_path / 'exports'
        exports_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = str(exports_dir / f'mmm_report_{ts}.pptx')
        logger.info(f'PPTX output path: {output_path}')

        has_model = bool(req.model_data)
        has_decomp = bool(req.decompose_data)
        has_optim = bool(req.optimize_data)

        # Сценарии - читаем с диска (Frontend их не передаёт, они - артефакт шага Optimize).
        scenarios_dir = project_path / 'results' / 'scenarios'
        scenarios: list[dict] = []
        if scenarios_dir.exists():
            for f in sorted(scenarios_dir.glob('*.json')):
                try:
                    with open(f, 'r', encoding='utf-8') as fh:
                        scenarios.append(json.load(fh))
                except Exception:
                    continue
        # E1 (2026-07-03): backtest-витрина с диска (артефакт кнопки «Проверить
        # модель на истории») — как и сценарии, frontend её не передаёт.
        from engines.backtest import load_saved_backtest
        backtest = load_saved_backtest(str(project_path))
        # E3 (2026-07-03): сравнение поколений — тем же путём с диска.
        from engines.model_compare import load_saved_generation_compare
        generation_compare = load_saved_generation_compare(str(project_path))
        # E4 (2026-07-03): зафиксированные прогнозы-обещания (для строк
        # «сбылось/не сбылось» в отчёте).
        from engines.promises import list_promises
        promises = (list_promises(str(project_path)) or {}).get('promises') or []
        # E5 (2026-07-10): прогноз-план (results/planning.json + сценарии).
        from engines.planning import load_saved_forecast
        forecast = load_saved_forecast(str(project_path))

        logger.info(
            f'PPTX inputs: model={has_model} decompose={has_decomp} '
            f'optimize={has_optim} scenarios={len(scenarios)} '
            f'backtest={"yes" if backtest else "no"} '
            f'gen_compare={"yes" if generation_compare else "no"} '
            f'forecast={"yes" if forecast else "no"}'
        )

        result = build_pptx(
            req.model_data, req.decompose_data, req.optimize_data,
            output_path, scenarios=scenarios, project_id=req.project_id,
            backtest=backtest, generation_compare=generation_compare,
            promises=promises, forecast=forecast,
        )
        logger.info(f'PPTX export OK: {result}')
        return JSONResponse(content=result)
    except Exception as e:
        logger.exception('PPTX export FAILED')
        return JSONResponse(
            status_code=500,
            content={
                'status': 'error',
                'message': _friendly_error(e),
                'type': type(e).__name__,
            },
        )


@app.post('/export/html')
def export_html(req: HtmlExportRequest):
    """Generate interactive standalone HTML report."""
    logger.info(f'HTML export START project_id={req.project_id}')
    # INV-50 NEW-2: тот же класс проблемы что и /export/pptx — тихая фикция
    # при пустом decompose_data. Гейт симметричен PPTX.
    _assert_decompose_present(req.decompose_data, req.allow_wireframe)
    try:
        from engines.html_export import build_html

        project_path = _resolve_project_dir(req.project_dir, req.project_id)
        exports_dir = project_path / 'exports'
        exports_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = str(exports_dir / f'mmm_report_{ts}.html')
        logger.info(f'HTML output path: {output_path}')

        # Сценарии с диска (как в PPTX)
        scenarios_dir = project_path / 'results' / 'scenarios'
        scenarios: list[dict] = []
        if scenarios_dir.exists():
            for f in sorted(scenarios_dir.glob('*.json')):
                try:
                    with open(f, 'r', encoding='utf-8') as fh:
                        scenarios.append(json.load(fh))
                except Exception:
                    continue

        # Inject project_dir hint so html_export can load full model pickle
        # for budget what-if slider (Hill params + normalization).
        decompose_for_build = dict(req.decompose_data or {})
        decompose_for_build.setdefault('project_dir', str(project_path))

        # E1-E4 (2026-07-04): артефакты петли доверия с диска — как в PPTX.
        from engines.backtest import load_saved_backtest
        from engines.model_compare import load_saved_generation_compare
        from engines.promises import list_promises
        backtest = load_saved_backtest(str(project_path))
        generation_compare = load_saved_generation_compare(str(project_path))
        promises = (list_promises(str(project_path)) or {}).get('promises') or []
        # E5 (2026-07-10): прогноз-план.
        from engines.planning import load_saved_forecast
        forecast = load_saved_forecast(str(project_path))

        result = build_html(
            req.model_data, decompose_for_build, req.optimize_data, output_path,
            scenarios=scenarios, project_name=req.project_name,
            project_id=req.project_id,
            backtest=backtest, generation_compare=generation_compare,
            promises=promises, forecast=forecast,
        )
        logger.info(f'HTML export OK: {result}')
        return JSONResponse(content=result)
    except Exception as e:
        logger.exception('HTML export FAILED')
        return JSONResponse(
            status_code=500,
            content={
                'status': 'error',
                'message': _friendly_error(e),
                'type': type(e).__name__,
            },
        )


# ─────────────────────────────────────────────────────
# v1.3.0 endpoints (per ADR-014, ADR-015, ADR-016)
# ─────────────────────────────────────────────────────


class SafeCorridorRequest(BaseModel):
    """v1.3.0: compute safe corridor для project."""
    project_dir: str
    relative_lo_factor: float = 0.5
    relative_hi_factor: float = 1.5


@app.post('/optimize/corridor')
def optimize_corridor(req: SafeCorridorRequest):
    """Compute safe corridor для бюджета каналов + aggregate (ADR-014).

    MVP формула per канал: max(P5, 0.5*mu), min(P95, 1.5*mu).
    Used by UI: CorridorSlider визуализирует green/yellow/red zones.
    """
    try:
        from engines.persistence import load_model_with_compat
        from optimize.bounds import compute_safe_corridor
        from pathlib import Path

        model_path = Path(req.project_dir) / 'models' / 'latest.pkl'
        if not model_path.exists():
            return JSONResponse(content={
                'status': 'error',
                'error_code': 'MODEL_NOT_FOUND',
                'message': 'Модель не найдена.',
            }, status_code=404)

        model_data = load_model_with_compat(model_path)
        corridor = compute_safe_corridor(
            model_data,
            relative_lo_factor=req.relative_lo_factor,
            relative_hi_factor=req.relative_hi_factor,
        )
        corridor['status'] = 'ok'
        return JSONResponse(content=corridor)
    except Exception as e:
        logger.exception('Safe corridor compute FAILED')
        return JSONResponse(status_code=500, content={
            'status': 'error',
            'message': _friendly_error(e),
            'type': type(e).__name__,
        })


class SplitCiRequest(BaseModel):
    """A4/OPP-04 (2026-07-03): интервалы неопределённости оптимального сплита
    (Jin 2017: пере-оптимизация на подвыборке posterior-draws → HDI долей)."""
    project_dir: str
    total_budget_money: float | None = None  # None → текущий суммарный
    n_draws: int = 60
    unit_costs: dict[str, float] | None = None


@app.post('/optimize/split-ci')
def optimize_split_ci_endpoint(req: SplitCiRequest):
    """Распределение оптимальных долей по posterior-draws (дорого, ~секунды —
    отдельная кнопка в UI, не интерактивный путь)."""
    try:
        from optimize.split_ci import optimal_split_ci
        result = optimal_split_ci(
            project_dir=req.project_dir,
            total_budget_money=req.total_budget_money,
            n_draws=req.n_draws,
            unit_costs_override=req.unit_costs,
        )
        return JSONResponse(content=result)
    except FileNotFoundError as e:
        # Текст резолвера данных уже человеческий и с действием — как есть.
        return JSONResponse(status_code=200, content={
            'status': 'error', 'error_code': 'DATA_FILE_MISSING', 'message': str(e)})
    except Exception as e:
        logger.exception('Split-CI FAILED')
        return JSONResponse(status_code=500, content={
            'status': 'error', 'message': _friendly_error(e), 'type': type(e).__name__})


class BacktestRequest(BaseModel):
    """E1 (2026-07-03): rolling-origin проверка модели на истории
    («модель vs факт»: coverage 90% PI, наивные бенчмарки, вердикт)."""
    project_dir: str
    horizon_periods: int | None = Field(default=None, ge=1, le=90)
    min_train: int | None = Field(default=None, ge=8, le=200)
    mode: Literal['auto', 'bayesian', 'ols'] = 'auto'
    max_windows: int = Field(default=8, ge=3, le=12)
    # Прочитать сохранённую витрину (models/backtest.json) без пересчёта —
    # мгновенный путь для загрузки карточки/отчёта.
    read_only: bool = False


@app.post('/compute/backtest')
def compute_backtest_endpoint(req: BacktestRequest):
    """E1 витрина: дорого (bayesian ≈ N окон × время обучения) — в UI это
    отдельная кнопка с честной оценкой времени, не интерактивный путь.
    status='insufficient' — честный результат («истории недостаточно»), не сбой."""
    try:
        from engines.backtest import load_saved_backtest, run_rolling_backtest
        if req.read_only:
            saved = load_saved_backtest(req.project_dir)
            if saved is None:
                return JSONResponse(content={
                    'status': 'not_found',
                    'message': 'Проверка на истории ещё не проводилась.',
                })
            return JSONResponse(content=saved)
        result = run_rolling_backtest(
            req.project_dir,
            horizon_periods=req.horizon_periods,
            min_train=req.min_train,
            mode=req.mode,
            max_windows=req.max_windows,
        )
        if (
            result.get('status') == 'error'
            and result.get('error_code') in ('NO_MODEL', 'NO_DATA')
        ):
            return JSONResponse(status_code=404, content=result)
        return JSONResponse(content=result)
    except Exception as e:
        logger.exception('Backtest FAILED')
        return JSONResponse(status_code=500, content={
            'status': 'error', 'message': _friendly_error(e), 'type': type(e).__name__})


class GenerationCompareRequest(BaseModel):
    """E3 (2026-07-03): сравнение текущей модели с архивным поколением
    («что изменилось с прошлого квартала», вердикты по перекрытию CI)."""
    project_dir: str
    baseline_ts: str | None = Field(default=None, pattern=r'^\d{8}_\d{6}$')
    unit_costs: dict[str, float] | None = None
    # Мгновенное чтение сохранённого сравнения (models/generation_compare.json).
    read_only: bool = False


@app.post('/compute/generation-compare')
def generation_compare_endpoint(req: GenerationCompareRequest):
    """Дёшево (2 декомпозиции, секунды). status='insufficient' — честный
    результат «истории поколений ещё нет», не сбой."""
    try:
        from engines.model_compare import (
            compare_generations,
            load_saved_generation_compare,
        )
        if req.read_only:
            saved = load_saved_generation_compare(req.project_dir)
            if saved is None:
                return JSONResponse(content={
                    'status': 'not_found',
                    'message': 'Сравнение поколений ещё не выполнялось.',
                })
            return JSONResponse(content=saved)
        result = compare_generations(
            req.project_dir,
            baseline_ts=req.baseline_ts,
            unit_costs_override=req.unit_costs,
        )
        if (
            result.get('status') == 'error'
            and result.get('error_code') in ('NO_MODEL', 'GENERATION_NOT_FOUND')
        ):
            return JSONResponse(status_code=404, content=result)
        return JSONResponse(content=result)
    except Exception as e:
        logger.exception('Generation compare FAILED')
        return JSONResponse(status_code=500, content={
            'status': 'error', 'message': _friendly_error(e), 'type': type(e).__name__})


class DriftCheckRequest(BaseModel):
    """E3 (2026-07-03): дрейф — архивное поколение на свежем хвосте данных."""
    project_dir: str
    baseline_ts: str | None = Field(default=None, pattern=r'^\d{8}_\d{6}$')


@app.post('/compute/drift-check')
def drift_check_endpoint(req: DriftCheckRequest):
    try:
        from engines.model_compare import drift_check
        result = drift_check(req.project_dir, baseline_ts=req.baseline_ts)
        if (
            result.get('status') == 'error'
            and result.get('error_code') in ('NO_MODEL', 'GENERATION_NOT_FOUND', 'NO_DATA')
        ):
            return JSONResponse(status_code=404, content=result)
        return JSONResponse(content=result)
    except Exception as e:
        logger.exception('Drift check FAILED')
        return JSONResponse(status_code=500, content={
            'status': 'error', 'message': _friendly_error(e), 'type': type(e).__name__})


class PromisesListRequest(BaseModel):
    """E4 (2026-07-03): зафиксированные прогнозы-обещания проекта."""
    project_dir: str


class PromiseCreateRequest(BaseModel):
    """E4: «Зафиксировать прогноз» — рекомендация становится проверяемой."""
    project_dir: str
    action_text: str = Field(min_length=3)
    expected_kpi_total: float
    ci_low: float | None = None
    ci_high: float | None = None
    horizon_periods: int = Field(ge=1, le=90)
    channel_changes: dict[str, float] | None = None
    extrapolation_flag: bool = False
    source: str = 'optimize'


@app.post('/compute/promises')
def promises_list_endpoint(req: PromisesListRequest):
    try:
        from engines.promises import list_promises
        return JSONResponse(content=list_promises(req.project_dir))
    except Exception as e:
        logger.exception('Promises list FAILED')
        return JSONResponse(status_code=500, content={
            'status': 'error', 'message': _friendly_error(e), 'type': type(e).__name__})


@app.post('/compute/promises/create')
def promises_create_endpoint(req: PromiseCreateRequest):
    try:
        from engines.promises import create_promise
        result = create_promise(
            req.project_dir,
            action_text=req.action_text,
            expected_kpi_total=req.expected_kpi_total,
            ci_low=req.ci_low,
            ci_high=req.ci_high,
            horizon_periods=req.horizon_periods,
            channel_changes=req.channel_changes,
            extrapolation_flag=req.extrapolation_flag,
            source=req.source,
        )
        if result.get('status') == 'error' and result.get('error_code') == 'NO_DATA':
            return JSONResponse(status_code=404, content=result)
        return JSONResponse(content=result)
    except Exception as e:
        logger.exception('Promise create FAILED')
        return JSONResponse(status_code=500, content={
            'status': 'error', 'message': _friendly_error(e), 'type': type(e).__name__})


@app.post('/compute/promises/check')
def promises_check_endpoint(req: PromisesListRequest):
    """Сверка обещаний со свежим фактом (kept/missed/pending со счётчиком)."""
    try:
        from engines.promises import check_promises
        result = check_promises(req.project_dir)
        if (
            result.get('status') == 'error'
            and result.get('error_code') in ('NO_MODEL', 'NO_DATA')
        ):
            return JSONResponse(status_code=404, content=result)
        return JSONResponse(content=result)
    except Exception as e:
        logger.exception('Promises check FAILED')
        return JSONResponse(status_code=500, content={
            'status': 'error', 'message': _friendly_error(e), 'type': type(e).__name__})


class InverseOptimizeRequest(BaseModel):
    """v1.3.0: Goal-Seek optimization (find min budget for target sales)."""
    project_dir: str
    target_sales: float
    kpi_kind: str = 'monetary'  # 'monetary' | 'count'
    mode: str = 'roi'           # 'roi' | 'effectiveness' | 'manual' (for logging)
    max_budget: float | None = None
    min_budget: float | None = None
    # OPP-02 (2026-07-03): «бюджет под вероятность». None = медианный режим
    # (back-compat); напр. 0.8 = минимальный бюджет с P(достижения цели) >= 80%
    # (квантильная бисекция по posterior-draws, optimize/inverse.py).
    confidence: float | None = None


@app.post('/optimize/inverse')
def optimize_inverse_endpoint(req: InverseOptimizeRequest):
    """Goal-Seek optimization: дана цель продаж → найти минимальный бюджет (ADR-014).

    MVP: бисекция по бюджету + Delta method posterior CI.
    Phase B: full posterior re-bisection (10 multi-start × 1000 draws).
    """
    try:
        from optimize.inverse import optimize_inverse as _optimize_inverse

        budget_constraints = None
        if req.max_budget is not None or req.min_budget is not None:
            budget_constraints = {}
            if req.max_budget is not None:
                budget_constraints['max_budget'] = req.max_budget
            if req.min_budget is not None:
                budget_constraints['min_budget'] = req.min_budget

        result = _optimize_inverse(
            project_dir=req.project_dir,
            target_sales=req.target_sales,
            kpi_kind=req.kpi_kind,
            mode=req.mode,
            budget_constraints=budget_constraints,
            confidence=req.confidence,
        )
        if 'status' not in result:
            result['status'] = 'ok'
        return JSONResponse(content=result)
    except Exception as e:
        logger.exception('Inverse optimize FAILED')
        return JSONResponse(status_code=500, content={
            'status': 'error',
            'message': _friendly_error(e),
            'type': type(e).__name__,
        })


class AutoPriceRequest(BaseModel):
    """v1.3.0: auto-detect value_per_count_unit (e.g. цена/упаковку, ценность лида)."""
    project_dir: str
    monetary_column: str  # e.g. 'sales_rub', 'revenue'
    count_column: str     # e.g. 'sales_packs', 'leads', 'registrations'
    cv_warn_threshold: float = 0.20


@app.post('/project/auto_price')
def project_auto_price(req: AutoPriceRequest):
    """Auto-detect value_per_count_unit из data (ADR-016).

    Reads training Excel/CSV, computes trimmed mean ratio monetary/count,
    flags CV>threshold as instability warning.
    """
    try:
        from engines.persistence import load_model_with_compat
        from optimize.auto_price import detect_value_per_count_unit
        from pathlib import Path
        import pandas as pd

        # Load training data from project.
        # First try latest.pkl config.data_file; fallback к project's data folder.
        model_path = Path(req.project_dir) / 'models' / 'latest.pkl'
        data_file = None
        if model_path.exists():
            model_data = load_model_with_compat(model_path)
            config = model_data.get('config') or {}
            data_file = config.get('data_file')

        if not data_file:
            # Fallback: ищем data folder.
            data_dir = Path(req.project_dir) / 'data'
            for candidate in data_dir.glob('*'):
                if candidate.suffix in ('.xlsx', '.xls', '.csv'):
                    data_file = str(candidate)
                    break

        if not data_file:
            return JSONResponse(content={
                'status': 'error',
                'error_code': 'NO_DATA_FILE',
                'message': 'Данные не найдены - загрузите проект и обучите модель сначала.',
            }, status_code=404)

        if str(data_file).endswith(('.xlsx', '.xls')):
            df = pd.read_excel(data_file)
        else:
            df = pd.read_csv(data_file)

        result = detect_value_per_count_unit(
            df,
            monetary_col=req.monetary_column,
            count_col=req.count_column,
            cv_warn_threshold=req.cv_warn_threshold,
        )
        result['status'] = 'ok'
        return JSONResponse(content=result)
    except Exception as e:
        logger.exception('Auto price detection FAILED')
        return JSONResponse(status_code=500, content={
            'status': 'error',
            'message': _friendly_error(e),
            'type': type(e).__name__,
        })


class ValuePerCountUnitSaveRequest(BaseModel):
    """v1.3.0: persist user-confirmed value_per_count_unit + per_channel_input.

    v2.0.1 (Phase 1.2): extended with unit_costs + inflation + mode_for +
    budget_inputs для defense-in-depth backend validation (audit P-02).
    All new fields optional — backward compat preserved.
    """
    project_dir: str
    value_per_count_unit: float | None = None
    value_per_count_unit_label: str = ''
    value_per_count_unit_source: str | None = None  # 'auto'|'manual'|'imported'
    per_channel_input: dict[str, str] | None = None  # {channel: 'monetary'|'physical'}
    kpi_kind: str = 'monetary'                       # 'monetary' | 'count'
    # v2.0.1 — unit cost persistence + role compatibility validation
    unit_costs: dict[str, float] | None = None         # {channel: ₽ per unit}
    unit_cost_inflation: dict[str, float] | None = None  # {channel: annual %}
    mode_for: dict[str, str] | None = None             # {channel: 'budget'|'unit'} (UI mode preference)
    budget_inputs: dict[str, float] | None = None      # {channel: raw budget input для UI restore}

    @field_validator('unit_costs')
    @classmethod
    def _validate_unit_costs_bounds(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        if v is None:
            return None
        for channel, cost in v.items():
            if not isinstance(cost, (int, float)):
                raise ValueError(f'unit_cost для {channel!r} must be numeric, got {type(cost).__name__}')
            if cost != cost:  # NaN check
                raise ValueError(f'unit_cost для {channel!r} is NaN')
            if cost < 0:
                raise ValueError(f'unit_cost для {channel!r} must be ≥ 0, got {cost}')
            if cost > 1e9:
                raise ValueError(f'unit_cost для {channel!r} unreasonably high: {cost} (max 1e9 ₽/unit)')
        return v

    @field_validator('unit_cost_inflation')
    @classmethod
    def _validate_inflation_bounds(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        if v is None:
            return None
        for channel, rate in v.items():
            if not isinstance(rate, (int, float)):
                raise ValueError(f'inflation для {channel!r} must be numeric')
            if rate != rate:  # NaN
                raise ValueError(f'inflation для {channel!r} is NaN')
            # Inflation %/год — sanity range [-50, 500]. Negative = deflation, accepted.
            if rate < -50 or rate > 500:
                raise ValueError(f'inflation для {channel!r} out of range: {rate}% (expected -50..500)')
        return v

    @field_validator('mode_for')
    @classmethod
    def _validate_mode_for(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is None:
            return None
        for channel, mode in v.items():
            if mode not in ('budget', 'unit'):
                raise ValueError(f'mode_for[{channel!r}] must be "budget" or "unit", got {mode!r}')
        return v

    @field_validator('value_per_count_unit')
    @classmethod
    def _validate_value_per_count_unit(cls, v: float | None) -> float | None:
        """Reject NaN / Infinity / negative / unreasonable values (audit H-03).

        Pydantic v2 accepts float('inf') as valid float — без guard'a проскакивает
        в settings JSON, downstream produces inf * spend = inf ROAS. Same bounds
        as unit_costs validator (sister field, parallel logic).
        """
        if v is None:
            return None
        if not isinstance(v, (int, float)):
            raise ValueError(f'value_per_count_unit must be numeric, got {type(v).__name__}')
        if v != v:  # NaN check
            raise ValueError('value_per_count_unit is NaN')
        import math
        if math.isinf(v):
            raise ValueError('value_per_count_unit is Infinity')
        if v < 0:
            raise ValueError(f'value_per_count_unit must be ≥ 0, got {v}')
        if v > 1e9:
            raise ValueError(f'value_per_count_unit unreasonably high: {v} (max 1e9)')
        return float(v)


@app.post('/project/save_kpi_settings')
def project_save_kpi_settings(req: ValuePerCountUnitSaveRequest):
    """Persist v1.3.0 KPI settings (per ADR-015, ADR-016, ADR-017).

    v2.0.1 (Phase 1.2): cross-field role compatibility validation
    (audit P-02 defense-in-depth) + atomic write через safe_io
    (Phase 0.3) + structured logging (Phase 0.2).

    Updates project state с derived_mode, kpi_kind, value_per_count_unit,
    unit_costs, inflation, mode_for, budget_inputs fields. NB: НЕ retrains
    модель — это lightweight metadata update.
    """
    try:
        from pathlib import Path
        from utils.mode_inference import derive_mode
        from utils.safe_io import atomic_write_json
        from utils.log_config import setup_module_logger, log_event
        from engines.validator import validate_role_compatibility

        save_logger = setup_module_logger('save_kpi_settings')
        from utils.file_lock import project_lock, LockTimeout

        # H-01 path traversal guard
        project_path = _assert_project_dir_safe(req.project_dir)
        if not project_path.exists():
            log_event(save_logger, 'kpi_settings_project_not_found', project_dir=str(project_path))
            return JSONResponse(content={
                'status': 'error',
                'error_code': 'PROJECT_NOT_FOUND',
            }, status_code=404)

        # C-02 multi-tab safety: lock на read-modify-write всей операции.
        # Если другая вкладка / процесс держит lock — wait до 5s, потом 423.
        try:
            with project_lock(project_path, timeout=5.0):
                # Cross-field validation: unit_costs only for media channels.
                # Read media list from project.json (if exists) — otherwise skip check.
                media_columns = []
                proj_json = project_path / 'project.json'
                if proj_json.exists():
                    try:
                        with open(proj_json, encoding='utf-8') as pf:
                            proj_data = json.load(pf)
                        media_columns = proj_data.get('media_columns', []) or []
                    except (OSError, json.JSONDecodeError):
                        media_columns = []

                if req.unit_costs and media_columns:
                    valid, err_code, msg = validate_role_compatibility(
                        req.unit_costs,
                        media_columns,
                    )
                    if not valid:
                        log_event(
                            save_logger,
                            'kpi_settings_role_mismatch',
                            level=logging.WARNING,
                            project_dir=str(project_path),
                            error_code=err_code,
                            detail=msg,
                        )
                        return JSONResponse(content={
                            'status': 'error',
                            'error_code': err_code,
                            'message': msg,
                        }, status_code=422)

                # Save as JSON metadata in project's settings/v13_kpi.json.
                settings_dir = project_path / 'settings'
                settings_dir.mkdir(parents=True, exist_ok=True)
                settings_file = settings_dir / 'v13_kpi.json'

                # Compute derived mode if per_channel_input provided.
                derived_mode = None
                if req.per_channel_input:
                    derived_mode = derive_mode(req.per_channel_input)

                settings = {
                    'kpi_kind': req.kpi_kind,
                    'value_per_count_unit': req.value_per_count_unit,
                    'value_per_count_unit_label': req.value_per_count_unit_label,
                    'value_per_count_unit_source': req.value_per_count_unit_source,
                    'per_channel_input': req.per_channel_input or {},
                    'derived_mode': derived_mode,
                    # v2.0.1 (Phase 1.3 persistence of UI mode state):
                    'unit_costs': req.unit_costs or {},
                    'unit_cost_inflation': req.unit_cost_inflation or {},
                    'mode_for': req.mode_for or {},
                    'budget_inputs': req.budget_inputs or {},
                    'updated_at': pd.Timestamp.now().isoformat(),
                }

                # Atomic write через Phase 0.3 helper — power-loss safe.
                try:
                    sha = atomic_write_json(settings_file, settings)
                except OSError as oe:
                    log_event(
                        save_logger,
                        'kpi_settings_disk_error',
                        level=logging.ERROR,
                        project_dir=str(project_path),
                        error=str(oe),
                    )
                    return JSONResponse(status_code=500, content={
                        'status': 'error',
                        'error_code': 'DISK_WRITE_FAILED',
                        'message': f'Не удалось записать настройки: {oe}',
                    })

                log_event(
                    save_logger,
                    'kpi_settings_saved',
                    project_dir=str(project_path),
                    derived_mode=derived_mode,
                    sha256=sha,
                    n_unit_costs=len(req.unit_costs or {}),
                )

                return JSONResponse(content={
                    'status': 'ok',
                    'derived_mode': derived_mode,
                    'saved_to': str(settings_file),
                    'integrity_sha256': sha,
                })
        except LockTimeout as lt:
            log_event(
                save_logger, 'kpi_settings_lock_timeout',
                level=logging.WARNING, project_dir=str(project_path),
            )
            return JSONResponse(status_code=423, content={
                'status': 'error',
                'error_code': 'LOCK_TIMEOUT',
                'message': str(lt),
            })
    except Exception as e:
        logger.exception('Save KPI settings FAILED')
        return JSONResponse(status_code=500, content={
            'status': 'error',
            'message': _friendly_error(e),
            'type': type(e).__name__,
        })


# ── Startup ──────────────────────────────────────────

if __name__ == '__main__':
    import uvicorn

    # Port: sys.argv[1] (от Rust) → fallback 7430 (back-compat с pre-v1.0.9 Rust)
    _port = 7430
    if len(sys.argv) > 1:
        try:
            _port = int(sys.argv[1])
        except ValueError:
            logger.warning(f'Invalid port arg "{sys.argv[1]}", using legacy {_port}')
    # Машиночитаемая метка для parent-process (синхронно с brand-hub/rag-server)
    print(f'PORT:{_port}', flush=True)
    logger.info(f'uvicorn binding 127.0.0.1:{_port}')
    uvicorn.run(app, host='127.0.0.1', port=_port, log_level='info')
