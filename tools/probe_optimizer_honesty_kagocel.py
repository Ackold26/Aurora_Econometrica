r"""Probe — honesty оптимизатора на реальном pickle Кагоцела (БЕЗ GUI, 0 фитов).

Цель (probe-first, anchor-to-one-real-artifact): доказать ДО строительства M2,
что `engines.optimizer.optimize()` выдаёт совет по переброске бюджета, НЕ
консультируясь с model-уровневой диагностикой надёжности (rHat / дивергенции /
Ratio / MQS-tier / verdict). Реальный Кагоцел сам = adversarial-кейс:
Ratio 1.55:1, MQS 50 «Слабое», verdict «результаты ненадёжны».

Что печатает:
  1. Model-level honesty-сигналы (ОРАКУЛ) из pickle.diagnostics.
  2. optimize() результат: status, lift, converged-флаги, ВСЕ top-level ключи
     (чтобы показать ОТСУТСТВИЕ model-verdict/refusal в выходе оптимизатора).
  3. Вывод гэпа: несёт ли выход оптимизатора «модель ненадёжна»? (ожидаемо — нет).

Run:
    python tools/probe_optimizer_honesty_kagocel.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sidecar"))
sys.path.insert(0, str(ROOT / "sidecar" / "econometrica"))

PROJECT = Path(os.environ["APPDATA"]) / "aurora-econometrica-gui" / "projects" / \
    "кагоцел-рф--данные-для-эконометрики---на-ммх-0706-26"

# Поля выхода optimize(), которые БЫ несли model-уровневую честность, если б были.
MODEL_HONESTY_FIELDS = (
    "model_reliability", "reliability", "verdict", "honesty", "mqs", "ratio",
    "r_hat_max", "divergences", "thin", "thinness", "reliability_verdict",
    "caveat", "caveats", "warnings", "model_warning", "refused", "refusal",
)


def _load_diag() -> dict:
    """Model-уровневая диагностика = SSOT results/model-diagnostics.json.

    NB (находка probe): pickle.mcmc_diagnostics ПУСТ ([]); rHat/divergences/ratio/
    mqs/checks/verdict живут ТОЛЬКО в results/model-diagnostics.json (пишется при
    train/decompose через utils.diagnostics.generate_diagnostics_summary). Поэтому
    M2 verdict-gate обязан консультировать этот файл (или ту же функцию), а не
    pickle. latest-params.json может расходиться (другой snapshot) — не SSOT.
    """
    import json
    f = PROJECT / "results" / "model-diagnostics.json"
    if not f.exists():
        return {}
    return json.load(open(f, encoding="utf-8"))


def main() -> int:
    print("=" * 74)
    print("PROBE — honesty оптимизатора на реальном Кагоцеле (0 фитов)")
    print("=" * 74)

    # ── 1. ОРАКУЛ: model-level honesty из pickle ──────────────────────────
    diag = _load_diag()
    mqs = diag.get("mqs", {}) or {}
    metrics = diag.get("metrics", {}) or {}
    checks = diag.get("checks", {}) or {}
    print("\n[1] МОДЕЛЬ-УРОВЕНЬ (оракул — что модель знает о себе):")
    print(f"    MQS            = {mqs.get('score')} ({mqs.get('tier_label')}), "
          f"raw={mqs.get('raw_score')}, thinness_cap={mqs.get('thinness_cap')}")
    print(f"    Ratio          = {metrics.get('ratio')}  "
          f"(n_obs={metrics.get('n_observations')}, n_params={metrics.get('n_parameters')})")
    print(f"    r_hat_max      = {metrics.get('r_hat_max')}, "
          f"divergences = {metrics.get('divergences')}")
    print(f"    checks         = convergence:{checks.get('convergence')}  "
          f"fit:{checks.get('fit')}  ratio:{checks.get('ratio')}")
    print(f"    verdict        = {diag.get('verdict')}")

    # ── 2. optimize() на реальном проекте ─────────────────────────────────
    from engines.optimizer import optimize
    res = optimize({"min_pct": 50, "max_pct": 150}, str(PROJECT))
    print("\n[2] ВЫХОД optimize(min_pct=50,max_pct=150):")
    print(f"    status                = {res.get('status')}")
    if res.get("status") != "ok" and res.get("status") is not None:
        print(f"    error_code/message    = {res.get('error_code')} / {res.get('message')}")
    print(f"    optimization_converged= {res.get('optimization_converged')}")
    print(f"    converged_at_current  = {res.get('converged_at_current')}")
    lift = res.get("expected_lift_pct", res.get("lift_pct"))
    print(f"    expected_lift_pct     = {lift}")
    print(f"    top-level keys        = {sorted(res.keys())}")

    chs = res.get("channels", []) or []
    if chs:
        print("\n    per-channel (name | action | confidence | mROAS):")
        for c in chs:
            print(f"      {c.get('name','?')[:34]:34}  {str(c.get('action','')):9}  "
                  f"conf={c.get('action_confidence')}  mROAS={c.get('mroi_current')}")

    # ── 3. M2 verdict-gate: несёт ли выход model-уровневую честность? ─────
    # (До M2 здесь не было НИ ОДНОГО поля — гэп. После M2 — model_reliability.)
    mr = res.get("model_reliability")
    ratio_thin = (metrics.get("ratio") or 99) < 4
    conv_bad = checks.get("convergence") is False
    print("\n[3] M2 verdict-gate в выходе optimize():")
    print(f"    модель тонкая (Ratio<4): {ratio_thin}; convergence-check провален: {conv_bad}")
    if not mr:
        print("    => ГЭП НЕ ЗАКРЫТ: model_reliability отсутствует в выходе optimize().")
        return 1
    print(f"    verdict      = {mr.get('verdict')}   refused = {mr.get('refused')}")
    print(f"    caveat_text  = {mr.get('caveat_text')}")
    for r in mr.get("reasons", []):
        print(f"      • {r}")
    # Регрешн-ожидание на реальном Кагоцеле: тонко (Ratio<4) → uncertain, НЕ refuse.
    ok = mr.get("verdict") == "uncertain" and mr.get("refused") is False
    print(f"\n    [регрешн] Кагоцел ожидается uncertain/refused=False: "
          f"{'✓ OK' if ok else '✗ ОТКЛОНЕНИЕ'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
