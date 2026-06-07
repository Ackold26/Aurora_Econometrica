"""Бэкфилл канонического `decomposition_series` в существующие decomposition.json
(аудит #12, 2026-06-07). Новые декомпозиции содержат поле автоматически; уже
сохранённые — нет. Скрипт добавляет его из существующих полей (time_series +
signed_factor_contributions) без ретрейна/ре-декомпозиции.

Использование:
  python tools/backfill_decomposition_series.py "<results_dir>"   # один проект
  python tools/backfill_decomposition_series.py --all             # все проекты
  python tools/backfill_decomposition_series.py --all --dry-run
"""
import os
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))
SID = os.path.join(os.path.dirname(HERE), 'sidecar', 'econometrica')
sys.path.insert(0, SID)
from engines.decomposer import build_decomposition_series

PROJECTS_ROOT = os.path.join(os.environ.get('APPDATA', ''), 'aurora-econometrica-gui', 'projects')


def backfill(results_dir: str, dry_run: bool = False) -> dict:
    name = os.path.basename(os.path.dirname(results_dir))
    path = os.path.join(results_dir, 'decomposition.json')
    if not os.path.exists(path):
        return {'project': name, 'status': 'skip', 'reason': 'no decomposition.json'}
    d = json.load(open(path, encoding='utf-8'))
    ts = d.get('time_series') or {}
    if not ts.get('dates'):
        return {'project': name, 'status': 'skip', 'reason': 'no time_series'}
    series = build_decomposition_series(
        ts.get('dates'), ts.get('baseline'), ts.get('channels'),
        d.get('signed_factor_contributions'),
    )
    n_factor = sum(1 for s in series['series'] if s['role'] == 'factor')
    d['decomposition_series'] = series
    if not dry_run:
        json.dump(d, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    return {'project': name, 'status': 'ok', 'n_series': len(series['series']),
            'n_factors': n_factor, 'written': not dry_run}


def main():
    args = list(sys.argv[1:])
    dry = '--dry-run' in args
    args = [a for a in args if a != '--dry-run']
    if args and args[0] == '--all':
        dirs = [os.path.join(PROJECTS_ROOT, dd, 'results') for dd in os.listdir(PROJECTS_ROOT)
                if os.path.isdir(os.path.join(PROJECTS_ROOT, dd, 'results'))]
    elif args:
        dirs = [args[0]]
    else:
        print(__doc__)
        return
    for d in dirs:
        print(json.dumps(backfill(d, dry_run=dry), ensure_ascii=False))


if __name__ == '__main__':
    main()
