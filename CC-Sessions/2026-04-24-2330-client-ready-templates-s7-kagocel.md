---
tags: [session, compressed, client-ready-templates, aurora_pptx, kagocel-cleanup, multi-client-safety]
type: session
updated: 2026-04-24
---

# Quick Reference

Session S7 of Client-Ready Templates — hunt down residual Kagocel / TV / Digital video / Robyn / LightweightMMM leaks that surfaced for real clients regardless of supplied channels/facts. 4 LEAKs identified and fixed with data-driven slot-fills; flight annotations gated behind preview_mode. Verification extended with Case 7 "no-TV client" (Yandex Direct / YouTube / Instagram / TikTok). 43/43 narrative PASS, 14/14 brand PASS, cargo clean.

**Topic:** client-ready-templates-s7-kagocel
**Commit:** `be3d689` on master
**Tag:** `v1.0.11-s7-kagocel-cleanup`
**Key files:**
- `sidecar/econometrica/aurora_pptx/builder.py` (+95/-46 net)
- `tools/verify_aurora_pptx_narrative.py` (+45/-0)

**Status:**
- ✅ Phase 1 audit — 4 LEAKs classified (s07 title, s07 footnotes, s08 bands, s10 note)
- ✅ Phase 2 fixes — all 4 data-driven or gated behind preview_mode
- ✅ Phase 3 verification — Case 7 no-TV client added, 20 leak assertions strictest
- ✅ Phase 4 red-team + verify + commit + tag
- 🎯 **Next: Session D user-attended ship v1.0.11** (6-8h) — bump versions, rebuild sidecar+Tauri+NSIS, RDP CLOUDEAI live-test, GH Release + Supabase + rosst-updates

---

## Classification rubric applied

Every hardcoded mention grepped across builder.py / pptx_export.py / report.rs / ReportStep.svelte / verify scripts triaged into:

1. **STATIC-OK** — generic template text, safe for all clients (methodology formulas, limitations glossary). Not touched.
2. **FALLBACK-OK** — activates only in preview mode (`data=None` or `len(channels) < 2`). Preserved for dev/demo.
3. **LEAK** — user-visible for real clients with ≥2 channels. MUST FIX.

report.rs / pptx_pipeline.py / ReportStep.svelte — clean (zero hits). All LEAKs localized in builder.py.

## The 4 LEAKs found

### L1. s07 action title (line 1245 pre-fix)

**Before:** `"Пять каналов генерируют 87% продаж - остальные рекомендованы к консолидации"` — hardcoded, shown unconditionally.

**After:** data-driven top-N computation. Sort channels by contribution desc, accumulate until ≥85% of total, emit `"{top_n} канал(ов) генерируют {pct}% продаж - остальные рекомендованы к консолидации"`. When all channels cover 100% (no others), switch to `"Портфель из {N} канал(ов) сбалансирован - все активно работают"`. Kagocel fallback preserved in `else` branch.

### L2. s07 footnotes (lines 1391-1395 pre-fix)

**Before:** 3 hardcoded notes about TV / Social / Print — appeared even with real channels.

**After:** generated from flagged channels (`verdict in ("Reduce", "Cut")`), matching the footnote numbers already assigned in `_build_action_table_rows`. Verdict-specific reasons:
- Cut: "ниже breakeven по mROAS; рекомендовано остановить или перевести в другие каналы."
- Reduce: "saturation-bound; мargin от дополнительного рубля ниже портфельного среднего."

Empty-flagged fallback = single informational note "Все каналы портфеля в рабочем диапазоне mROAS..."

### L3. s08 band chart (lines 1471-1544 pre-fix) — main hotspot

**Before:** hardcoded 6-band stack (Baseline + TV + Digital video + Search + OOH + Social) with specific heights calibrated to Kagocel pilot; W06/W11 hardcoded "TV FLIGHT . 95 TRP/нед" and "HOLIDAY PUSH . DIGITAL" annotations; TV-specific 1.6× seasonal multiplier.

**After:** when `self.channels` present, build bands from top-5 contributors sorted by contribution desc, share-proportional heights scaled into channel_h_budget=1.10" (sum × peak modulation stays under area_h=2.6"). Brand palette cycles `[gold, deep_80, deep_60, deep_40, deep_20, deep_20]`. Leader seasonal modulation generic (sin-based, `0.95 + 0.15 * sin(w_idx/4.2 + 0.7)`) rather than Kagocel-specific flight spikes. Flight annotations gated behind `preview_mode = not self.channels` — real clients see clean stacked bands, per-week peak detection deferred to XLSX "Динамика" sheet (documented trade-off).

### L4. s10 methodology bottom note (line 1888 pre-fix)

**Before:** `"Приоры: Robyn, LightweightMMM + 12 FMCG-проектов Aurora (2024-2026)."` — competitor MMM tools named directly.

**After:** `"Приоры: 12+ FMCG-проектов Aurora (2024-2026) + индустриальные бенчмарки Bayesian MMM."` Still positions Aurora within industry standard without naming specific competitors (per acceptance criteria).

---

## Verification harness updates

### Case 7 "no-TV client" added

Digital-only 4-channel scenario to exercise strictest multi-client safety:
```python
channels = [
    ("Yandex Direct", 40, 78,  1.95, 70),  # hero (highest mROAS)
    ("YouTube",       35, 55,  1.57, 58),
    ("Instagram",     22, 30,  1.36, 28),
    ("TikTok",        18, 22,  1.22, 20),
]
```

Leak list (asserted NOT in XML): Kagocel, KAGOCEL, `"TV"`, `>TV<`, Digital video, Print, Radio, OOH, TV FLIGHT, HOLIDAY PUSH, 286 млн, 25 млн из TV, Weekly bursts, Robyn, LightweightMMM, 80 TRP, 1.8x. 20 assertions — ALL PASS.

### W06/W11 tuning

Originally spec asked to assert no "W06"/"W11" leaks. Reality-check: those substrings appear as generic x-axis week labels W01..W13 in every scenario — not Kagocel flight annotations. Substituted the actual Kagocel-specific strings "TV FLIGHT" / "HOLIDAY PUSH" which are the gated-behind-preview annotations. Correct semantic check.

### cp1251 console survival

Windows PowerShell / cmd default encoding cp1251 cannot encode Unicode `×` (U+00D7). Initial check label `"1.8×"` crashed UnicodeEncodeError on print(). Two fixes:
1. `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` at top of script.
2. Check label swapped to plain ASCII `"1.8x"`.

Lesson: dev tools that emit to stdout need utf-8 forcing on Windows cp1251 OR strictly ASCII-only labels.

---

## Self-audit findings (resolved)

### Em dash in added comments

Ran `git diff HEAD | grep -E "^\+" | grep -c "—"` → 3 hits in my own comment lines. Per `feedback_no_em_dash.md` rule, em dash forbidden in all Aurora artifacts including code comments. Fixed:
- 5 comments in builder.py replaced `—` → `-`
- 3 comments in verify_aurora_pptx_narrative.py replaced `—` → `-`

Final diff check: 0 em dashes. Lesson reinforced: the rule covers comments, not just deliverables/memory/chat.

---

## Technical insights

1. **hash() % N for palette jitter.** Used `hash(name) % 7` as seed for non-leader band modulation to avoid all bands moving in lockstep. Python's hash is negative-safe through `math.sin` (signed float input accepted). Doesn't need `abs()`.

2. **Band height budget calibration.** Original hardcoded pilot: baseline 0.85 + TV 0.55×1.6(peak) + 4 small channels summing ~0.71 = ~2.45 ≤ 2.6" area_h. New real-data: baseline 0.85 + channel budget 1.10 × leader 1.10(peak) = ~2.10, safer margin for arbitrary channel count. Verified geometric correctness before commit.

3. **Footnote pairing invariant.** `_build_action_table_rows` assigns footnote numbers 1..3 based on order of first 3 flagged channels. New footnote generator must use same ordering to keep row superscripts consistent with bottom-block text. Matched by iterating `self.channels` in same order (not re-sorting) and filtering same verdicts.

4. **Preview mode flag.** `preview_mode = not self.channels` cleanly separates the "wireframe / demo / unit-test" path from real-data path for s08. Single boolean gates both seasonal modulation choice and annotation visibility — more maintainable than 2 separate `if self.channels` checks.

5. **Plural-agnostic Russian.** "канал(ов)" is the idiomatic hedge in Russian UI text when channel count is dynamic (1/2/5 = разные окончания). Avoids three-branch numeral agreement logic without looking awkward.

---

## Diff scope

- builder.py: 4 localized edits within existing slide methods, no new helpers added. Net +95/-46.
- verify_aurora_pptx_narrative.py: 1 new Case 7 block (22 lines) + stdout reconfigure (4 lines). Net +45/-0.
- 0 new files, 0 deletions of methods.

Pre-existing code (s04/s05/s06/s02/s09 slot-fills from Session C) untouched — they were already LEAK-free, just scoped behind `if self.facts and self.channels`.

---

## Remaining residual Kagocel (by design)

All remaining hardcoded Kagocel references are in explicit fallback branches:
- `self.client` default `"Kagocel"` (meta=None)
- s02 findings else-branch
- s04 takeaway else-branch
- s05 key message else-branch
- s06 chart bars + commentary else-branch
- s07 action table rows + totals else-branch
- s07 footnotes else-branch (NEW)
- s07 title else-branch (NEW)
- s08 title else-branch + flight annotations behind preview_mode (NEW)
- s09 SCQAR + actions else-branch

For `len(channels) >= 1` pipeline run, all real slides render with real data. Dev/wireframe-mode (`build_pptx()` no args) still produces full Kagocel pilot deck for visual QA.

---

## Rollback

Pre-S7 anchor: `v1.0.11-s6-narrative` (or commit `6e39c9c` post-audit hardening). `git reset --hard v1.0.11-s6-narrative`.

---

## Related memory

- `project_client_ready_templates_2026-04-24.md` — program-level S4/B/C/S7 status
- `feedback_no_em_dash.md` — em dash rule applies to code comments too
- `feedback_value_perception_tier1.md` — no MCMC time / speedup in deliverables
