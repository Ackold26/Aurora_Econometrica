---
tags: [session, compressed, html-tier1, aurora_html, v1.0.12, post-audit, ship-ready]
type: session
updated: 2026-04-24
---

# Quick Reference

Marathon session: planned + executed complete HTML Tier-1 overhaul program (M0 data recon → M5 ship) + post-ship critical audit finding 8 additional defects, all fixed. **137/137 automated checks PASS.** Program artefacts fully captured in comprehensive `2026-04-24-2330-html-tier1-program.md` — this file is compressed pointer + session-specific notes.

**Topic:** html-tier1-complete-all-phases
**Key files (primary artefacts):**
- `sidecar/econometrica/aurora_html/` (NEW package, 8 modules)
- `sidecar/econometrica/engines/narrative_adapter.py` (NEW, promoted from pptx_export)
- `sidecar/econometrica/engines/html_export.py` (REWRITE 612→130 LOC thin wrapper)
- `sidecar/econometrica/engines/pptx_export.py` (REFACTOR 369→102 LOC thin wrapper)
- `Standards/tokens/build.py` (+ html-css + html-js targets)
- `Standards/CLIENT_READY_ANATOMY_HTML.md` (NEW spec)
- `tools/verify_aurora_html_{brand,narrative,a11y}.py` (NEW 3 verify suites)

**Status:**
- ✅ M0-M5 program complete
- ✅ Post-ship audit 8 defects fixed
- ✅ 137/137 automated checks PASS
- ✅ 7 commits + 5 tags on master
- 🎯 Awaiting live-test with user (dev pipeline → Chrome → email attach test)

**Primary session log:** `CC-Sessions/2026-04-24-2330-html-tier1-program.md` — covers full M0-M5 + post-audit appendix in detail.

---

## Learnings

### Architecture lessons

1. **JS-side chart configs beat Python charts.py.** Initial design had Python `charts.py` emit ECharts JSON. Actually moving all chart logic into JS (`interactive.py`) gave single source of truth for theme-aware palettes (JS reads `window.AURORA_THEMES` directly), easier re-theme on toggle, eliminated Python-JS data plumbing for static config.

2. **Adapter refactor via incremental 3-step works.** copy → verify → remove kept zero PPTX regression through 7 commits of HTML program. Pattern: new `narrative_adapter.py` created with functions copied verbatim, PPTX still works, then `pptx_export.py` rewritten as re-exporter.

3. **String.Template with shell.html scales.** HTML scaffold stays readable as plain HTML file. Python just substitutes 20+ placeholders. Beat raw f-string concatenation for maintainability.

### Security + a11y lessons

4. **Hash-based CSP multi-block is viable.** CSP3 `'sha256-{b64}'` supports multiple hashes per directive — we emit 3 style + 3 script hashes in single meta. Zero `unsafe-inline` achievable. Browser refuses any script not matching hashes.

5. **`ensure_ascii=True` defuses U+2028/U+2029 XSS.** JSON embedding in JS context is safe once Cyrillic (and everything non-ASCII) is escaped to `\uXXXX`. Cost: file size grows ~5% due to escape sequences.

6. **Defense-in-depth still matters after CSP.** Post-audit found 6 innerHTML sites concatenating channel names without escape. CSP blocks <script> injection but not all DOM-structure attacks (unclosed tags, attribute breakout). Added `escapeHtml()` / `escapeAttr()` JS helpers with textContent round-trip.

7. **WCAG AA gold-on-white is tricky.** `#C5A46D` gold_primary has 2.36:1 on white — below 3:1 UI minimum. Solution: 2-tier accent system (`accent` for text = gold_muted `#8C7142` at 4.23:1, `accent-decor` for bars/hairlines = gold_primary where contrast irrelevant).

8. **Crimson Pro lacks Cyrillic on Google Fonts.** Switched to Lora (open-source, full Cyrillic, tier-1 quality). Lesson: check font subsets BEFORE committing to design system typography.

9. **Safari file:// localStorage restricted.** Storage wrapper must fallback: `localStorage → sessionStorage → URL param → in-memory`. Theme + sort preferences now work across attach/email scenarios.

### Numerical safety lessons

10. **Hill formula in browser needs 5 guards.** `z = spend / media_mean` produces Infinity if mean=0. Math.pow chain propagates to NaN. Must check: mean > 0, alpha > 0, gamma > 0, spend > 0, final sat finite. Plus outer guard on baseline KPI itself.

11. **Deterministic hash must exclude time.** Report ID hashing `timestamp` means every rebuild produces new ID — clients can't verify "same report". Stable input: `(client + project_id + version + sorted channels sig + rounded diagnostics)`.

12. **zlib.crc32 > built-in hash() for stability.** Python's `hash(str)` is PYTHONHASHSEED-salted, different per process. For reproducible build outputs, use `zlib.crc32(name.encode('utf-8')) % N` — same across processes.

### Process lessons

13. **Red-team after ship = 8 more defects.** Ran critical audit after tagging M5 ship-ready. Found XSS defense gaps, div-by-zero, dead code, wasted payloads. Pattern holds: each milestone benefits from ≥1 dedicated audit pass.

14. **Em dash discipline is non-local.** Bulk find-replace needed 38 em dashes → hyphens across 8 files. Third-party ECharts CJK i18n exempted via wider-context heuristic in verify script.

15. **PE baseline is overlooked until tested.** Chart skeletons animated forever without JS. Section fade-in trapped content invisible. Both fixed via `<noscript><style>` overrides. Always test with JS disabled before ship.

---

## Decisions

### Locked during this session

**Architectural:**
- D3: ECharts common.5.5.1.min.js inline (648KB pinned SHA)
- D8: Lora + Inter WOFF2 cyrillic+latin subsets embedded as data URIs
- D11: ECharts SVG renderer (crisp any DPI)
- D12: Hash-based CSP, zero unsafe-inline
- D14: Progressive enhancement baseline mandatory
- D15: Tokens → JS module for ECharts theme sync
- D17: Performance budget FCP<500ms TTI<2s

**Product:**
- Single Aurora AI brand, no Econometrica in output
- 3 themes: light (default email-friendly), dark, fun
- 14 sections mirror PPTX S7 narrative
- Report ID = SHA-256 of deterministic data signature (no timestamp)
- Live-test = user-attended session with Антон (10-step checklist)

**Tag policy:**
- `v1.0.12-html-tier1` pinned on `3be60e4` (M5 ship)
- Audit fixes `b68cf5b` live past the tag
- Future retag option: `v1.0.12-html-tier1-audited` on `b68cf5b` after live-test

### Deferred

- **Live-test** — user-attended, pending Antoн's availability
- **Single-channel LEAK** — `len(channels) >= 2` threshold; deferred v1.0.13
- **EN localization** — deferred v1.0.13
- **Adstock in what-if** — steady-state approximation only; full time-series reconstruction deferred v1.0.13 if requested
- **Screenshot diff regression** — deferred; manual visual QA sufficient for pilot
- **Ship v1.0.11 stable** — blocked separately; HTML program was orthogonal and did not gate v1.0.11

---

## Pending

### Before v1.0.12 release

1. Live-test with Антон:
   - `npm run tauri dev` → Kagocel sample XLSX
   - Full pipeline: Import → Validate → Train → Decompose → Optimize → Report
   - Click "Интерактивный (HTML)" export button
   - Open in Chrome → verify all 14 sections, 3 theme toggle, drill-down,
     sortable table, search Ctrl+K, budget what-if slider (if pickle found)
   - Email test: Gmail attach → download → offline open
   - iPhone Safari test (Apple touch icon + haptic on theme cycle)

2. After live-test PASS:
   - Regen tokens: `python Standards/tokens/build.py --target all`
   - Rebuild sidecar: `python sidecar/econometrica/build_sidecar.py`
   - Rebuild Tauri + NSIS installer
   - Upload to Supabase Storage + GitHub Release
   - Update `rosst-updates/latest.json`
   - Optional re-tag `v1.0.12-html-tier1-audited` on HEAD if desired

3. v1.0.11 ship (separate, already prepared):
   - Unblocked by HTML program — PPTX/XLSX unchanged
   - Session D checklist in earlier memory

### v1.0.13 roadmap

- EN localization (strings_en.json)
- Single-channel narrative support (threshold `< 1`)
- Full adstock time-series reconstruction in what-if (if client requests)
- Screenshot diff regression suite (Playwright)
- Mobile bottom-sheet TOC (vs current hamburger)

---

## Full Session Notes

### Session structure

This session spanned the complete HTML Tier-1 Overhaul program execution plus critical post-ship audit. See primary session log `CC-Sessions/2026-04-24-2330-html-tier1-program.md` for:

- Full M0-M5 milestone-by-milestone deliverables
- Per-milestone LOC counts
- Complete locked decisions table (D1-D20)
- Detailed lessons (8 items)
- Known limits documentation
- 10-step ship checklist
- Rollback runbook
- Post-ship audit appendix with all 8 defects + red-team verification

### Session-specific additions (not in primary log)

**Post-audit commit `b68cf5b` + session-log appendix commit `65ec26f`:**
- interactive.py: added `escapeHtml()` / `escapeAttr()` helpers
- interactive.py: 6 innerHTML sites updated to use escape helpers
- interactive.py: verdict class-attr whitelist `/^[A-Za-z]+$/`
- interactive.py: drill-panel focus `{preventScroll: true}` with catch
- interactive.py: what-if 5 guards (mean / alpha / gamma / spend / sat finite)
- interactive.py: adstock disclaimer in what-if label
- shell.html: noscript CSS override (skeleton + section animation + panels)
- __init__.py: full 64-char SHA-256 for all assets + exact match + docstring
- sections.py: added chart-waterfall container in findings section
- sections.py: added chart-optimize container in recommend section
- charts.py: DELETED (never imported after M3)
- builder.py: Report ID hash uses deterministic channel/diag signature

**Red-team tests executed:**
- Determinism: 3 builds with same data → same ID `aurora-mmm-a2535beec908`
- XSS: crafted `<img src=x onerror=alert(1)>` channel name; escape verified
- Div-by-zero: `media_means[B] = 0` → channel correctly skipped, no NaN
- Empty path: `build_html({}, {}, {})` → valid 1005 KB HTML

**Final 137/137 verification:**
- verify_aurora_html_brand: 30/30 PASS
- verify_aurora_html_narrative: 35/35 PASS (7 scenarios incl strict no-TV Case 7)
- verify_aurora_html_a11y: 15/15 PASS (WCAG AA across light/dark/fun)
- verify_aurora_pptx_narrative: 43/43 PASS (regression clean through all refactors)
- verify_aurora_pptx_brand: 14/14 PASS (regression clean)

### Files modified (aggregate M0 → post-audit)

**New files:**
- `sidecar/econometrica/aurora_html/__init__.py`
- `sidecar/econometrica/aurora_html/builder.py`
- `sidecar/econometrica/aurora_html/sections.py`
- `sidecar/econometrica/aurora_html/themes.py`
- `sidecar/econometrica/aurora_html/interactive.py`
- `sidecar/econometrica/aurora_html/security.py`
- `sidecar/econometrica/aurora_html/strings_ru.json`
- `sidecar/econometrica/aurora_html/templates/shell.html`
- `sidecar/econometrica/aurora_html/templates/layout.css`
- `sidecar/econometrica/aurora_html/templates/echarts.common.5.5.1.min.js`
- `sidecar/econometrica/aurora_html/templates/fonts/*.woff2` (6 files)
- `sidecar/econometrica/engines/narrative_adapter.py`
- `Standards/CLIENT_READY_ANATOMY_HTML.md`
- `tools/verify_aurora_html_brand.py`
- `tools/verify_aurora_html_narrative.py`
- `tools/verify_aurora_html_a11y.py`
- `CC-Sessions/2026-04-24-2330-html-tier1-program.md` (primary log)

**Generated (gitignored):**
- `sidecar/econometrica/aurora_html/templates/aurora_html.css`
- `sidecar/econometrica/aurora_html/templates/aurora_html_tokens.js`

**Modified:**
- `sidecar/econometrica/engines/html_export.py` (612 → 130 LOC)
- `sidecar/econometrica/engines/pptx_export.py` (369 → 102 LOC)
- `sidecar/econometrica/server.py` (project_dir injection)
- `sidecar/econometrica/build_sidecar.py` (--add-data aurora_html)
- `Standards/tokens/build.py` (html-css + html-js targets)
- `.gitignore` (HTML generated artefacts)

**Deleted:**
- `sidecar/econometrica/aurora_html/charts.py` (dead code after M3)

### Errors & workarounds encountered

- **cp1251 console UnicodeEncodeError** — Windows default Python stdout
  cannot encode `×` / `₽` / CJK. Fix: `sys.stdout.reconfigure(encoding='utf-8', errors='replace')` at top of verify scripts.
- **ECharts Chinese i18n em dashes** — bundled min.js contains `其数据是——`
  Chinese tooltip defaults. Our em dash rule excludes third-party bundles
  via CJK-context heuristic in verify.
- **Google Fonts CSS2 without UA returns TTF** — must send Chrome UA header
  to get WOFF2 URLs.
- **Lora cyrillic subset missing on first attempt** — Crimson Pro had no
  Cyrillic subset. Switched fonts mid-M1 with zero rework elsewhere.
- **Import paths on Windows bash** — `sys.path.insert(0, 'econometrica')`
  must use forward slashes; cp1251 parent process quotes behave differently.

### Related memory

- `project_client_ready_templates_2026-04-24.md` — program index with M0-M5 + post-audit sections
- `MEMORY.md` — updated index reflecting final state (137/137, 7 commits, 5 tags)
- `feedback_no_em_dash.md` — strict rule applied (38 em dashes swept)
- `feedback_value_perception_tier1.md` — no MCMC time / speedup in deliverable
- `feedback_online_only_license.md` — Aurora-wide policy respected
