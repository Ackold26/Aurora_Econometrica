"""Съёмник клиентских величин из обученной модели – для замера расхождения прогонов.

Читает модель, сохранённую `repro_train_probe.py` (или обычным обучением), и выдаёт
плоский набор чисел, которые клиент реально видит на экране и в отчёте:

  * окупаемость канала (`roi`) и вклад канала в продажи (`contribution`, `contribution_pct`) –
    считаются декомпозицией, как в кабинете «Декомпозиция»;
  * коэффициент канала (`beta`), параметры насыщения (`alpha`, `gamma`),
    параметр переноса (`decay`) – из паспорта модели.

Ничего не пишет в проект: декомпозиция вызывается с `save_results=False`.

Пример:
    python Projects/repro_extract_metrics.py ^
        --engine-root sidecar/econometrica ^
        --work-dir <каталог прогона> ^
        --out <файл.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def extract(engine_root: Path, project_dir: Path) -> dict:
    sys.path.insert(0, str(engine_root))
    from engines.decomposer import decompose
    from engines.persistence import load_model_with_compat

    models_dir = project_dir / "models"
    aurora = models_dir / "latest.aurora-model"
    pkl = models_dir / "latest.pkl"
    model_path = aurora if aurora.exists() else pkl
    if not model_path.exists():
        raise SystemExit(f"ОШИБКА: модель не найдена в {models_dir}")

    model_data = load_model_with_compat(model_path)
    channel_params = model_data.get("channel_params", {})
    repro = model_data.get("reproducibility", {}) or {}
    mcmc = (model_data.get("diagnostics", {}) or {}).get("mcmc_settings", {}) or {}

    dec = decompose(str(project_dir), model_path=str(model_path), save_results=False)
    if dec.get("status") == "error":
        raise SystemExit(f"ОШИБКА декомпозиции: {dec}")

    channels = {}
    for ch in dec.get("channels", []):
        name = ch.get("name") or ch.get("channel")
        channels[name] = {
            "roi": ch.get("roi"),
            "contribution": ch.get("contribution"),
            "contribution_pct": ch.get("contribution_pct"),
            # Границы правдоподобного диапазона – нужны, чтобы соотнести расхождение
            # прогонов с собственным разбросом модели, а не только с процентами.
            "roi_ci_low": ch.get("roi_ci_low"),
            "roi_ci_high": ch.get("roi_ci_high"),
            "contribution_ci_low": ch.get("contribution_ci_low"),
            "contribution_ci_high": ch.get("contribution_ci_high"),
        }

    for name, prm in channel_params.items():
        row = channels.setdefault(name, {})
        row["beta"] = prm.get("beta")
        row["alpha"] = prm.get("alpha")
        row["gamma"] = prm.get("gamma")
        row["decay"] = prm.get("decay")
        row["adstock_mean_posterior"] = prm.get("adstock_mean_posterior")

    return {
        "project_dir": str(project_dir),
        "model_path": str(model_path),
        "seed": repro.get("seed") or (model_data.get("config", {}) or {}).get("seed"),
        "mcmc": mcmc,
        "baseline": dec.get("baseline_total") or dec.get("baseline"),
        "channels": channels,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine-root", required=True)
    ap.add_argument("--work-dir", required=True, help="Каталог прогона (внутри – project/models/...).")
    ap.add_argument("--out", default=None, help="Файл для JSON. По умолчанию – печать в вывод.")
    args = ap.parse_args()

    work_dir = Path(args.work_dir).resolve()
    project_dir = work_dir / "project" if (work_dir / "project").exists() else work_dir
    payload = extract(Path(args.engine_root).resolve(), project_dir)

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"[repro_extract_metrics] записано: {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
