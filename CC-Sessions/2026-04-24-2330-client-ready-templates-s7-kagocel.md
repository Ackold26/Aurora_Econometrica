---
tags: [session, compressed, client-ready-templates, aurora_pptx, kagocel-cleanup, multi-client-safety]
type: session
updated: 2026-04-24
---

# Quick Reference

Session S7 of Client-Ready Templates — hunt down residual Kagocel / TV / Digital video / Robyn / LightweightMMM leaks that surfaced for real clients regardless of supplied channels/facts. 4 LEAKs identified and fixed with data-driven slot-fills; flight annotations gated behind preview_mode. Verification extended with Case 7 "no-TV client" (Yandex Direct / YouTube / Instagram / TikTok). 43/43 narrative PASS, 14/14 brand PASS, cargo clean.

**Topic:** client-ready-templates-s7-kagocel
**Commits:** `be3d689` (initial S7 cleanup) + `85d21f6` (post-audit hardening, 7 defects)
**Tag:** `v1.0.11-s7-kagocel-cleanup` (on `be3d689`; post-audit fixes live on HEAD past the tag)
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
- Reduce: "saturation-bound; маржинальный возврат от дополнительного рубля ниже среднего по портфелю."

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

## Post-audit hardening (commit `85d21f6`)

After tagging `v1.0.11-s7-kagocel-cleanup` the user asked for a critical
self-review of all S7 work. I found 7 defects and fixed them in a single
follow-up commit.

### Defects found and fixed

1. **Typo `мargin`** (Cyrillic м + Latin argin) in s07 Reduce footnote reason.
   Fix: rewrote as "маржинальный возврат от дополнительного рубля ниже
   среднего по портфелю." Clean Russian, no mixed-script, no em dash.

2. **Non-deterministic s08 band jitter.** My S7 commit used
   `hash(name) % 7` for band seasonal modulation phase. Python's built-in
   hash() is salted with PYTHONHASHSEED on every process start, so each
   build produced different modulation phases. Verified via 3 separate
   processes: outer PPTX SHA differed in 1/3 runs before fix. Fix:
   replaced with `zlib.crc32(name.encode('utf-8')) % 7` - deterministic
   across processes. Slide XML SHA256 now identical across 3 runs
   (`55b5f198...`). Outer PPTX SHA still varies due to python-pptx's
   save-time stamp in `docProps/core.xml`; that's out of scope.

3. **Footnote orphan (pre-existing Session C bug + my S7 inheritance).**
   `_build_action_table_rows` filtered flagged channels (verdict ∈
   {Reduce, Cut}) from the full `channels` list, but the row loop only
   renders `channels[:10]`. A channel at index 15+ with Cut verdict
   would get a footnote text in the bottom block but no superscript in
   any rendered row. My S7 s07 footnote generator inherited the same
   pattern. Fix: both now filter within `channels[:10]` before the
   verdict filter. Row ↔ footnote pairing now invariant.

4. **s07 action title grammar.** My S7 used lazy `канал(ов) генерируют`.
   Replaced with 5 idiomatic Russian branches:
   - all-zero contributions → "Вклад каналов требует пересчёта - проверьте
     входные данные" (was: claimed "0% продаж" with "сбалансирован" -
     contradictory!)
   - len=1 → "Один канал портфеля обеспечивает 100% продаж" (was:
     misleading "сбалансирован - все активно работают")
   - top_n=1 dominant → "Один канал даёт X% продаж - остальные
     рекомендованы к консолидации"
   - top_n>1 with others → "Топ-N каналов дают X% продаж..."
   - top_n=len all active → "Все каналы портфеля активно работают..."

5. **Em dash in user-visible s02 Finding 4 (pre-existing Session C).**
   `f"Из {len} активных каналов — чёткий verdict по каждому"` - em dash
   missed by post-audit `6e39c9c`. Fixed.

6. **Em dash in adapter log message** (pptx_export.py). `"channel(s) —
   falling back"` - logs are Aurora output too per rule. Fixed.

7. **Em dash in my own S7 comment** `be3d689`. Replaced `—` with
   parentheses in the `channels[:10]` slice-pair explanation.

### Why red-team matters (reflection)

This session set a high bar: Session B+C post-audit found 8 defects in my
own work, so I expected S7 to need a similar pass. It did. Key lessons:

- **`hash()` non-determinism is invisible unless tested.** A single
  successful build doesn't prove reproducibility. Always spot-check
  SHA256 across 2+ processes when adding any hash-based logic.
- **Plural-agnostic hacks (`канал(ов)`) look professional-ish in dev
  but fail tier-1 delivery standards.** Enumerate the 3-5 real cases
  (N=1, N>1 dominant, N>1 balanced, edge) and write each explicitly.
- **Filter-slice mismatches are easy to miss.** When filtering from
  list A and iterating over list A[:K], always filter within A[:K].
- **Em dash checks need a full diff pass, not just text I added.**
  Pre-existing em dashes in slot-fill templates leak to final output;
  the `6e39c9c` post-audit should have caught line 561 but didn't
  because grep was scoped to my diff.

### Known limits documented for Session D

- **Single-channel real-client LEAK.** Adapter threshold
  `if len(channels) >= 2` triggers full Kagocel fallback for 1-channel
  clients (log: "pptx_export adapter: only 1 channel(s) - falling back
  to Kagocel narrative defaults"). Edge case but real. My len==1
  branch in s07 is dead code through the normal pipeline path; it
  only fires for direct builder invocation. Two options for Session D
  or v1.0.12:
  - Lower threshold to `< 1` and let builder slot-fills handle it.
    `_derive_narrative_facts` is safe for len==1 (hero=leader, no
    div-by-zero). But narrative templates assume `hero != leader`
    comparison semantics, so output quality suffers.
  - Add informational fallback slide: "Single-channel portfolio -
    MMM comparison requires ≥2 channels." Cleaner UX but scope.

- **python-pptx save-time timestamps.** `docProps/core.xml` gets
  fresh `<dcterms:created>` / `<dcterms:modified>` on every save, so
  outer PPTX SHA varies across builds even with identical inputs.
  Slide content is deterministic (verified). Byte-identical builds
  would require patching core.xml post-save or a python-pptx patch.
  Not worth the effort in pilot scope.

### Verification after post-audit

- `verify_aurora_pptx_narrative.py` 43/43 PASS (no regressions from
  grammar changes; title text doesn't break leak assertions).
- `verify_aurora_pptx_brand.py` 14/14 PASS.
- `cargo check` 0 warnings.
- Slide XML SHA256 identical across 3 processes (`55b5f198...`).

## Related memory

- `project_client_ready_templates_2026-04-24.md` — program-level S4/B/C/S7 status
- `feedback_no_em_dash.md` — em dash rule applies to code comments AND user-visible slot-fill text
- `feedback_value_perception_tier1.md` — no MCMC time / speedup in deliverables
