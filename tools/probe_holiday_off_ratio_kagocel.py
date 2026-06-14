r"""Probe — демонстрация ценности мастер-флага use_holidays на реальном Кагоцеле.

Гипотеза (мотивация фичи 2026-06-13): отключение праздников убирает ~12 контролей →
n_params падает → Ratio (степени свободы) растёт. Вопрос: флипнет ли это M2-вердикт
Кагоцела uncertain→reliable (связь двух фич сессии)?

Делает 1 Bayesian retrain (use_holidays=False) на исходном xlsx, сравнивает Ratio/MQS/
M2-вердикт «до» (12 праздников) и «после» (без праздников).

Run: python tools/probe_holiday_off_ratio_kagocel.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sidecar"))
sys.path.insert(0, str(ROOT / "sidecar" / "econometrica"))

PROJECT = Path(os.environ["APPDATA"]) / "aurora-econometrica-gui" / "projects" / \
    "кагоцел-рф--данные-для-эконометрики---на-ммх-0706-26"


def _diag_summary(diag: dict, tag: str) -> None:
    from utils.optimizer_honesty import model_reliability_verdict
    mqs = diag.get("mqs", {}) or {}
    metrics = diag.get("metrics", {}) or {}
    checks = diag.get("checks", {}) or {}
    mr = model_reliability_verdict(diag)
    print(f"  [{tag}]")
    print(f"    Ratio={metrics.get('ratio')}  n_params={metrics.get('n_parameters')}  "
          f"eff_params={metrics.get('effective_parameters')}")
    print(f"    MQS={mqs.get('score')} ({mqs.get('tier_label')})  "
          f"checks.ratio={checks.get('ratio')}  checks.convergence={checks.get('convergence')}")
    print(f"    M2 verdict = {mr.get('verdict')}  refused={mr.get('refused')}")


def main() -> int:
    print("=" * 74)
    print("PROBE — use_holidays=False raises Ratio? (реальный Кагоцел, 1 retrain)")
    print("=" * 74)

    from engines.persistence import load_model_with_compat
    md = load_model_with_compat(PROJECT / "models" / "latest.pkl")
    cfg = md["config"]

    # ── ДО: текущая диагностика (с 12 праздниками) ─────────────────────────
    before = json.load(open(PROJECT / "results" / "model-diagnostics.json", encoding="utf-8"))
    print("\nДО (12 праздников как контроли):")
    _diag_summary(before, "before")

    src_xlsx = cfg.get("data_file")
    if not src_xlsx or not Path(src_xlsx).exists():
        print(f"\n[стоп] Исходный xlsx недоступен: {src_xlsx!r}")
        return 2

    # ── retrain с use_holidays=False ──────────────────────────────────────
    print("\nRetrain с use_holidays=False (1 Bayesian фит, минуты)...")
    from engines.modeler import train_model
    from engines.decomposer import decompose
    retrain_cfg = dict(cfg)
    # holiday_* инжектились в control_columns при обучении — для чистого ретрейна
    # оставляем только ОРИГИНАЛЬНЫЕ user-контроли (modeler перегенерил бы holidays,
    # но use_holidays=False это запрещает).
    retrain_cfg["control_columns"] = [c for c in (cfg.get("control_columns") or [])
                                      if not c.startswith("holiday_")]
    retrain_cfg["use_holidays"] = False
    retrain_cfg["disabled_holidays"] = []
    print(f"  user-контролей осталось: {retrain_cfg['control_columns']}")

    with tempfile.TemporaryDirectory() as td:
        proj2 = Path(td)
        (proj2 / "models").mkdir(parents=True, exist_ok=True)
        (proj2 / "results").mkdir(exist_ok=True)
        res = train_model(retrain_cfg, str(proj2))
        if res.get("status") != "ok":
            print(f"[стоп] train failed: {res.get('error_code')}/{res.get('message')}")
            return 3
        decompose(str(proj2))
        after = json.load(open(proj2 / "results" / "model-diagnostics.json", encoding="utf-8"))

    print("\nПОСЛЕ (без праздников):")
    _diag_summary(after, "after")

    # ── Итог ──────────────────────────────────────────────────────────────
    rb = (before.get("metrics") or {}).get("ratio")
    ra = (after.get("metrics") or {}).get("ratio")
    print("\n" + "=" * 74)
    print(f"ИТОГ: Ratio {rb} → {ra}  "
          f"({'ВЫРОС ✓' if (ra or 0) > (rb or 0) else 'не вырос ✗'})")
    from utils.optimizer_honesty import model_reliability_verdict
    vb = model_reliability_verdict(before).get("verdict")
    va = model_reliability_verdict(after).get("verdict")
    print(f"M2 verdict: {vb} → {va}  "
          f"({'ФЛИП к надёжности ✓' if va == 'reliable' and vb != 'reliable' else 'без флипа'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
