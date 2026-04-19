"""
Aurora AI Econometrica — Python Sidecar Server.
FastAPI server for local MMM computations (0 Claude tokens).
Port: 7430
"""
import json
import logging
import os
import sys
import threading
import uuid
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Ensure sidecar root is in sys.path for absolute imports (engines.*, utils.*, charts.*)
_sidecar_root = str(Path(__file__).parent)
if _sidecar_root not in sys.path:
    sys.path.insert(0, _sidecar_root)

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Configure logging — dual output: stderr + file in %APPDATA%
_log_dir = Path(os.environ.get('APPDATA', '.')) / 'aurora-econometrica-gui' / 'logs'
try:
    _log_dir.mkdir(parents=True, exist_ok=True)
except Exception:
    _log_dir = Path('.')
_log_file = _log_dir / f'sidecar-{datetime.now().strftime("%Y-%m-%d")}.log'

_log_format = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
_stderr_handler = logging.StreamHandler(sys.stderr)
_stderr_handler.setFormatter(logging.Formatter(_log_format))
_file_handler = logging.FileHandler(_log_file, encoding='utf-8', mode='a')
_file_handler.setFormatter(logging.Formatter(_log_format))

logging.basicConfig(
    level=logging.INFO,
    handlers=[_stderr_handler, _file_handler],
    force=True,
)
logger = logging.getLogger('econometrica')
logger.info(f'=== Sidecar starting, log file: {_log_file} ===')

# Dump PyTensor/MSVC diagnostic on startup
try:
    from engines.modeler import check_compiler as _check_compiler
    _has_cc = _check_compiler()
    logger.info(f'check_compiler() = {_has_cc}')
    logger.info(f'Injected PATH (first 300 chars): {os.environ.get("PATH", "")[:300]}')
    logger.info(f'Injected INCLUDE (first 200 chars): {os.environ.get("INCLUDE", "(not set)")[:200]}')
    logger.info(f'Injected LIB (first 200 chars): {os.environ.get("LIB", "(not set)")[:200]}')
    # Now check what PyTensor picks up
    import pytensor
    logger.info(f'pytensor.config.cxx = "{pytensor.config.cxx}"')
    logger.info(f'pytensor.config.mode = "{pytensor.config.mode}"')
    logger.info(f'pytensor.config.compiledir = "{pytensor.config.compiledir}"')
except Exception as e:
    logger.exception(f'Startup diagnostic failed: {e}')

app = FastAPI(
    title='Aurora AI Econometrica Sidecar',
    version='1.0.0',
    description='Local MMM computation engine (0 tokens)',
)


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


class DecomposeRequest(BaseModel):
    project_dir: str
    # Trust Level 2: override unit_costs поверх pickle-config.
    # Нужно когда user изменил CPP после тренировки — pickle содержит старые значения.
    unit_costs: dict[str, float] | None = None


class OptimizeRequest(BaseModel):
    project_dir: str
    total_budget: float | None = None
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


class ModelHistoryRequest(BaseModel):
    project_dir: str


# ── Async training state ─────────────────────────────
# task_id → {status, phase, pct, elapsed_sec, result, error, started_at}
_training_tasks: dict[str, dict] = {}
_training_lock = threading.Lock()


# ── Health ───────────────────────────────────────────

@app.get('/health')
async def health():
    """Check sidecar health and available packages."""
    packages = {}
    for pkg in ['pymc', 'pymc_marketing', 'pandas', 'scipy', 'matplotlib', 'numpy']:
        try:
            mod = __import__(pkg)
            packages[pkg] = getattr(mod, '__version__', 'installed')
        except ImportError:
            packages[pkg] = None

    return {
        'status': 'ok',
        'version': '1.0.0',
        'python': sys.version,
        'packages': packages,
    }


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


@app.post('/compute/compare')
def compare_scenarios(req: DecomposeRequest):
    """Compare all saved scenarios side-by-side."""
    from engines.scenario import compare_scenarios as _compare
    result = _compare(req.project_dir)
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

@app.post('/export/pptx')
def export_pptx(req: PptxExportRequest):
    """Generate branded PPTX presentation from MMM results."""
    logger.info(f'PPTX export START project_id={req.project_id}')
    try:
        from engines.pptx_export import build_pptx

        appdata = os.environ.get('APPDATA', '')
        identifier = 'com.aurora.econometrica'
        exports_dir = Path(appdata) / identifier / 'projects' / req.project_id / 'exports'
        exports_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = str(exports_dir / f'mmm_report_{ts}.pptx')
        logger.info(f'PPTX output path: {output_path}')

        has_model = bool(req.model_data)
        has_decomp = bool(req.decompose_data)
        has_optim = bool(req.optimize_data)
        logger.info(f'PPTX inputs: model={has_model} decompose={has_decomp} optimize={has_optim}')

        result = build_pptx(req.model_data, req.decompose_data, req.optimize_data, output_path)
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


# ── Startup ──────────────────────────────────────────

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=7430, log_level='info')
