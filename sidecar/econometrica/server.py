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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stderr,
)
logger = logging.getLogger('econometrica')

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


class TrainStartRequest(BaseModel):
    project_dir: str
    data_file: str
    kpi_column: str
    media_columns: list[str]
    control_columns: list[str] = []
    date_column: str = 'date'
    adstock_config: dict[str, str] = {}
    mcmc_override: dict | None = None


class DecomposeRequest(BaseModel):
    project_dir: str


class OptimizeRequest(BaseModel):
    project_dir: str
    total_budget: float | None = None
    min_pct: float = 50
    max_pct: float = 150


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


class PptxExportRequest(BaseModel):
    project_id: str
    model_data: dict
    decompose_data: dict
    optimize_data: dict


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
    return {'task_id': task_id, **{k: v for k, v in task.items() if k not in ('result', 'error', 'started_at')}}


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
    result = _decompose(req.project_dir)
    return JSONResponse(content=result)


@app.post('/compute/optimize')
def optimize_budget(req: OptimizeRequest):
    """Optimize budget allocation across channels."""
    from engines.optimizer import optimize as _optimize
    config = {'total_budget': req.total_budget, 'min_pct': req.min_pct, 'max_pct': req.max_pct}
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


# ── PPTX Export ──────────────────────────────────────────

@app.post('/export/pptx')
def export_pptx(req: PptxExportRequest):
    """Generate branded PPTX presentation from MMM results."""
    from engines.pptx_export import build_pptx

    appdata = os.environ.get('APPDATA', '')
    identifier = 'com.aurora.econometrica'
    exports_dir = Path(appdata) / identifier / 'projects' / req.project_id / 'exports'
    exports_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_path = str(exports_dir / f'mmm_report_{ts}.pptx')

    result = build_pptx(req.model_data, req.decompose_data, req.optimize_data, output_path)
    return JSONResponse(content=result)


# ── Startup ──────────────────────────────────────────

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=7430, log_level='info')
