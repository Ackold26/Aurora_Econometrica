---
tags: [session, compressed, html-tier1, aurora_html, v1.0.12, tier1-deliverable]
type: session
updated: 2026-04-24
---

# Quick Reference

HTML Tier-1 Overhaul program — comprehensive redesign of Aurora AI interactive HTML deliverable from generic 612-LOC single-theme static to tier-1 MBB-grade 14-section interactive report with 3 themes, inline assets, hash-based CSP, WCAG AA accessibility, and premium micro-interactions. Completed M0-M5 in one extended session. 5 commits + 5 tags, ~5700 LOC net additions across ~25 files.

**Topic:** html-tier1-program
**Version:** v1.0.12 scope (v1.0.11 ship unblocked)
**Plan file:** `C:/Users/ackol/.claude/plans/toasty-sprouting-kahn.md`
**Pre-program anchor:** tag `v1.0.11-pre-html-tier1`

**Milestones:**
- M0 Data recon — 1h — budget what-if viability confirmed
- M1 Foundation (`7a0e4af`) — package skeleton + shared adapter + bundled assets
- M2 Narrative & Layout (`9a757b2`, tag `v1.0.12-html-m2`) — 14 sections + layout.css 900 LOC
- M3 Interactivity & Charts (`a1b2943`, tag `v1.0.12-html-m3`) — 5 ECharts + sortable + drill-down + what-if
- M4 Themes & Polish (`88adcac`, tag `v1.0.12-html-m4`) — WCAG AA 15/15 + haptic + favicon
- M5 Verification (this commit) — brand 30/30 + narrative 35/35 + a11y 15/15

---

## Locked decisions (final)

| # | Decision | Value |
|---|----------|-------|
| D1 | Branding | Aurora AI wordmark only (no "Econometrica") |
| D2 | Themes | 3: light (default, email) / dark / fun |
| D3 | ECharts | common.5.5.1.min.js inline (648 KB, pinned SHA) |
| D4 | PDF | No — that's PPTX's role |
| D5 | Size | ~1 MB total, within 1.2 MB cap |
| D6 | Customization | None, fixed Aurora brand |
| D7 | Interactivity | Maximum — TOC + drill-down + sortable + switcher + what-if + shortcuts + search |
| D8 | Fonts | Inter + Lora WOFF2 subsets (cyrillic+latin, 123 KB) |
| D9 | State | localStorage with sessionStorage + URL param fallback |
| D11 | Renderer | ECharts SVG (crisp any DPI) |
| D12 | CSP | Hash-based (6 SHA-256), NO unsafe-inline |
| D13 | JSON embed | ensure_ascii=True (U+2028/U+2029 defence) |
| D14 | Progressive enhancement | Static HTML readable without JS |
| D15 | Palette sync | Generated aurora_html_tokens.js (single source tokens.json) |
| D16 | A11y | WCAG AA + keyboard nav + ARIA + skip-link + reduced-motion |
| D17 | Performance | FCP <500ms, TTI <2s targets |
| D20 | Trust signals | Report ID SHA-256 + methodology badge + confidentiality watermark |

---

## M0 Data recon findings

Budget what-if slider **FULLY VIABLE** without backend changes:
- `model_data.channel_params[col] = {beta, alpha, gamma, adstock}` — exposed in `modeler.py:583-605`
- `model_data.normalization = {y_mean, y_std, media_means, media_stds}`
- Hill formula portable to JS: `z=spend/mean; sat=z^α/(z^α+γ^α); KPI=baseline + Σ(β·sat)·y_std`
- Auto-loads pickle (`models/latest.pkl`) via new `html_export._try_load_pickle_model`

---

## M1 Foundation (commit `7a0e4af`)

Deliverables:
1. **Shared narrative adapter** `engines/narrative_adapter.py` — promoted `_merge_channels`, `derive_verdict`, `_derive_narrative_facts`, `_map_pipeline_to_builder_data` + new `MAX_CHANNELS_IN_TABLE=10` constant. Zero PPTX regression (43/43 + 14/14 PASS).
2. **pptx_export.py refactored**: 369 → 102 LOC, re-exports adapter.
3. **aurora_html/ package** (8 modules): `__init__` (fail-fast SHA verify), `builder`, `sections`, `charts`, `themes`, `interactive`, `security`, `strings_ru.json`.
4. **Bundled assets**:
   - echarts.common.5.5.1.min.js 648 KB, SHA `66f17003724d5b6c...`
   - Lora WOFF2 cyrillic+latin (57 KB)
   - Inter WOFF2 cyrillic+latin (65 KB)
   - Crimson Pro rejected (no Cyrillic subset на Google Fonts)
5. **Standards/tokens/build.py** extended: `--target html-css` (3 [data-theme] selectors), `--target html-js` (window.AURORA_THEMES palette).
6. **Standards/CLIENT_READY_ANATOMY_HTML.md** — 10-criteria Definition of Done, 14 sections, interactivity contract, 3 themes, a11y, security, performance.
7. **build_sidecar.py** обновлён: `--add-data aurora_html` + `regenerate_tokens --target all`.

---

## M2 Narrative & Layout (commit `9a757b2`, tag `v1.0.12-html-m2`)

**3012 insertions, 6 files.** Full static 14-section deliverable.

- `strings_ru.json` **275 LOC**: 14 sections + SCQAR templates + 5 findings variants + methodology + glossary 24 terms × 3 categories + verdict reasons + UI strings + closing.
- `templates/shell.html` — outer scaffold with CSP hash placeholders, skip-link, scroll progress, sticky header (5 ghost buttons), 240px TOC sidebar + fluid main, footer with Report ID + timestamp, modals (search + shortcuts), drill panel, toast container, `<noscript>` banner.
- `templates/layout.css` **~900 LOC handcrafted** — full component library: header / TOC / sections / findings / key message / charts / commentary / action table / verdict badges / footnotes / SCQAR / recommendations / impact card / methodology / MQS card / glossary / closing / modals / drill panel / toasts. Micro-interactions (section fade staggered, TOC spring `cubic-bezier(0.34, 1.56, 0.64, 1)`, hover gold border slide, shimmer skeleton, scroll progress lime). Print CSS. A11y (focus-visible lime, prefers-reduced-motion).
- `sections.py` **~900 LOC** — 14 render functions, PE compliant, s07 5-branch edge cases mirror PPTX post-audit logic.
- `builder.py` **~370 LOC** — AuroraHTMLBuilder with Report ID SHA-256 hash, asset inlining (6 WOFF2 + 648 KB ECharts + 3 CSS blocks + tokens JS + bootstrap + SVG favicon data URI), **hash-based CSP per block** (3 styles + 3 scripts separately hashed, zero unsafe-inline), @font-face with unicode-range, OG meta tags, Apple touch icon.
- `interactive.py` **~230 LOC** M2 minimal bootstrap — theme resolution chain, TOC scroll-spy, keyboard shortcuts, storage fallback (Safari file:// tolerant).

Smoke 972 KB, 14 sections, zero Econometrica leak, CSP clean.

---

## M3 Interactivity & Charts (commit `a1b2943`, tag `v1.0.12-html-m3`)

**1024 insertions, 5 files.** Full interactive tier-1 experience.

**builder.py** `_chart_data_json` emits 5 payloads (waterfall + mROAS with drill-down details + share + timeline + optimize + scenarios). `_model_context_json` gates what-if via `enabled` flag.

**interactive.py rewrite ~750 LOC single IIFE** — все фичи:
- 5 ECharts SVG renderer (crisp retina/4K)
- Theme-aware palette, re-theme без re-init (smooth setOption)
- Sortable action table (click th, persist localStorage, totals-row pinned bottom)
- Table search filter (debounced)
- Copy CSV (clipboard) + Copy chart as PNG (2× pixel ratio)
- Drill-down side-panel (click chart bar OR table row → slides right)
- Animated number counters (IntersectionObserver, 1.2s easeOutQuart, reduced-motion respected)
- **Budget what-if slider** — Hill saturation in-browser: `z^α/(z^α+γ^α)·β`, per-channel sliders, debounced 120ms, delta % colored, reset button. Gated via MODEL_CTX.enabled.
- Scenario switcher (≥2 scenarios) — dropdown + KPI/lift info
- Fuzzy search Ctrl+K — sections + channels, top 8, click scroll + row highlight

**engines/html_export.py** rewritten 612 → 130 LOC thin wrapper — maps через narrative_adapter, loads pickle automatically for what-if, delegates to aurora_html.build_html.

**server.py** injects `project_dir` into decompose_data so wrapper can locate pickle.

Smoke 1019 KB, CHART_DATA all 5 payloads populated, MODEL_CTX.enabled=true, Cyrillic escaped to `\uXXXX`.

---

## M4 Themes & Polish (commit `88adcac`, tag `v1.0.12-html-m4`)

**155 insertions, 3 files.** Premium polish + WCAG AA.

Gold accent layering per theme:
- light: accent=gold_muted (`#8C7142`, 4.23:1 on white, AA pass); accent-decor=gold_primary (non-text decoration only)
- dark: accent=gold_primary (`#C5A46D`, 8:1 on deep navy, AAA)
- fun: accent=gold_muted, accent-decor=gold_primary

**tools/verify_aurora_html_a11y.py NEW** — parses `[data-theme]` blocks, computes WCAG contrast per theme. **15/15 PASS** after fix (was 14/15 — gold on white failed 3:1).

Favicon upgrade: navy rounded square + gold dashed arc rotated -30° + lime center dot = recognisable Aurora sigil (crisp 16-512px).

interactive.py polish:
- `haptic(ms)` helper `navigator.vibrate(8-12)` on theme cycle + copy-link + drill-down open (prefers-reduced-motion guard)
- applyTheme animated icon rotation + scale(1.1) 320ms on user-initiated
- cycleTheme emits toast with theme name
- openDrillPanel auto-focuses close button (WCAG 2.4.11)
- aria-label updated per theme

---

## M5 Verification (this commit)

**Three new verify tools:**

1. **tools/verify_aurora_html_brand.py** — 30 brand+security+structural invariants:
   Aurora wordmark / no Econometrica / sacred lime / gold / navy /
   Lora / Inter / WOFF2 data URIs / 4+ @font-face / 3 theme selectors /
   inline ECharts (not CDN) / CSP / sha256 hashes / no unsafe-inline /
   frame-ancestors / 14 section ids / skip-link / aria-hidden / lang /
   viewport / Report ID / favicon / OG meta / methodology badge /
   confidentiality / size under 1.2 MB / zero em dashes user-visible.
   **30/30 PASS.**

2. **tools/verify_aurora_html_narrative.py** — 7 scenarios mirror PPTX:
   Case 1 default preview
   Case 2 Kagocel-like synthetic (5 channels, verdict, Cut)
   Case 3 3-channel minimal + wireframe residue checks
   Case 4 10-channel maximal (MAX_CHANNELS_IN_TABLE slice)
   Case 5 empty fallback (meta propagates)
   Case 6 partial diagnostics (no MQS)
   Case 7 no-TV digital-only — **strictest** multi-client safety:
     Yandex Direct / YouTube / Instagram / TikTok; ZERO Kagocel /
     TV FLIGHT / HOLIDAY PUSH / Robyn / LightweightMMM / 286 млн /
     25 млн из TV / Weekly bursts / 80 TRP residue.
   **35/35 PASS.**

3. **tools/verify_aurora_html_a11y.py** (from M4) — **15/15 PASS**.

**Em dash cleanup during M5.1:** brand verify flagged 4 user-visible em dashes (not CJK-context ECharts). Grep found 38 em dashes across 8 files — all in user-facing code as placeholder "—" for null values OR comments. Replaced with hyphen `-` per Aurora rule `feedback_no_em_dash`. Re-verify: 0 em dashes in user-visible, brand 30/30, a11y 15/15, PPTX regression clean.

---

## Aggregate metrics

| Metric | Value | Budget |
|--------|-------|--------|
| HTML total size | 1019 KB | ≤1.2 MB ✅ |
| ECharts bundle | 648 KB | pinned SHA ✅ |
| Fonts inline | 123 KB (6 WOFF2) | ✅ |
| Aurora CSS + layout | ~12 KB | ≤50 KB ✅ |
| Bootstrap JS | ~25 KB | ≤30 KB ✅ |
| 14 sections | all present | 14 ✅ |
| WCAG AA contrast | 15/15 | 15/15 ✅ |
| Brand invariants | 30/30 | ≥25 ✅ |
| Narrative scenarios | 35/35 | ≥28 ✅ |
| PPTX regression | 43/43 + 14/14 | clean ✅ |
| `unsafe-inline` in CSP | 0 | 0 ✅ |
| Em dashes user-visible | 0 | 0 ✅ |
| "Econometrica" substring | 0 | 0 ✅ |

---

## Lessons learned

1. **Hash-based CSP with multi-block hashes.** CSP3 `'sha256-{b64}'` works per-block — we emit 3 script hashes + 3 style hashes. Each inline block hashed separately. Browser refuses any other script. Fundamental XSS defense не relying на perfect escape.

2. **ensure_ascii=True in json.dumps** — must for JS embedding. Defuses U+2028/U+2029 line separators that otherwise break JS string literals. Cost: Cyrillic becomes `\uXXXX` (larger but safer).

3. **Safari file:// localStorage is restricted.** Fallback chain URL param → localStorage → sessionStorage → in-memory keeps theme/sort preference workable.

4. **WCAG AA gold-on-white failing.** `#C5A46D` gold_primary has only 2.36:1 on white — below 3:1 UI minimum. Solution: use `gold_muted` (`#8C7142`, 4.23:1) для text + `gold_primary` только для non-text decoration (bars, hairlines where accessibility doesn't apply).

5. **Crimson Pro lacks Cyrillic subset on Google Fonts.** Russian text falls back to system serif — inconsistent across OS. Switched to Lora (open-source, full Cyrillic support, tier-1 quality).

6. **Adapter refactor = regression hazard mitigated.** Incremental 3-step: copy → verify → remove. Zero PPTX regression across 4 milestones.

7. **WOFF2 data URIs add ~180 KB total to HTML.** Acceptable for premium consistency across all OS. Alternative (system font stack) saves ~180 KB but loses design integrity on Linux/Android.

8. **Em dash discipline across codebase.** Aurora `feedback_no_em_dash` rule applies not just to PPTX narrative but to HTML code, CSS comments, JS comments. Bulk find-replace `—` → `-` after any new content addition. Third-party library bundles (ECharts CJK i18n) exempted.

---

## Known limits documented

- **Single-channel real-client LEAK.** Adapter threshold `len(channels) >= 2` → 1-channel client sees preview/wireframe. My len==1 branch в s07 = dead code в normal pipeline. Deferred to v1.0.13.
- **Live pipeline test pending.** All automated tools PASS but full dev-mode E2E (`npm run tauri dev` → Kagocel XLSX → Report → HTML → Chrome) requires user session with Антон. Checklist prepared separately.
- **Budget what-if uses steady-state approximation.** Full time-series adstock reconstruction deferred to v1.0.13 if clients request.
- **No EN localization.** Scheduled v1.0.13 (RU + EN).

---

## Rollback

- Pre-program: `git tag v1.0.11-pre-html-tier1` on commit `43b3883`.
- Full: `git reset --hard v1.0.11-pre-html-tier1`.
- Partial: delete `aurora_html/` package, revert `engines/html_export.py` to legacy, revert `narrative_adapter.py` inlined back into `pptx_export.py`. Zero impact on PPTX/XLSX.

---

## Ship checklist (M5.4 — для Антона)

1. Regen tokens: `python Standards/tokens/build.py --target all`
2. Rebuild sidecar: `python sidecar/econometrica/build_sidecar.py`
3. Rebuild Tauri: `CARGO_TARGET_DIR=... npm run tauri build`
4. Live-test dev pipeline:
   ```
   npm run tauri dev
   → Kagocel sample XLSX (или любой 2+ channel)
   → Import → Validate → Train → Decompose → Optimize
   → Report → Интерактивный (HTML)
   → Open in Chrome → visual + interactivity QA
   ```
5. Email test: attach HTML → Gmail → download → offline open (inline assets).
6. 3 themes visual QA: ?theme=light/dark/fun → screenshots.
7. Mobile test (iPhone): Apple touch icon + haptic on theme toggle.
8. Verify automation:
   ```
   cd sidecar
   python ../tools/verify_aurora_pptx_narrative.py  # 43/43
   python ../tools/verify_aurora_pptx_brand.py      # 14/14
   python ../tools/verify_aurora_html_brand.py      # 30/30
   python ../tools/verify_aurora_html_narrative.py  # 35/35
   python ../tools/verify_aurora_html_a11y.py       # 15/15
   ```
9. Tag `v1.0.12-html-tier1` (after live-test PASS).
10. Update `rosst-updates/latest.json` + Supabase Storage + GitHub Release.

---

## Post-ship audit (commit `b68cf5b`, +191/-96, 6 files)

Critical self-review after v1.0.12-html-tier1 ship found 8 defects.
All fixed, 137/137 automated checks still PASS.

### Defects found and fixed

1. **XSS defense-in-depth** (interactive.py) — CSP hash-based already
   blocks inline script + event handlers, но 6 innerHTML sites
   concatenated user-controlled channel names без escape. Added
   `escapeHtml()` (textContent round-trip) + `escapeAttr()` helpers.
   Applied to: chart tooltip formatters × 2, drill-down content,
   search results, scenario dropdown, what-if slider rows. Verdict
   class attribute whitelisted `/^[A-Za-z]+$/` against injection.

2. **Drill-panel focus scroll jank** (interactive.py) —
   `closeBtn.focus()` without preventScroll option caused browsers
   to scrollIntoView despite panel being position:fixed. Added
   `{preventScroll: true}` with catch fallback for older engines.

3. **Chart skeleton infinite shimmer without JS** (shell.html) —
   PE baseline was broken. `.chart-skeleton` CSS animation ran
   forever for JS-disabled readers. Added `<noscript><style>`:
   - `.chart-skeleton { display: none !important }`
   - `.chart-host::before` with helpful "требует JS" message
   - `.section { opacity: 1; transform: none; animation: none }`
     override (section fade-in keyframes start at opacity 0)

4. **What-if div-by-zero / NaN propagation** (interactive.py) —
   If media_means[channel] = 0, Hill formula `z = spend / mean`
   produces Infinity, `Math.pow(Infinity, alpha)` = Infinity,
   `sat = Infinity / (Infinity + ga)` = NaN. Propagates to delta %.
   Fixed with 5 guards in `predictKPI`:
     - Skip channel if mean falsy/non-finite/<=0
     - Skip if alpha/gamma invalid
     - Skip if spend <= 0
     - Check sat is finite after Hill computation
     - Return 0 if final KPI non-finite
   Plus outer guard: skip entire what-if UI if currentKPI non-finite.

5. **Adstock silently ignored in what-if** (interactive.py label) —
   Hill-only formula omits adstock decay (theta). Updated helper
   text: "Hill-формуле (приближение без adstock; полная модель - в
   PPTX-отчёте и оптимизаторе)".

6. **ASSET_SHA256 uses 16-char prefix for fonts** (__init__.py) —
   Fonts pinned with 16-char SHA-256 prefix (weaker). Computed full
   64-char digests, switched from `startswith` to exact equality.
   Documented graceful degradation: logs errors, doesn't raise
   (single asset mismatch → report with warning, not HTTP 500).

7. **Dead charts.py + 2 chart containers missing** (sections.py,
   charts.py deleted) — interactive.py initialized `chart-waterfall`
   + `chart-optimize` but sections.py had no DOM hosts → data wasted.
   Added:
     - `chart-waterfall` in render_at_a_glance (below findings list,
       visual decomposition reinforcement)
     - `chart-optimize` in render_recommendation (current vs optimal
       budget bars alongside 3 action numbers)
   Both JS-gated: silently no-op if CHART_DATA block is empty.
   Removed dead charts.py (never imported after M3 moved chart logic
   entirely to JS).

8. **Report ID includes timestamp** (builder.py) — old hash included
   `generated_iso`, making every rebuild produce different ID even
   with identical model output. Clients couldn't verify "this is
   report abc123" across re-exports. Fixed: hash over deterministic
   `(client + project_id + version + sorted channels signature + diag
   rounded to 3 decimals)`. Verified: 3 builds same data → identical
   `aurora-mmm-a2535beec908`.

### Red-team verification

- Determinism: 3 builds with same data produce identical Report ID ✅
- XSS: crafted `<img src=x onerror=...>` channel name — all 6
  occurrences in output live inside JS string literals, safe (JS
  doesn't parse as HTML); escapeHtml converts before DOM innerHTML ✅
- Div-by-zero: `media_means[B] = 0` — no NaN propagation, channel
  skipped correctly ✅
- Empty path: `build_html({}, {}, {})` produces valid 1005 KB HTML ✅

### Final verification after audit

| Suite | Result |
|-------|--------|
| verify_aurora_html_brand     | 30/30 PASS |
| verify_aurora_html_narrative | 35/35 PASS |
| verify_aurora_html_a11y      | 15/15 PASS |
| verify_aurora_pptx_narrative | 43/43 PASS (regression clean) |
| verify_aurora_pptx_brand     | 14/14 PASS (regression clean) |
| **Total**                    | **137/137 PASS** |

### Tag policy

- `v1.0.12-html-tier1` pinned on `3be60e4` (pre-audit ship-ready reference)
- `b68cf5b` audit fixes live past the tag
- During live-test: if all PASS, may re-tag `v1.0.12-html-tier1-audited`
  on `b68cf5b` to signal fully-audited shipment

## Related memory

- `project_client_ready_templates_2026-04-24.md` — program-level M0-M5 log + post-audit
- `feedback_no_em_dash.md` — strict rule (38 em dashes replaced в M5 sweep)
- `feedback_value_perception_tier1.md` — no MCMC time / speedup
- `feedback_online_only_license.md` — license handling (Aurora-wide)
