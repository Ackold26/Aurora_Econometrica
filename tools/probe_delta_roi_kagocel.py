r"""Probe #6d ΔROI / OVB-guardrail на реальном pickle Кагоцела — БЕЗ GUI.

Цель (ритм probe-first): доказать математику Δ ROI ДО строительства UI.
Два режима:

  (по умолчанию, 0 фитов — дёшево):
    Декомпозирует существующий pickle, считает per_control_contraction по 12 авто-
    праздникам + 2 user-контролям, печатает ROI-снимок 5 медиаканалов «до» и
    список неинформативных праздников (contraction<0.1 → кандидаты на удаление
    БЕЗ omitted-variable bias).

  --retrain (1 Bayesian фит — дорого, минуты):
    Ретрейнит config + disabled_holidays=[неинформативные] на исходном xlsx,
    декомпозирует новый pickle, печатает Δ ROI каждого медиаканала и OVB-флаг
    (|Δ ROI| велик у информативного контроля = был confounding; у неинформативного
    Δ≈0 = удаление безопасно).

Run:
    python tools/probe_delta_roi_kagocel.py            # дёшево (contraction + ROI до)
    python tools/probe_delta_roi_kagocel.py --retrain  # полный ΔROI (фит)

Project (APPDATA): кагоцел-рф…0706-26 (MQS 70). Pickle уже обучен с 12 holidays.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sidecar"))
sys.path.insert(0, str(ROOT / "sidecar" / "econometrica"))

PROJECT = Path(os.environ["APPDATA"]) / "aurora-econometrica-gui" / "projects" / \
    "кагоцел-рф--данные-для-эконометрики---на-ммх-0706-26"

CONTRACTION_THRESHOLD = 0.1  # <0.1 → неинформативный (SSOT diagnostics.per_control_contraction)


def _load_pickle():
    from engines.persistence import load_model_with_compat
    return load_model_with_compat(PROJECT / "models" / "latest.pkl")


def _contraction_table(md) -> dict:
    """per_control_contraction из готового pickle (0 фитов).

    Зеркалит VERBATIM путь recompute_mqs.posterior_sd_from_samples (SSOT):
    control_betas хранится shape (n_controls, draws) → SD по axis=1.
    Не свой reshape (даёт ложную кучность из-за перемешивания осей).
    """
    from utils.diagnostics import per_control_contraction, prior_sds_for_bayesian
    sys.path.insert(0, str(ROOT / "sidecar" / "econometrica" / "tools"))
    from recompute_mqs import posterior_sd_from_samples  # SSOT extract
    cfg = md["config"]
    prior_sd = prior_sds_for_bayesian(
        gammas_alpha=float(cfg.get("gammas_alpha", 3)),
        gammas_beta=float(cfg.get("gammas_beta", 3)))
    post_sd = posterior_sd_from_samples(md["posterior_samples"], prior_sd.keys())
    return per_control_contraction(
        post_sd.get("control_betas"), prior_sd.get("control_betas"),
        cfg.get("control_columns") or [])


def _decompose(project_dir: str) -> list[dict]:
    """ROI-снимок 5 медиаканалов через тот же движок, что и приложение."""
    from engines.decomposer import decompose
    res = decompose(str(project_dir))
    chs = res.get("channels", [])
    return [{"name": c["name"], "roi": c.get("roi"),
             "roi_ci_low": c.get("roi_ci_low"), "roi_ci_high": c.get("roi_ci_high"),
             "contribution_pct": c.get("contribution_pct")} for c in chs]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrain", action="store_true", help="полный ΔROI (1 Bayesian фит)")
    args = ap.parse_args()

    md = _load_pickle()
    cfg = md["config"]

    # ── Дёшево: contraction по контролям ──────────────────────────────
    contraction = _contraction_table(md)
    holidays = {k: v for k, v in contraction.items() if k.startswith("holiday_")}
    uncontrolled = sorted([k for k, v in contraction.items() if v < CONTRACTION_THRESHOLD])
    informative = sorted([k for k, v in contraction.items() if v >= 0.3])

    print("=" * 72)
    print("PROBE #6d — per_control_contraction (0 фитов, из готового pickle)")
    print("=" * 72)
    for name, c in sorted(contraction.items(), key=lambda kv: kv[1]):
        tag = "  НЕИНФОРМАТИВЕН (<0.1)" if c < CONTRACTION_THRESHOLD else \
              ("  информативен (≥0.3)" if c >= 0.3 else "")
        print(f"  {c:5.3f}  {name}{tag}")
    print()
    print(f"Кандидаты на удаление БЕЗ OVB (contraction<{CONTRACTION_THRESHOLD}): "
          f"{len(uncontrolled)} из {len(contraction)}")
    for h in uncontrolled:
        print(f"    - {h}")
    print(f"Информативные (удаление = OVB-смещение media-ROI): {informative or '—'}")

    # ── ROI-снимок «до» ───────────────────────────────────────────────
    roi_before = _decompose(PROJECT)
    print()
    print("ROI-снимок «до» (5 медиаканалов):")
    for c in roi_before:
        print(f"    {c['roi']:>8.3f}  {c['name']}")

    if not args.retrain:
        print()
        print("[дёшево] Готово без фитов. Для полного ΔROI: --retrain "
              f"(отключит {len(uncontrolled)} неинформативных праздников, 1 Bayesian фит).")
        return 0

    # ── Дорого: ретрейн с disabled_holidays + ΔROI ────────────────────
    if not uncontrolled:
        print("\n[--retrain] Нет неинформативных праздников — отключать нечего. Стоп.")
        return 0

    src_xlsx = cfg.get("data_file")
    if not src_xlsx or not Path(src_xlsx).exists():
        print(f"\n[--retrain] Исходный xlsx недоступен: {src_xlsx!r}. Стоп.")
        return 2

    print("\n" + "=" * 72)
    print(f"PROBE #6d --retrain: disabled_holidays={uncontrolled} (1 Bayesian фит, минуты)")
    print("=" * 72)

    from engines.modeler import train_model
    retrain_cfg = dict(cfg)
    # pickle.config.control_columns содержит ИНЖЕКТИРОВАННЫЕ holiday_* (modeler добавил
    # их в control_cols при обучении). Для ретрейна нужны только ОРИГИНАЛЬНЫЕ user-
    # контроли — holidays modeler сгенерит из даты заново, disabled_holidays пропустит
    # нужные. Иначе валидация падает MISSING_CONTROL_COLUMNS (их нет в xlsx).
    # ← урок для UI #6: фронт тоже шлёт control_columns БЕЗ holiday_* на ретрейн.
    retrain_cfg["control_columns"] = [c for c in (cfg.get("control_columns") or [])
                                      if not c.startswith("holiday_")]
    retrain_cfg["disabled_holidays"] = uncontrolled
    with tempfile.TemporaryDirectory() as td:
        proj2 = Path(td)
        (proj2 / "models").mkdir(parents=True, exist_ok=True)
        (proj2 / "results").mkdir(exist_ok=True)
        res = train_model(retrain_cfg, str(proj2))
        if res.get("status") != "ok":
            print(f"[--retrain] train failed: {res.get('error_code')}/{res.get('message')}")
            return 3
        roi_after = _decompose(proj2)

    print("\nΔ ROI медиаканалов (после удаления неинформативных праздников):")
    after_by_name = {c["name"]: c for c in roi_after}
    max_abs_delta = 0.0
    for cb in roi_before:
        ca = after_by_name.get(cb["name"])
        if not ca or cb["roi"] is None or ca["roi"] is None:
            continue
        d = ca["roi"] - cb["roi"]
        max_abs_delta = max(max_abs_delta, abs(d))
        print(f"    {cb['roi']:>8.3f} → {ca['roi']:>8.3f}   Δ={d:+8.3f}  {cb['name']}")
    print()
    print(f"max |Δ ROI| = {max_abs_delta:.3f}")
    print("OVB-интерпретация: неинформативные праздники → Δ ROI≈0 (удаление безопасно). "
          "Большой Δ у медиа = удалённый контроль был confounder (НЕ удалять).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
