"""
Unit tests for compute_roi_verdict (decomposer.py hybrid threshold logic).

Phase 0.2 — plan immutable-bouncing-noodle §0.2 / L4 fix.
Covers:
  1. Posterior CI uncertainty (Step 1)
  2. Absolute hard caps (Step 2): deep loss, loss, breakeven, unit_smell, artifact
  3. Quantile relative mode (Step 3): gated on N >= 20 + portfolio benchmarks
  4. Efficiency gap fallback (Step 4): oversat, underperf, high, good, balanced
  5. Tone enum invariant
  6. Backward compatibility — pre-fix labels still producible

Run from repo root:
    python tools/test_roi_verdict.py
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / "sidecar"
sys.path.insert(0, str(SIDECAR))
sys.path.insert(0, str(SIDECAR / "econometrica"))

from engines.decomposer import compute_roi_verdict


PASSED = 0
FAILED = 0
ALLOWED_TONES = {'good', 'warn', 'bad', 'neutral'}


def _ok(label: str) -> None:
    global PASSED
    PASSED += 1
    print(f"[OK]   {label}")


def _fail(label: str, detail: str = "") -> None:
    global FAILED
    FAILED += 1
    line = f"[FAIL] {label}"
    if detail:
        line += f" - {detail}"
    print(line)


def assert_verdict(label: str, got: tuple[str, str], expected_label: str, expected_tone: str) -> None:
    if got == (expected_label, expected_tone):
        _ok(label)
    else:
        _fail(label, f"got {got!r}, expected ({expected_label!r}, {expected_tone!r})")


def assert_tone(label: str, got: tuple[str, str], expected_tone: str) -> None:
    if got[1] == expected_tone:
        _ok(label)
    else:
        _fail(label, f"got tone {got[1]!r}, expected {expected_tone!r} (label was {got[0]!r})")


# ── Step 1 (L2 refactor 2026-04-29): posterior CI uncertainty as suffix ─────
def test_ci_uncertainty_triggers_when_ci_wider_than_roi():
    # ROI=2.0, CI=[0.5, 3.0] — width=2.5 > 2.0 → suffix appended.
    # Pre-fix: returned 'Высокая неопределённость' (suppressed informative
    # descriptive verdict). Post-fix (L2): keeps base verdict ('Сбалансирован'
    # for ROI=2.0 / gap=0) and appends ' (низкая уверенность)' suffix —
    # honest disclosure без потери informativeness.
    got = compute_roi_verdict(roi=2.0, efficiency_gap=0.0,
                              roi_ci_low=0.5, roi_ci_high=3.0)
    assert_verdict("CI wider than ROI → uncertainty suffix", got,
                   'Сбалансирован (низкая уверенность)', 'neutral')


def test_ci_uncertainty_demotes_good_to_warn():
    # ROI=12.0 (Высокоэффективен → good) + wide CI → suffix + tone demoted к warn
    got = compute_roi_verdict(roi=12.0, efficiency_gap=8.0,
                              roi_ci_low=0.5, roi_ci_high=15.0)
    assert_verdict("Wide CI demotes good→warn", got,
                   'Высокоэффективен (низкая уверенность)', 'warn')


def test_ci_uncertainty_not_triggered_when_ci_narrow():
    # ROI=2.0, CI=[1.8, 2.3] — width=0.5 < 2.0 → fall through to other rules
    got = compute_roi_verdict(roi=2.0, efficiency_gap=0.0,
                              roi_ci_low=1.8, roi_ci_high=2.3)
    assert_verdict("Narrow CI → fall through", got, 'Сбалансирован', 'neutral')


def test_ci_uncertainty_skipped_when_ci_missing():
    # No CI data → skip Step 1 entirely
    got = compute_roi_verdict(roi=0.3, efficiency_gap=0.0)
    assert_verdict("Missing CI → skip uncertainty step", got,
                   'Глубоко убыточный', 'bad')


def test_ci_uncertainty_partial_data_ignored():
    # Only one bound → cannot compute width → skip
    got = compute_roi_verdict(roi=2.0, efficiency_gap=0.0, roi_ci_low=1.5)
    assert_tone("Partial CI ignored", got, 'neutral')


# ── Step 2: absolute hard caps ────────────────────────────────────────────────
def test_deep_loss():
    got = compute_roi_verdict(roi=0.3, efficiency_gap=0.0)
    assert_verdict("ROI 0.3 → Глубоко убыточный", got, 'Глубоко убыточный', 'bad')


def test_loss_boundary():
    got = compute_roi_verdict(roi=0.7, efficiency_gap=0.0)
    assert_verdict("ROI 0.7 → Убыточный", got, 'Убыточный', 'bad')


def test_loss_just_below_threshold():
    # roi=0.5 is boundary: ROI_DEEP_LOSS=0.5, condition is < 0.5
    got = compute_roi_verdict(roi=0.5, efficiency_gap=0.0)
    assert_verdict("ROI 0.5 (boundary) → Убыточный (>=0.5 tier)", got, 'Убыточный', 'bad')


def test_breakeven():
    got = compute_roi_verdict(roi=0.95, efficiency_gap=0.0)
    assert_verdict("ROI 0.95 → На грани окупаемости", got,
                   'На грани окупаемости', 'warn')


def test_unit_smell_high_roi():
    # ROI=80 + unit_smell → "не рубли?"
    got = compute_roi_verdict(roi=80.0, efficiency_gap=0.0, unit_smell=True)
    assert_verdict("ROI 80 + unit_smell → не рубли", got,
                   'ROI завышен (не рубли?)', 'warn')


def test_unit_smell_skipped_when_below_threshold():
    # ROI=20 + unit_smell — below ROI_UNIT_SMELL_FLOOR (50) — fall through
    got = compute_roi_verdict(roi=20.0, efficiency_gap=0.0, unit_smell=True)
    # Fall through to high-roi-money branch — but unit_smell guard блокирует
    # абсолютный 'Высокоэффективен' branch (roi > 5 + not unit_smell). Goes
    # to gap fallback: gap=0 → Сбалансирован.
    assert_verdict("ROI 20 + unit_smell + gap 0 → balanced", got,
                   'Сбалансирован', 'neutral')


def test_artifact_threshold():
    # ROI=150 без unit_smell → artifact warning
    got = compute_roi_verdict(roi=150.0, efficiency_gap=0.0)
    assert_verdict("ROI 150 → артефакт", got,
                   'ROI нереалистичен (артефакт)', 'warn')


def test_artifact_overrides_unit_smell_when_extreme():
    # ROI 60 + unit_smell триггерит unit_smell first (preserved behaviour),
    # т.к. unit_smell label более информативен. Artifact > 100 на крайних tail.
    got = compute_roi_verdict(roi=60.0, efficiency_gap=0.0, unit_smell=True)
    assert_verdict("ROI 60 + unit_smell → не рубли (priority)", got,
                   'ROI завышен (не рубли?)', 'warn')


# ── Step 3: relative quantile (gated on N >= 20) ─────────────────────────────
def _quantiles_brand():
    return {'brand_reach': {'p10': 1.0, 'p25': 1.5, 'p75': 3.0, 'p90': 4.5}}


def test_quantile_mode_active_when_n_geq_20():
    got = compute_roi_verdict(roi=5.0, efficiency_gap=0.0,
                              category='brand_reach',
                              n_channels=25,
                              category_quantiles=_quantiles_brand())
    assert_verdict("N=25, ROI=5 → Top-10% по категории", got,
                   'Top-10% по категории', 'good')


def test_quantile_mode_top_25():
    got = compute_roi_verdict(roi=3.5, efficiency_gap=0.0,
                              category='brand_reach',
                              n_channels=30,
                              category_quantiles=_quantiles_brand())
    assert_verdict("ROI=3.5 → Top-25% по категории", got,
                   'Top-25% по категории', 'good')


def test_quantile_mode_bottom_10():
    # roi=1.05 — выше absolute breakeven (1.0) но ниже p10 (1.0) — wait, p10=1.0 → roi must be < 1.0
    # ROI=1.05 → выше p10 → значит проходит к p25 check (1.5) → Bottom-25%
    got = compute_roi_verdict(roi=1.05, efficiency_gap=0.0,
                              category='brand_reach',
                              n_channels=30,
                              category_quantiles=_quantiles_brand())
    assert_verdict("ROI=1.05 → Bottom-25% (выше p10, ниже p25)", got,
                   'Bottom-25% по категории', 'warn')


def test_quantile_mode_average():
    got = compute_roi_verdict(roi=2.0, efficiency_gap=0.0,
                              category='brand_reach',
                              n_channels=30,
                              category_quantiles=_quantiles_brand())
    assert_verdict("ROI=2 → Средний по категории", got,
                   'Средний по категории', 'neutral')


def test_quantile_mode_skipped_when_n_lt_20():
    got = compute_roi_verdict(roi=6.0, efficiency_gap=0.0,
                              category='brand_reach',
                              n_channels=10,
                              category_quantiles=_quantiles_brand())
    # N=10 < 20 → quantiles ignored → step 4 fallback: roi > 5 not unit_smell → high
    assert_verdict("N=10 → quantile skipped, абсолютный fallback", got,
                   'Высокоэффективен', 'good')


def test_quantile_mode_skipped_without_benchmarks():
    got = compute_roi_verdict(roi=6.0, efficiency_gap=0.0,
                              category='brand_reach',
                              n_channels=30,
                              category_quantiles=None)
    # No quantiles → step 4 fallback: roi > 5 → high
    assert_verdict("No benchmarks → quantile skipped", got,
                   'Высокоэффективен', 'good')


def test_quantile_mode_skipped_for_unknown_category():
    got = compute_roi_verdict(roi=6.0, efficiency_gap=0.0,
                              category='unknown_category',
                              n_channels=30,
                              category_quantiles=_quantiles_brand())
    # Category not in benchmarks → fall through
    assert_verdict("Unknown category → quantile skipped", got,
                   'Высокоэффективен', 'good')


# ── Step 4: efficiency gap fallback ──────────────────────────────────────────
def test_high_absolute_roi_money_channel():
    got = compute_roi_verdict(roi=6.5, efficiency_gap=0.0, unit_smell=False)
    assert_verdict("ROI 6.5 (money) → Высокоэффективен", got,
                   'Высокоэффективен', 'good')


def test_oversaturated_gap():
    got = compute_roi_verdict(roi=1.5, efficiency_gap=-15.0)
    assert_verdict("Gap -15 → Перенасыщен", got, 'Перенасыщен', 'warn')


def test_underperf_gap():
    got = compute_roi_verdict(roi=1.5, efficiency_gap=-7.0)
    assert_verdict("Gap -7 → Слабее своей доли", got,
                   'Слабее своей доли', 'warn')


def test_high_gap():
    got = compute_roi_verdict(roi=1.5, efficiency_gap=12.0)
    assert_verdict("Gap +12 → Высокоэффективен (gap)", got,
                   'Высокоэффективен', 'good')


def test_good_gap():
    got = compute_roi_verdict(roi=1.5, efficiency_gap=7.0)
    assert_verdict("Gap +7 → Эффективен", got, 'Эффективен', 'good')


def test_balanced():
    got = compute_roi_verdict(roi=1.5, efficiency_gap=0.0)
    assert_verdict("Gap 0 → Сбалансирован", got, 'Сбалансирован', 'neutral')


def test_balanced_minor_gap():
    got = compute_roi_verdict(roi=1.5, efficiency_gap=2.0)
    assert_verdict("Gap +2 → Сбалансирован", got, 'Сбалансирован', 'neutral')


# ── Tone enum invariant ──────────────────────────────────────────────────────
def test_tone_always_in_enum():
    cases = [
        # (roi, gap, kwargs)
        (0.1, 0.0, {}),
        (0.5, 0.0, {}),
        (0.95, 0.0, {}),
        (1.5, 0.0, {}),
        (1.5, -15.0, {}),
        (1.5, 12.0, {}),
        (6.0, 0.0, {}),
        (60.0, 0.0, {'unit_smell': True}),
        (150.0, 0.0, {}),
        (2.0, 0.0, {'roi_ci_low': 0.0, 'roi_ci_high': 5.0}),
    ]
    bad = []
    for roi, gap, kwargs in cases:
        _, tone = compute_roi_verdict(roi=roi, efficiency_gap=gap, **kwargs)
        if tone not in ALLOWED_TONES:
            bad.append((roi, gap, kwargs, tone))
    if not bad:
        _ok("All cases produce tone ∈ {good, warn, bad, neutral}")
    else:
        _fail("Tone enum invariant", f"violations: {bad}")


# ── Backward compatibility: pre-fix labels still producible ──────────────────
def test_backward_compat_labels():
    """Все pre-fix verdict labels всё ещё producible с тем же смыслом."""
    # 'Убыточный' — preserved (roi < 0.8)
    assert_verdict("compat: Убыточный", compute_roi_verdict(roi=0.7, efficiency_gap=0.0),
                   'Убыточный', 'bad')
    # 'На грани окупаемости' — preserved (0.8 <= roi < 1.0)
    assert_verdict("compat: На грани", compute_roi_verdict(roi=0.95, efficiency_gap=0.0),
                   'На грани окупаемости', 'warn')
    # 'Перенасыщен' — preserved (gap <= -10)
    assert_verdict("compat: Перенасыщен", compute_roi_verdict(roi=1.5, efficiency_gap=-15.0),
                   'Перенасыщен', 'warn')
    # 'Слабее своей доли' — preserved
    assert_verdict("compat: Слабее", compute_roi_verdict(roi=1.5, efficiency_gap=-7.0),
                   'Слабее своей доли', 'warn')
    # 'Высокоэффективен' — preserved (gap >= 10)
    assert_verdict("compat: Высокоэффективен по gap",
                   compute_roi_verdict(roi=1.5, efficiency_gap=12.0),
                   'Высокоэффективен', 'good')
    # 'Эффективен' — preserved (gap >= 5)
    assert_verdict("compat: Эффективен", compute_roi_verdict(roi=1.5, efficiency_gap=7.0),
                   'Эффективен', 'good')
    # 'Сбалансирован' — preserved (default neutral)
    assert_verdict("compat: Сбалансирован", compute_roi_verdict(roi=1.5, efficiency_gap=0.0),
                   'Сбалансирован', 'neutral')
    # 'ROI завышен (не рубли?)' — preserved (roi > 50 + unit_smell)
    assert_verdict("compat: не рубли", compute_roi_verdict(roi=80.0, efficiency_gap=0.0,
                                                            unit_smell=True),
                   'ROI завышен (не рубли?)', 'warn')


# ── Drop-in replacement smoke (decompose pipeline) ───────────────────────────
def test_compute_roi_verdict_signature_compatibility():
    """compute_roi_verdict callable с positional + keyword args в порядке,
    в котором decomposer.py его вызывает."""
    # Mimics call site: keyword-only after roi/efficiency_gap
    got = compute_roi_verdict(
        roi=2.0,
        efficiency_gap=3.0,
        category='mixed',
        unit_smell=False,
        roi_ci_low=None,
        roi_ci_high=None,
        n_channels=5,
        category_quantiles=None,
    )
    assert_tone("Decomposer call site OK", got, 'neutral')


def main() -> int:
    print("── Step 1: posterior CI uncertainty ──")
    test_ci_uncertainty_triggers_when_ci_wider_than_roi()
    test_ci_uncertainty_demotes_good_to_warn()
    test_ci_uncertainty_not_triggered_when_ci_narrow()
    test_ci_uncertainty_skipped_when_ci_missing()
    test_ci_uncertainty_partial_data_ignored()

    print("\n── Step 2: absolute hard caps ──")
    test_deep_loss()
    test_loss_boundary()
    test_loss_just_below_threshold()
    test_breakeven()
    test_unit_smell_high_roi()
    test_unit_smell_skipped_when_below_threshold()
    test_artifact_threshold()
    test_artifact_overrides_unit_smell_when_extreme()

    print("\n── Step 3: relative quantile ──")
    test_quantile_mode_active_when_n_geq_20()
    test_quantile_mode_top_25()
    test_quantile_mode_bottom_10()
    test_quantile_mode_average()
    test_quantile_mode_skipped_when_n_lt_20()
    test_quantile_mode_skipped_without_benchmarks()
    test_quantile_mode_skipped_for_unknown_category()

    print("\n── Step 4: efficiency gap fallback ──")
    test_high_absolute_roi_money_channel()
    test_oversaturated_gap()
    test_underperf_gap()
    test_high_gap()
    test_good_gap()
    test_balanced()
    test_balanced_minor_gap()

    print("\n── Tone enum invariant ──")
    test_tone_always_in_enum()

    print("\n── Backward compatibility ──")
    test_backward_compat_labels()

    print("\n── Decomposer call-site compatibility ──")
    test_compute_roi_verdict_signature_compatibility()

    total = PASSED + FAILED
    print(f"\n{PASSED}/{total} assertions passed.")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
