"""Пересчёт MQS существующих моделей по ЭФФЕКТИВНЫМ параметрам (миграция).

Фон (2026-06-07, INV-50): MQS-cap стал считаться по эффективному ratio
(posterior contraction), а не номинальному. Новые трейны честны автоматически,
но уже обученные модели хранят старый (номинал-capped) MQS в
results/model-diagnostics.json. Этот скрипт пересчитывает MQS из сохранённого
posterior без ретрейна и патчит model-diagnostics.json (mqs/verdict/metrics/
checks), сохраняя остальные поля (per_param_rhat, actual_vs_predicted, …).

Использование:
  python tools/recompute_mqs.py "<project_dir>"     # один проект
  python tools/recompute_mqs.py --all               # все проекты
  python tools/recompute_mqs.py "<dir>" --dry-run   # показать без записи
"""
import sys, os, json
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SID = os.path.dirname(HERE)
sys.path.insert(0, SID)
from engines.persistence import load_model_with_compat
from utils.diagnostics import (
    prior_sds_for_bayesian, effective_params_contraction, generate_diagnostics_summary,
    per_control_contraction,
)
from utils.safe_io import sanitize_nonfinite

PROJECTS_ROOT = os.path.join(os.environ.get('APPDATA', ''), 'aurora-econometrica-gui', 'projects')


def posterior_sd_from_samples(ps: dict, groups) -> dict:
    """Per-param posterior SD из stored posterior_samples (shape (n, draws) или (draws,))."""
    out = {}
    for g in groups:
        if g not in ps:
            continue
        try:
            a = np.asarray(ps[g], dtype=float)
        except (ValueError, TypeError):
            continue
        if a.ndim == 0:
            continue
        if a.ndim == 1:                  # (draws,) — скаляр-параметр
            out[g] = [float(a.std())]
        else:                            # (n, draws) — вектор-параметр
            out[g] = a.std(axis=1)
    return out


def recompute_project(proj_dir: str, dry_run: bool = False) -> dict:
    pkl = os.path.join(proj_dir, 'models', 'latest.pkl')
    diag_path = os.path.join(proj_dir, 'results', 'model-diagnostics.json')
    if not os.path.exists(pkl) or not os.path.exists(diag_path):
        return {'project': os.path.basename(proj_dir), 'status': 'skip', 'reason': 'no pkl/diagnostics'}

    md = load_model_with_compat(pkl)
    if md.get('use_hierarchical'):
        return {'project': os.path.basename(proj_dir), 'status': 'skip', 'reason': 'hierarchical (nominal kept)'}
    ps = md.get('posterior_samples')
    if not isinstance(ps, dict):
        return {'project': os.path.basename(proj_dir), 'status': 'skip', 'reason': 'no posterior_samples (OLS?)'}

    with open(diag_path, 'r', encoding='utf-8') as f:
        diag = json.load(f)
    m = diag.get('metrics', {})
    comp = diag.get('mqs', {}).get('components', {})
    r_squared = comp.get('r_squared', {}).get('value', m.get('r_squared'))
    mape = comp.get('mape', {}).get('value', m.get('mape_pct'))
    rmse = m.get('rmse', 0.0)
    r_hat_max = m.get('r_hat_max', 1.0)
    divergences = m.get('divergences', 0)
    n_obs = m.get('n_observations') or len(md.get('y_actual') or [])
    n_params = m.get('n_parameters')
    if None in (r_squared, mape, n_obs, n_params):
        return {'project': os.path.basename(proj_dir), 'status': 'skip', 'reason': 'diagnostics missing fields'}

    cfg = md.get('config', {}) or {}
    prior_sd = prior_sds_for_bayesian(
        gammas_alpha=float(cfg.get('gammas_alpha', 3)),
        gammas_beta=float(cfg.get('gammas_beta', 3)),
    )
    post_sd = posterior_sd_from_samples(ps, prior_sd.keys())
    eff = effective_params_contraction(post_sd, prior_sd)
    if not eff:
        return {'project': os.path.basename(proj_dir), 'status': 'skip', 'reason': 'eff_params not computable'}

    old_score = diag.get('mqs', {}).get('score')
    new_diag = generate_diagnostics_summary(
        r_squared=r_squared, mape=mape, rmse=rmse,
        r_hat_max=r_hat_max, divergences=divergences,
        n_obs=n_obs, n_params=n_params, effective_params=eff,
    )
    # merge: обновляем только пересчитанные секции, остальное сохраняем
    diag['mqs'] = new_diag['mqs']
    diag['verdict'] = new_diag['verdict']
    diag.setdefault('metrics', {}).update(new_diag['metrics'])
    diag['checks'] = new_diag['checks']

    # #6 OVB-guardrail (2026-06-07): per-control contraction (SSOT-формула в diagnostics).
    pcc = per_control_contraction(
        post_sd.get('control_betas'), prior_sd.get('control_betas'),
        cfg.get('control_columns') or [])
    if pcc:
        diag['per_control_contraction'] = pcc

    result = {
        'project': os.path.basename(proj_dir), 'status': 'ok',
        'effective_params': round(eff, 2), 'nominal_params': n_params,
        'old_score': old_score, 'new_score': new_diag['mqs']['score'],
        'new_tier': new_diag['mqs']['tier_label'],
        'controls_uninformative': sum(1 for v in pcc.values() if v < 0.1),
        'controls_total': len(pcc),
    }
    if not dry_run:
        # Аудит 2026-06-07 (F-PY1): sanitize_nonfinite ОБЯЗАТЕЛЬНА — голый json.dump
        # пишет литерал NaN/Infinity (нарушение RFC 8259) → Rust serde_json (strict)
        # падает → project_load_results молча null → «Отчёт: модель не загружена».
        # modeler.py/ols_modeler.py санируют; recompute_mqs (3-й писатель) — теперь тоже.
        with open(diag_path, 'w', encoding='utf-8') as f:
            json.dump(sanitize_nonfinite(diag), f, ensure_ascii=False, indent=2)
        result['written'] = True
    return result


def main():
    args = [a for a in sys.argv[1:]]
    dry = '--dry-run' in args
    args = [a for a in args if a != '--dry-run']
    if args and args[0] == '--all':
        dirs = [os.path.join(PROJECTS_ROOT, d) for d in os.listdir(PROJECTS_ROOT)
                if os.path.isdir(os.path.join(PROJECTS_ROOT, d))]
    elif args:
        dirs = [args[0]]
    else:
        print(__doc__); return
    for d in dirs:
        print(json.dumps(recompute_project(d, dry_run=dry), ensure_ascii=False))


if __name__ == '__main__':
    main()
