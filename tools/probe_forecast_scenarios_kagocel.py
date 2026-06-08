r"""Probe: forecast-кривые продаж по сценариям медиаплана (модуль «график прогноза»).

Цель (probe-first ДО UI): доказать, что predict_scenario выдаёт ОСМЫСЛЕННЫЕ
помесячные кривые продаж при РАЗНЫХ медиапланах — основа будущего chart-модуля
(история факт+fit + N прогнозных хвостов на таймлайне).

3 сценария на N=5 месяцев (авг-дек, как слайды РОСТ):
  A «базовый»       — media на уровне среднего последнего года (плоско)
  B «сезонный пик»  — МЕНЯЮЩИЙСЯ помесячный план (рост к декабрю) ← тест: гнётся ли кривая
  C «ноль»          — media=0 ← тест: падение к baseline (intercept)

Проверки:
  (а) B-кривая варьируется (std>0) — НЕ плоская при меняющемся плане
  (б) C ≈ baseline_per_period (только intercept) — числа осмысленны
  (в) шов: predictions[0] сценария A ≈ последнее фактическое KPI (непрерывность история↔прогноз)

Run: python tools/probe_forecast_scenarios_kagocel.py
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sidecar"))
sys.path.insert(0, str(ROOT / "sidecar" / "econometrica"))

PROJECT = Path(os.environ["APPDATA"]) / "aurora-econometrica-gui" / "projects" / \
    "кагоцел-рф--данные-для-эконометрики---на-ммх-0706-26"
N = 5


def main() -> int:
    from engines.persistence import load_model_with_compat
    from engines.scenario import predict_scenario

    md = load_model_with_compat(PROJECT / "models" / "latest.pkl")
    cfg = md["config"]
    media_cols = list(cfg["media_columns"])
    unit_costs = cfg.get("unit_costs", {}) or {}
    kpi_col = cfg["kpi_column"]
    data_file = cfg.get("data_file")
    untrained = (md.get("normalization", {}) or {}).get("untrained_channels", []) or []
    active = [c for c in media_cols if c not in untrained]

    # Исторические уровни media + последнее фактическое KPI (для шва).
    df = pd.read_excel(data_file)
    last_year = df[media_cols].tail(12)
    mean_level = last_year.mean()
    last_kpi = float(df[kpi_col].dropna().iloc[-1])
    hist_mean_kpi = float(df[kpi_col].dropna().tail(12).mean())

    print("=" * 72)
    print("PROBE forecast-сценарии (Кагоцел 0706, KPI =", kpi_col, ")")
    print("=" * 72)
    print(f"Активные каналы ({len(active)}): {[c.split()[0] for c in active]}")
    print(f"Untrained (исключены из плана): {untrained or '—'}")
    print(f"Последнее фактич. KPI: {last_kpi:,.0f} · среднее за год: {hist_mean_kpi:,.0f}")
    print()

    def plan_flat(mult):
        return {c: [float(mean_level[c]) * mult] * N for c in active}

    def plan_seasonal(mults):
        return {c: [float(mean_level[c]) * m for m in mults] for c in active}

    def plan_zero():
        return {c: [0.0] * N for c in active}

    scenarios = {
        "A базовый (уровень истории)": plan_flat(1.0),
        "B сезонный пик к декабрю":    plan_seasonal([0.7, 0.9, 1.2, 1.6, 2.2]),
        "C ноль активности":           plan_zero(),
    }

    results = {}
    for name, plan in scenarios.items():
        r = predict_scenario(
            {"scenario_name": name, "media_plan": plan, "unit_costs": unit_costs},
            str(PROJECT))
        results[name] = r
        if r.get("status") != "ok":
            print(f"[{name}] ERROR {r.get('error_code')}: {r.get('message')}")
            continue
        preds = r.get("predictions") or []
        tot = r.get("totals", {})
        ci_lo = tot.get("predicted_kpi_ci_low")
        ci_hi = tot.get("predicted_kpi_ci_high")
        print(f"--- {name} ---")
        print(f"  кривая помесячно: {[f'{p:,.0f}' for p in preds]}")
        print(f"  total predicted: {tot.get('predicted_kpi'):,.0f}"
              + (f"  CI[{ci_lo:,.0f}..{ci_hi:,.0f}]" if ci_lo is not None else "  CI: n/a")
              + f"  baseline_total: {tot.get('baseline_kpi'):,.0f}  lift: {tot.get('lift_pct')}%")
        print()

    # ── Проверки осмысленности ──
    print("=" * 72)
    print("ПРОВЕРКИ")
    print("=" * 72)
    A = results["A базовый (уровень истории)"]
    B = results["B сезонный пик к декабрю"]
    C = results["C ноль активности"]

    if B.get("status") == "ok":
        bp = np.array(B["predictions"], dtype=float)
        b_std = float(bp.std())
        b_monotone = bool(np.all(np.diff(bp) >= -1e-6))
        print(f"(а) B-кривая ГНЁТСЯ: std={b_std:,.0f} "
              f"({'✓ варьируется' if b_std > 1 else '✗ ПЛОСКАЯ — план не влияет на форму!'}), "
              f"рост к декабрю: {'✓' if b_monotone else 'нет (не моно)'}")

    if C.get("status") == "ok":
        cp = np.array(C["predictions"], dtype=float)
        base_pp = C["totals"]["baseline_kpi"] / max(1, C["n_periods"])
        c_dev = abs(float(cp.mean()) - base_pp) / max(1.0, abs(base_pp))
        print(f"(б) C ноль ≈ baseline: pred_avg={cp.mean():,.0f} vs baseline_pp={base_pp:,.0f} "
              f"(откл {c_dev*100:.1f}% {'✓' if c_dev < 0.1 else '⚠'})")

    if A.get("status") == "ok":
        a0 = float(A["predictions"][0])
        seam_dev = abs(a0 - last_kpi) / max(1.0, abs(last_kpi))
        print(f"(в) ШОВ история↔прогноз: A.pred[0]={a0:,.0f} vs последнее факт={last_kpi:,.0f} "
              f"(разрыв {seam_dev*100:.1f}% {'✓ непрерывно' if seam_dev < 0.25 else '⚠ скачок на стыке'})")
        a_vs_hist = abs(float(np.mean(A['predictions'])) - hist_mean_kpi) / max(1.0, hist_mean_kpi)
        print(f"    A (план=история) ≈ среднее истории: откл {a_vs_hist*100:.1f}% "
              f"{'✓' if a_vs_hist < 0.25 else '⚠'}")

    # Ранжирование: больше медиа → больше продаж?
    if all(r.get("status") == "ok" for r in (A, B, C)):
        ta = A["totals"]["predicted_kpi"]; tb = B["totals"]["predicted_kpi"]; tc = C["totals"]["predicted_kpi"]
        print(f"(г) монотонность: C(ноль)={tc:,.0f} < A(база)={ta:,.0f} < B(пик)={tb:,.0f} "
              f"{'✓ больше медиа → больше продаж' if tc < ta < tb else '⚠ порядок нарушен'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
