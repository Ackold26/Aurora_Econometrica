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


def _next_months(last: str, n: int) -> list[str]:
    """Продолжить помесячный таймлайн вперёд от last на n точек ('YYYY-MM')."""
    p = pd.Period(str(last), freq="M")
    return [str(p + i + 1) for i in range(n)]


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
        band_lo = r.get("predictions_ci_low")
        band_hi = r.get("predictions_ci_high")
        if band_lo and band_hi:
            print(f"  CI-веер low:  {[f'{v:,.0f}' for v in band_lo]}")
            print(f"  CI-веер high: {[f'{v:,.0f}' for v in band_hi]}")
        else:
            print("  CI-веер per-period: n/a (posterior недоступен)")
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

    # ── (д) per-period CI-веер: low ≤ pred ≤ high по каждому месяцу, ширина осмысленна ──
    print()
    print("ВЕЕР (per-period CI band — питает MultiScenarioChart):")
    for name, r in results.items():
        if r.get("status") != "ok":
            continue
        lo = r.get("predictions_ci_low"); hi = r.get("predictions_ci_high"); pr = r.get("predictions")
        if not (lo and hi and pr):
            print(f"  [{name}] band отсутствует — chart покажет линию без ленты (graceful)")
            continue
        bad_order = [t for t in range(len(pr)) if not (lo[t] - 1 <= pr[t] <= hi[t] + 1)]
        widths = [(hi[t] - lo[t]) / max(1.0, abs(pr[t])) for t in range(len(pr))]
        w_avg = sum(widths) / len(widths)
        widens = widths[-1] >= widths[0] - 1e-9
        print(f"  [{name.split()[0]}] low≤pred≤high: "
              f"{'✓ все ' + str(len(pr)) if not bad_order else '✗ нарушено на ' + str(bad_order)}"
              f" · ширина ~{w_avg*100:.0f}% от прогноза"
              f" · {'расширяется к концу ✓' if widens else 'сужается (проверить)'}"
              f" · положит.: {'✓' if all(l >= 0 for l in lo) else '⚠ есть отрицат. нижняя'}")

    # ── (е) сборка baseline-история + хвост + непрерывность шва/дат (data-path chart) ──
    print()
    print("СБОРКА ТАЙМЛАЙНА (decompose-история + прогнозный хвост):")
    from engines.decomposer import decompose as _decompose
    dec = _decompose(str(PROJECT))
    if dec.get("status") != "ok":
        print(f"  decompose ERROR: {dec.get('message')}")
        return 0
    ts = dec.get("time_series", {}) or {}
    hist_dates = list(ts.get("dates", []) or [])
    base_ts = list(ts.get("baseline", []) or [])
    chans = ts.get("channels", {}) or {}
    # Проверка утверждения агента: ключ 'kpi_values' в time_series?
    print(f"  ключи time_series: {sorted(ts.keys())} "
          f"(агент заявлял 'kpi_values' — {'ЕСТЬ' if 'kpi_values' in ts else 'НЕТ, реконструируем fit=baseline+Σканалы'})")
    # fit-история = baseline + Σ медиа (in-sample prediction; гладкая линия для шва, не сырой факт)
    fit_hist = []
    for t in range(len(hist_dates)):
        v = float(base_ts[t]) if t < len(base_ts) else 0.0
        for arr in chans.values():
            if t < len(arr):
                v += float(arr[t])
        fit_hist.append(round(v, 0))
    print(f"  история: {len(hist_dates)} мес, dates[0]={hist_dates[0] if hist_dates else '—'} "
          f"… dates[-1]={hist_dates[-1] if hist_dates else '—'}")
    yp = list(md.get("y_predicted", []) or [])
    if yp and len(yp) == len(fit_hist):
        dev = float(np.max(np.abs(np.array(yp) - np.array(fit_hist))) / max(1.0, float(np.mean(np.abs(yp)))))
        print(f"  fit(baseline+Σканалы) == y_predicted(pickle): макс.откл {dev*100:.2f}% "
              f"{'✓ совпало' if dev < 0.02 else '⚠ расходится — для baseline брать y_predicted напрямую'}")
    else:
        print(f"  y_predicted(pickle): len={len(yp)} vs fit len={len(fit_hist)} "
              f"{'(несовпадение длин — использовать fit-реконструкцию)' if yp else '(нет в pickle — использовать fit-реконструкцию)'}")

    # Источник baseline ДЛЯ ФРОНТА (у него нет pickle, но есть decomposition_series).
    # Код decomposer.py:1165 утверждает baseline_reduced+Σфакторы+Σмедиа==total.
    ds = dec.get("decomposition_series", {}) or {}
    ds_series = ds.get("series", []) or []
    ds_dates = list(ds.get("dates", []) or [])
    if ds_series:
        n = len(ds_dates)
        ds_total = [0.0] * n
        for s in ds_series:
            d = s.get("data", []) or []
            for t in range(min(n, len(d))):
                ds_total[t] += float(d[t])
        roles = [s.get("role") for s in ds_series]
        print(f"  decomposition_series: {len(ds_series)} серий, роли={roles}")
        if yp and len(yp) == n:
            dev2 = float(np.max(np.abs(np.array(yp) - np.array(ds_total))) / max(1.0, float(np.mean(np.abs(yp)))))
            print(f"  Σ decomposition_series == y_predicted(pickle): макс.откл {dev2*100:.2f}% "
                  f"{'✓ — фронт baseline = Σ decomposition_series.data' if dev2 < 0.02 else '⚠ расходится, иной источник'}")

    # Хвост сценария на УРОВНЕ последних 3 мес (УРОК: гладкий дефолт-шов)
    last3 = df[media_cols].tail(3).mean()
    level_plan = {c: [float(last3[c])] * N for c in active}
    rl = predict_scenario({"scenario_name": "level", "media_plan": level_plan, "unit_costs": unit_costs}, str(PROJECT))
    fc = list(rl.get("predictions") or [])
    if fc and hist_dates:
        fc_dates = _next_months(hist_dates[-1], N)
        combined = hist_dates + fc_dates
        seam = abs(fc[0] - fit_hist[-1]) / max(1.0, abs(fit_hist[-1]))
        dup = len(combined) != len(set(combined))
        mono = all(str(combined[i]) < str(combined[i + 1]) for i in range(len(combined) - 1))
        print(f"  хвост (план=уровень посл.3 мес): fc={[f'{v:,.0f}' for v in fc]}")
        print(f"  ШОВ fit↔прогноз: fit[-1]={fit_hist[-1]:,.0f} → fc[0]={fc[0]:,.0f} "
              f"(разрыв {seam*100:.1f}% {'✓ непрерывно' if seam < 0.25 else '⚠ скачок'})")
        print(f"  ДАТЫ: {len(combined)} точек ({hist_dates[-1]} → {fc_dates[0]}…{fc_dates[-1]}), "
              f"дублей нет: {'✓' if not dup else '✗'}, строго возр.: {'✓' if mono else '✗'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
