"""
Aurora AI Econometrica — Python Sidecar Server.
FastAPI server for local MMM computations (0 Claude tokens).

Port: принимается через sys.argv[1] (fallback 7430 для back-compat).
Version: из env AURORA_PRODUCT_VERSION (fallback '1.0.9').
Product ID: из env AURORA_PRODUCT_ID (fallback 'com.aurora.econometrica').

Per-user RDP изоляция обеспечивается на Rust-стороне — этот сервер
просто слушает переданный ему порт.
"""
# ── JAX multi-core setup — MUST be before any `import jax` ──────────────
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
from typing import Any

# Ensure sidecar root is in sys.path for absolute imports (engines.*, utils.*, charts.*)
_sidecar_root = str(Path(__file__).parent)
if _sidecar_root not in sys.path:
    sys.path.insert(0, _sidecar_root)

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ── Identity & session (required by handshake protocol v1.0.9+) ──────────────
# Session_id меняется при каждом cold start. Rust сверяет его с sidecar.json
# и live /health, несовпадение → force kill + respawn (защита от stale/foreign).
PRODUCT_ID = os.environ.get('AURORA_PRODUCT_ID', 'com.aurora.econometrica')
VERSION = os.environ.get('AURORA_PRODUCT_VERSION', '1.0.9')
SESSION_ID = uuid.uuid4().hex
STARTED_AT = datetime.now(timezone.utc).isoformat()

# Configure logging — dual output: stderr + rotating file в %LOCALAPPDATA%.
# %LOCALAPPDATA% (AppData\Local) гарантированно НЕ роумит в AD-доменах,
# в отличие от %APPDATA% (AppData\Roaming) — критично для RDP-серверов.
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
# Surgical filter — preserves legitimate asyncio errors, убирает только этот тип.
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

    # Known-risk bundle paths — if any missing, the sidecar WILL crash later.
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
    ]
    for rel in _required_files:
        p = _bundle_root / rel
        logger.info(f'bundle check: {rel} — {"OK" if p.exists() else "MISSING"} ({p})')

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

    # Probe JAX devices — подтверждение что XLA_FLAGS применился до init.
    # Если XLA_FLAGS не сработал (старый jax, ручной override) — devices=1,
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


# ── Global exception handler (JSON envelope) ─────────────────────────────────
# Без него любая необработанная ошибка возвращается uvicorn'ом как plain text
# `Internal Server Error`. Rust-сторона валится на парсинге с «expected value
# at line 1 column 1». Под RemoteApp (другой профиль/env/тайминги) вероятность
# неожиданных ошибок выше — пример: PermissionError на записи результата.
#
# HTTPException и RequestValidationError обрабатываются встроенными handler'ами
# FastAPI — явно пропускаем их (re-raise) чтобы не перехватить 400/404/422.
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
            'message': str(exc)[:500],  # truncate — избегаем длинных путей в body
            'type': type(exc).__name__,
            'path': str(request.url.path),
        },
    )


# ── Session middleware (handshake protection) ────────────────────────────────
# Каждый API-запрос от GUI может включать заголовок `X-Expected-Session: <uuid>`.
# Если он не совпадает с текущим SESSION_ID — это значит GUI разговаривает с
# процессом, которого он не создавал (переиспользованный чужой sidecar).
# Отвечаем 409 Conflict — GUI перехватывает и делает re-handshake + retry once.
@app.middleware('http')
async def session_guard(request: Request, call_next):
    # Health и shutdown пропускаем — они сами служат для разрешения рассинхрона
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
# Signal от родителя (Rust закрывает GUI) или HTTP /shutdown — cleanup + exit.
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
    # Стоимость 1 юнита канала в валюте KPI для не-денежных каналов (CPP/CPM).
    # {channel: cost_per_unit}. Если задано — decomposer/optimizer используют
    # spend × unit_cost для отображения и расчёта ROI. На обучение модели не
    # влияет (Hill работает на нативных единицах канала).
    unit_costs: dict[str, float] = {}
    # Виртуальные merged каналы (например «Малые медиа» из 4 источников).
    # Frontend InsightsPanel создаёт их как metadata. Backend создаёт
    # df[merged_name] = sum(df[sources]) до column guard. См. utils/merge_rules.py.
    merge_rules: dict[str, list[str]] = {}


class TrainStartRequest(BaseModel):
    project_dir: str
    data_file: str
    kpi_column: str
    media_columns: list[str]
    control_columns: list[str] = []
    date_column: str = 'date'
    adstock_config: dict[str, str] = {}
    mcmc_override: dict | None = None
    unit_costs: dict[str, float] = {}
    merge_rules: dict[str, list[str]] = {}


class DecomposeRequest(BaseModel):
    project_dir: str
    # Trust Level 2: override unit_costs поверх pickle-config.
    # Нужно когда user изменил CPP после тренировки — pickle содержит старые значения.
    unit_costs: dict[str, float] | None = None


class OptimizeRequest(BaseModel):
    project_dir: str
    total_budget: float | None = None
    # Альтернатива total_budget: constraint в money (Σ x × unit_cost == total_budget_money).
    # Используется в Forecast режиме «Сохранить бюджет» — чтобы сумма в рублях
    # после оптимизации оставалась точно равной currentMoney.
    total_budget_money: float | None = None
    min_pct: float = 50
    max_pct: float = 150
    # Per-channel constraints (экспертный режим). Перекрывают глобальные min_pct/max_pct
    # для указанных каналов. Если канал отсутствует в dict — используется глобальный лимит.
    min_per_channel: dict[str, float] | None = None
    max_per_channel: dict[str, float] | None = None
    # Override unit_costs (аналогично DecomposeRequest).
    unit_costs: dict[str, float] | None = None


class ScenarioRequest(BaseModel):
    project_dir: str
    scenario_name: str = 'custom'
    media_plan: dict[str, list[float]] = {}
    media_plan_file: str | None = None
    unit_costs: dict[str, float] | None = None


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
    # Абсолютный путь к project_dir — передаётся Rust-стороной чтобы
    # учесть Settings override (econometrica_projects_root). Fallback на
    # вычисление из %APPDATA% если None для обратной совместимости со старым Rust.
    project_dir: str | None = None


class HtmlExportRequest(BaseModel):
    project_id: str
    model_data: dict
    decompose_data: dict
    optimize_data: dict
    project_name: str = 'Marketing Mix Model'
    project_dir: str | None = None


class ModelHistoryRequest(BaseModel):
    project_dir: str


# ── Async training state ─────────────────────────────
# task_id → {status, phase, pct, elapsed_sec, result, error, started_at}
_training_tasks: dict[str, dict] = {}
_training_lock = threading.Lock()


# ── Health ───────────────────────────────────────────

@app.get('/health')
async def health():
    """Extended /health (v1.0.9+) — handshake protocol.

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


@app.post('/compute/train')
def train_model(req: TrainRequest):
    """Train Bayesian MMM model. Long-running (3-15 min).
    sync def — FastAPI runs in thread pool, event loop stays free for /health polling."""
    from engines.modeler import train_model as _train
    config = req.model_dump()
    project_dir = config.pop('project_dir')
    result = _train(config, project_dir)
    return JSONResponse(content=result)


@app.post('/compute/train/start')
def train_start(req: TrainStartRequest):
    """Start async training. Returns task_id immediately."""
    task_id = str(uuid.uuid4())
    config = req.model_dump()
    config.pop('project_dir')
    project_dir = req.project_dir
    logger.info(f'/compute/train/start: kpi={req.kpi_column}, media={len(req.media_columns)} channels, merge_rules={req.merge_rules!r}')

    with _training_lock:
        # Cleanup consumed tasks older than 5 min
        cutoff = time.time() - 300
        stale = [k for k, v in _training_tasks.items() if v.get('consumed_at', 0) and v['consumed_at'] < cutoff]
        for k in stale:
            del _training_tasks[k]

        _training_tasks[task_id] = {
            'status': 'running',
            'phase': 'loading',
            'pct': 0,
            'elapsed_sec': 0,
            'started_at': time.time(),
            'result': None,
            'error': None,
        }

    def run():
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
            return result
    return {'status': 'pending'}


@app.post('/compute/decompose')
def decompose_sales(req: DecomposeRequest):
    """Decompose sales into baseline + channel contributions."""
    from engines.decomposer import decompose as _decompose
    from pathlib import Path as _Path
    pickle_exists = (_Path(req.project_dir) / 'models' / 'latest.pkl').exists()
    logger.info(f'/compute/decompose project_dir={req.project_dir} pickle_exists={pickle_exists}')
    result = _decompose(req.project_dir, unit_costs_override=req.unit_costs)
    if result.get('status') != 'ok':
        logger.warning(f'/compute/decompose returned error: {result.get("message")}')
    return JSONResponse(content=result)


@app.post('/compute/optimize')
def optimize_budget(req: OptimizeRequest):
    """Optimize budget allocation across channels."""
    from engines.optimizer import optimize as _optimize
    config = {
        'total_budget': req.total_budget,
        'total_budget_money': req.total_budget_money,
        'min_pct': req.min_pct,
        'max_pct': req.max_pct,
        'min_per_channel': req.min_per_channel,
        'max_per_channel': req.max_per_channel,
        'unit_costs': req.unit_costs,  # None → decomposer fallback на pickle config
    }
    result = _optimize(config, req.project_dir)
    return JSONResponse(content=result)


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
        return {'status': 'error', 'message': str(e)}


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


# ── PPTX Export ──────────────────────────────────────────

def _resolve_project_dir(project_dir: str | None, project_id: str) -> Path:
    """Вычислить путь к project_dir с учётом Settings override.

    Приоритет:
      1. Явно переданный project_dir (из Rust с учётом Settings override)
      2. Fallback на %APPDATA%\\<identifier>\\projects\\<project_id>\\ для
         обратной совместимости со старыми клиентами Rust.
    """
    if project_dir:
        return Path(project_dir)
    appdata = os.environ.get('APPDATA', '')
    identifier = 'aurora-econometrica-gui'
    return Path(appdata) / identifier / 'projects' / project_id


@app.post('/export/pptx')
def export_pptx(req: PptxExportRequest):
    """Generate branded PPTX presentation from MMM results."""
    logger.info(f'PPTX export START project_id={req.project_id}')
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

        # Сценарии — читаем с диска (Frontend их не передаёт, они — артефакт шага Optimize).
        scenarios_dir = project_path / 'results' / 'scenarios'
        scenarios: list[dict] = []
        if scenarios_dir.exists():
            for f in sorted(scenarios_dir.glob('*.json')):
                try:
                    with open(f, 'r', encoding='utf-8') as fh:
                        scenarios.append(json.load(fh))
                except Exception:
                    continue
        logger.info(f'PPTX inputs: model={has_model} decompose={has_decomp} optimize={has_optim} scenarios={len(scenarios)}')

        result = build_pptx(
            req.model_data, req.decompose_data, req.optimize_data,
            output_path, scenarios=scenarios, project_id=req.project_id,
        )
        logger.info(f'PPTX export OK: {result}')
        return JSONResponse(content=result)
    except Exception as e:
        logger.exception('PPTX export FAILED')
        return JSONResponse(
            status_code=500,
            content={
                'status': 'error',
                'message': str(e),
                'type': type(e).__name__,
            },
        )


@app.post('/export/html')
def export_html(req: HtmlExportRequest):
    """Generate interactive standalone HTML report."""
    logger.info(f'HTML export START project_id={req.project_id}')
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

        result = build_html(
            req.model_data, decompose_for_build, req.optimize_data, output_path,
            scenarios=scenarios, project_name=req.project_name,
            project_id=req.project_id,
        )
        logger.info(f'HTML export OK: {result}')
        return JSONResponse(content=result)
    except Exception as e:
        logger.exception('HTML export FAILED')
        return JSONResponse(
            status_code=500,
            content={
                'status': 'error',
                'message': str(e),
                'type': type(e).__name__,
            },
        )


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
