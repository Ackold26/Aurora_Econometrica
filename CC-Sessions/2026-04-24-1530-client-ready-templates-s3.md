---
tags: [session, compressed, client-ready-templates, aurora_pptx, wireframe, audit]
type: session
updated: 2026-04-24
---

# Quick Reference

Session 3 of Client-Ready Templates program (D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica + Standards/). Master wireframe finalized (13 slides, 73.4 KB) через 60+ iterative fixes с Антоном; M3 builder ported в aurora_pptx; post-audit found 2 ship-blockers fixed in-session.

**Topic:** client-ready-templates-s3
**Key files:**
- `D:/Docs/Aurora_Ai/Standards/templates/wireframe.pptx` (final, 73.4 KB, 13 slides)
- `D:/Docs/Aurora_Ai/Standards/templates/build_wireframe.py` (master reference, ~1800 LOC)
- `D:/Docs/Aurora_Ai/Standards/tokens/tokens.json` + `build.py` (SSOT tokens)
- `D:/Docs/Aurora_Ai/Standards/CLIENT_READY_ANATOMY.md` (M1 spec)
- `D:/Docs/Aurora_Ai/Standards/SESSION_AUDIT_2026-04-24.md` (findings report, 12 KB)
- `Dev/Aurora_Econometrica/sidecar/econometrica/aurora_pptx/builder.py` (1861 LOC)
- `Dev/Aurora_Econometrica/sidecar/econometrica/aurora_pptx/__init__.py` (build_pptx orchestrator)
- `Dev/Aurora_Econometrica/sidecar/econometrica/build_sidecar.py` (PyInstaller + regen tokens)

**Status:**
- ✅ Wireframe v3 finalized (13 slides, iterative review with Antonov complete)
- ✅ aurora_pptx.build_pptx() working (smoke test: 13 slides, 75 KB)
- ✅ Audit complete, C1/C2 ship-blockers fixed
- 🎯 **Next:** Session 4 M4 refactor pptx_export.py (7-10h) — parametrize builder (A2 CRITICAL first task)
- 🔒 Hybrid v1.0.11 release frozen до Session 5

**Commits (Aurora_Econometrica master):** `bba9a8b` → `3af07b2` → `8837f3d`

**Tags:** `v1.0.11-pre-templates`, `v1.0.11-m3-builder-ready`, `v1.0.11-s3-audited`

---

## Learnings

### Technical insights

1. **python-pptx ограничения (C1-C4 audit):**
   - НЕ может создавать slide masters programmatically (`prs.slide_masters` read-only). Поэтому M3 pivot от real .potx template в "template-equivalent via code" (builder class с inline primitives).
   - `shape.name` read-only — нельзя программно переименовать placeholders, используется `placeholder_format.idx`.
   - Theme XML только через ZIP + `xml.etree` — нет API. Сделано в `build_blank_theme.py` (12 color slots injected).
   - `add_chart()` creates absolute-positioned GraphicFrame — не binds к chart placeholder.

2. **Georgia+Arial легальны для embed в client deliverables:** Standards/01_TYPOGRAPHY_COLOR.md утверждает что Windows/Office EULA покрывает embed Microsoft Core Web Fonts в deliverables от лицензионной системы. **Override моё начальное Crimson Pro+Inter решение** — Georgia/Arial/Consolas pre-installed Windows/macOS/iOS/Android ~99% юзеров; Crimson Pro + Inter не pre-installed нигде.

3. **Value-perception principle (Antonov):** в tier-1 client deliverables **НЕ показывать** MCMC time / processing time / speedup metrics — девальвирует воспринимаемую ценность. Клиент платит за качество выводов и методологическую строгость, не за compute efficiency. McKinsey/BCG/Bain никогда не включают compute stats в reports. Saved as global feedback rule `feedback_value_perception_tier1.md`.

4. **Grep ≠ fact-check** (lesson from Hybrid rc1 wrong-file incident, reinforced): Explore-агент нашёл phantom path `src-tauri/sidecar/econometrica/engines/pptx_export.py` который не существовал (real: `sidecar/econometrica/engines/...`). Всегда `ls`-verify перед commit. Applied в audit.

5. **Em dash prohibition:** "—" запрещено во всех текстах Aurora (memory, deliverables, code comments). Только "-" (hyphen). Правило Антона 2026-04-24. Saved as `feedback_no_em_dash.md`.

6. **Template compression trade-offs:** Safe zones 0.4" → 0.25"/0.20" = +0.35" content space (+10%). Требует careful positioning для избежания overlap с footer/logo zones.

7. **PyInstaller gotcha:** Gitignored generated files нужны в bundle с `--add-data` + pre-step regeneration. Легко забыть (мы забыли — C1 audit finding).

### Tier-1 design patterns applied

- **One gold accent per slide** (strict discipline): scattered gold = amateur; focused gold = professional.
- **Pull quotes Georgia italic 18-20pt** с gold vertical bar — killer pattern для key takeaways.
- **Section dividers с mini-takeaway** (не просто номер+имя) — tier-1 differentiator.
- **SCQAR** (Situation/Complication/Question/Answer/Recommendation) > SCR. Question block gets gold accent.
- **Methodology + Limitations** — explicit "what model does NOT do" signals rigor.
- **Closing slide не technical colophon** — inspirational brand statement + CTA + narrative (Antonov redesign).
- **Sources/footnotes в bottom-left quadrant** (width ≤8.3", не full), прижаты max к footer hairline. Single bottom hairline (не double).
- **Line-spacing=1.0 для headings.** Narrative body gets 1.3-1.5.
- **Middle dot "·"** bullets вместо ".".
- **No arrows на charts** where tick markers suffice (избегать line clutter).

---

## Decisions

### D-series (pre-session, reference)
- **D1:** i18n strings в одном template (не dual RU/EN)
- **D2 OVERRIDE:** Georgia + Arial embed для PPTX (Standards/01 EULA coverage), not Crimson Pro + Inter
- **D3:** M5a "Open PPTX" MVP в v1.0.11, M5b (LibreOffice auto-convert) → v1.0.12
- **D4:** RU-first pilot, EN → v1.0.12

### Session 3 decisions

- **Builder port approach:** Copy `build_wireframe.py` → `aurora_pptx/builder.py` с class rename `Wireframe` → `AuroraPPTXBuilder`. Monolithic class (1861 LOC), все primitives + 13 layouts. Parametrization deferred to Session 4 M4.
- **Dead submodules:** tokens.py, master.py, typography.py, charts.py, i18n.py, layouts.py, strings_*.json — kept as deprecated (marked в __init__.py). Session 4.5 optional refactor may consolidate builder.py → submodules.
- **blank_with_theme.pptx:** Orphaned artifact. Builder creates fresh `Presentation()`. Decision: keep for future theme-based workflow (dark-mode variant, possible M4 upgrade).
- **Glossary slide added:** 13th slide before closing. 3-column layout, 24 terms (Методология MMM / Качество модели / Медиа-метрики). Cross-reference for client.
- **Closing slide redesign (Antonov):** statement → CTA (with lime) → narrative → wordmark → compact copyright. "Не на интуиции" в `gold_muted` (softer). Email contact removed from CTA. Copyright без "Подготовлено для Kagocel".
- **MCMC time removed:** Value-perception rule. From s10 diagnostics kept only R²/MAPE/R-hat/ESS.
- **PyInstaller auto-regen tokens:** Pre-step в build_sidecar.py запускает Standards/tokens/build.py перед bundle. Fresh clone safe.

### Deferred to Session 4

- **A2 CRITICAL:** Builder hardcoded Kagocel → parametrize via data dict. First task S4.
- **A1:** Modularize builder.py — Session 4.5 optional.
- **M2:** blank_with_theme.pptx — use or remove decision.
- **M3:** TOC page_refs из data schema (dummy сейчас).
- **L3:** MEMORY.md cleanup/archiving stale entries.

---

## Pending

### Session 4 (next, 7-10h, user-attended for last mile)

**MUST-HAVE (ship blockers):**
1. ✏️ **Data schema definition + parametrize builder** (A2 CRITICAL first)
2. ✏️ **Refactor pptx_export.py** (703 → ~300 LOC) calling `aurora_pptx.build_pptx(data)`
3. ✏️ **DOCX signature-lime** (P0.5b)
4. ✏️ **M5a "Open PPTX" UI button** в `ReportStep.svelte`
5. ✏️ **PyInstaller bundle verify** (C1 fix уже применён, нужна проверка live bundle)

**SHOULD-HAVE (quality):**
6. Brand compliance test (parse output PPTX XML, assert sacred lime + fonts + safe zones)
7. `lang='en'` explicit `NotImplementedError` guard
8. TOC page_refs из data schema

**NICE-TO-HAVE (Session 4.5):**
9. Modularize builder.py — extract primitives/layouts в submodules
10. Use blank_with_theme.pptx as base (M2 theme concept return)
11. Delete dead submodules если не consolidate

### Session 5 (6-8h user-attended ship)

- Bump version (Cargo.toml + tauri.conf.json + package.json 1.0.10 → 1.0.11)
- Full rebuild sidecar + Tauri + NSIS
- Phase 4.2: RDP CLOUDEAI → install → Kagocel pipeline → Report → PowerPoint visual verification
- Phase 5 ship: GitHub Release + Supabase Storage + rosst-updates/latest.json + app_versions SQL + PASHE_IT.MD
- Tag `v1.0.11-stable`

### Open questions / uncertainty

- CLOUDEAI Windows Server Core fonts: Georgia/Arial pre-installed? If not — font substitution could break PDF quality. Check on live-test.
- Hybrid PDF-via-LibreOffice (M5b v1.0.12): winget prerequisite vs bundle trade-off.

---

## Full Session Notes

### Session arc (chronological)

**Session 2 carry-over (iteration phase):**
- Started with wireframe.pptx (43.7 KB, 10 slides) → v1
- Antonov requested: "TOP 10 world quality, не просто не-черновой"
- Critical audit found C1-C4 python-pptx limitations
- Pivot to "template-equivalent via code" (helper library)

**Session 3 iteration (60+ fixes slide-by-slide):**
- v2 (64.1 KB, 12 slides): added at-a-glance, key message, section dividers with takeaway, SCQAR, methodology with limitations, closing narrative
- Slide-by-slide screenshot review:
  - Cover: "Q3 Q4" → "Q3-Q4" (hyphen), 4-column metadata grid
  - At-a-glance: last hairline removed before footer (double-line fix)
  - TOC: dense leader dots, page numbers в Georgia 14pt без "стр.", sidebar "W01-W13" no-wrap
  - Section divider: progress bar repositioned y=6.3 (был conflict с footer); section number deep_40 (читаемее); bullets "·" (middle dot)
  - Key message: source at y=6.4 (не 6.85 overlap); orphan "максимума" documented (content-level, не template)
  - Action+chart: HERO CHANNEL annotation overlap fix (внутри chart zone); native PPTX BAR_CLUSTERED chart
  - Action+table: row_h 0.45 → 0.35; footnote block compact; single bottom hairline
  - Timeline: bands scaled чтобы не overflow (sum=3.13 > area_h=2.6); annotation labels без arrows; gold tick markers
  - SCQAR: blocks compressed; RECOMMENDATION actions split lead/body на 2 строки
  - Methodology: limits с bold lead + body на разных строках; MCMC time removed
  - Sources: "87" ширина 1.5 broken (wrap), fix 2.0; "/100" baseline-aligned; "Последняя синхр." removed
  - Glossary (NEW): 3-column 24 terms; footer domain link removed (misleading)
  - Closing: Antonov redesign applied (flow, lime position, gold_muted, no email, compact copyright)

**Template compression (Antonov request):**
- Top zone 2.3" → 2.05" (safe 0.4 → 0.25)
- Bottom zone tightened (safe 0.4 → 0.20)
- Content zone +0.35" (+10%)
- All heading line_spacing=1.0

**Final wireframe v3:** 73.4 KB, 13 slides, финализирован после всех 60+ правок.

**M3 port to aurora_pptx:**
- Copy build_wireframe.py → aurora_pptx/builder.py
- Rename Wireframe → AuroraPPTXBuilder
- Replace load_tokens() с `from econometrica.aurora_tokens import COLORS, TYPOGRAPHY, SIZING` (generated)
- Remove main(), standalone script infra
- Update `__init__.py` build_pptx() orchestrator
- Smoke test: 13 slides, 75 KB ✓

**Audit phase:**
- Comprehensive review всех Session 1-3 artifacts
- Found C1 (PyInstaller не bundle aurora_pptx) + C2 (aurora_tokens not auto-regen) = 2 ship blockers
- Dead code: Emu import, leaf() func, _nested() func
- Misleading docstring в __init__.py
- Architectural concerns A1-A4 documented
- Fixes applied inline, smoke test re-verified

### Files modified (detailed)

**Created:**
- `Standards/CLIENT_READY_ANATOMY.md` (M1 spec, 9 sections)
- `Standards/tokens/tokens.json` (W3C DTCG, 2-palette architecture)
- `Standards/tokens/build.py` (CLI generator: JSON → CSS/Python)
- `Standards/templates/build_wireframe.py` (~1800 LOC, master reference)
- `Standards/templates/build_blank_theme.py` (ZIP-hack theme XML)
- `Standards/templates/wireframe.pptx` (final, 73.4 KB)
- `Standards/templates/blank_with_theme.pptx` (27 KB, orphaned)
- `Standards/SESSION_AUDIT_2026-04-24.md` (audit report)
- `Dev/Aurora_Econometrica/sidecar/econometrica/aurora_pptx/` (package):
  - `__init__.py` (build_pptx orchestrator)
  - `builder.py` (AuroraPPTXBuilder monolith, 1861 LOC)
  - `tokens.py`, `master.py`, `typography.py`, `charts.py`, `i18n.py`, `layouts.py` (deprecated submodules)
  - `strings_ru.json`, `strings_en.json` (i18n placeholder)
  - `templates/blank_with_theme.pptx` (bundled copy)

**Modified (Aurora_Econometrica master):**
- `.gitignore`: add `src/tokens.generated.css`, `sidecar/econometrica/aurora_tokens.py`
- `sidecar/econometrica/build_sidecar.py`: `--add-data` для aurora_pptx + aurora_tokens + regenerate_tokens() pre-step
- `sidecar/econometrica/aurora_pptx/builder.py` + `__init__.py`: audit cleanup

**Generated (gitignored):**
- `src/tokens.generated.css` (3.6 KB)
- `sidecar/econometrica/aurora_tokens.py` (4.4 KB) — auto-regen on build

### Commits (detailed)

**`bba9a8b` Session 2 skeleton** (11 files, +834 LOC):
```
feat(aurora_pptx): skeleton for client-ready PPTX helpers + generated tokens gitignore
```
- aurora_pptx/ package init
- .gitignore additions

**`3af07b2` Session 3 M3 builder port** (2 files, +1873/-8 LOC):
```
feat(aurora_pptx): M3 builder port + build_pptx() orchestrator
```
- builder.py port from build_wireframe.py
- __init__.py build_pptx() wrapper

**`8837f3d` Session 3 post-audit fixes** (3 files, +58/-36 LOC):
```
fix(aurora_pptx): session audit fixes — PyInstaller bundle + cleanup
```
- build_sidecar.py: aurora_pptx + aurora_tokens bundle + regenerate_tokens()
- builder.py: remove dead imports (Emu, leaf, _nested)
- __init__.py: docstring rewrite, version 0.1.0 → 0.2.0

### Setup & config changes

**Standards directory layout:**
```
Standards/
├── 00_PRINCIPLES.md .. 07_CHECKLIST.md (pre-existing spec)
├── CLIENT_READY_ANATOMY.md (NEW - M1)
├── BRAND_DECISION.md (Hybrid ADR, pre-existing)
├── AUDIT.md + DOGFOOD_2026-04-24.md (Hybrid session artifacts)
├── SESSION_AUDIT_2026-04-24.md (NEW - templates audit)
├── tokens/
│   ├── tokens.json (NEW - W3C DTCG SSOT)
│   └── build.py (NEW - CSS/Python generator)
├── templates/
│   ├── wireframe.pptx (final)
│   ├── build_wireframe.py (master reference)
│   ├── blank_with_theme.pptx (orphan)
│   └── build_blank_theme.py (ZIP theme hack)
└── assets/logo/ (placeholder)
```

**aurora_pptx package layout (Aurora_Econometrica):**
```
sidecar/econometrica/aurora_pptx/
├── __init__.py          # build_pptx() orchestrator (ACTIVE)
├── builder.py           # AuroraPPTXBuilder monolith (ACTIVE, 1861 LOC)
├── tokens.py            # (deprecated)
├── master.py            # (deprecated)
├── typography.py        # (deprecated)
├── charts.py            # (deprecated)
├── i18n.py              # (deprecated)
├── layouts.py           # (deprecated)
├── strings_ru.json      # (deprecated)
├── strings_en.json      # (deprecated)
└── templates/
    └── blank_with_theme.pptx   # (orphan, bundled but not used)
```

**Font stack (final):**
- PPTX output: Georgia (headings) + Arial (body) + Consolas (mono). Embed via Windows/Office EULA coverage. Pre-installed ~99% clients.
- Tauri UI (app.css): Noto Serif + Inter + JetBrains Mono (SIL OFL 1.1).

### Errors & workarounds

**Encountered:**
1. Windows cp1251 console encoding — `print('✓')` / `print('→')` fail. Used `[OK]`, `.` instead throughout session.
2. PermissionError reading wireframe.pptx при Antonov имел файл open в PowerPoint. Workaround: wait for him to close before rebuild.
3. Build_sidecar.py UnicodeDecodeError при `open(...).read()` без explicit encoding='utf-8'. Fixed in verification.
4. "87" text box width=1.5 → wrap на 2 строки для 120pt (each digit ~0.7"). Fix: width=2.0.
5. Stack bars overflow в timeline chart (sum band_h=3.13 > area_h=2.6). Fix: proportional scale-down.
6. Dead leaf() calls после sed replace — 15 instances replaced batch (cleanup).

**Prevented (audit):**
1. 🔴 PyInstaller bundle missing aurora_pptx/aurora_tokens — would cause production ImportError at Report step. Fixed pre-ship.
2. 🔴 Fresh clone broken (aurora_tokens gitignored + no auto-regen). Fixed with regenerate_tokens() step.

**Known (not yet fixed):**
- Orphan "максимума" в key-message title — content-level, template принимает любой title (by design).
- blank_with_theme.pptx created but unused — documented orphan.
- 780 LOC dead code в aurora_pptx submodules — documented, deferred.

### Reference commands

**Regenerate tokens manually (dev):**
```bash
cd D:/Docs/Aurora_Ai/Standards/tokens
python build.py --target python   # → sidecar/econometrica/aurora_tokens.py
python build.py --target css      # → src/tokens.generated.css
python build.py --target all      # both
```

**Rebuild wireframe:**
```bash
cd D:/Docs/Aurora_Ai/Standards/templates
python build_wireframe.py   # → wireframe.pptx
```

**Smoke test build_pptx():**
```python
from econometrica.aurora_pptx import build_pptx
prs = build_pptx()    # uses default Kagocel data
prs.save('out.pptx')  # 13 slides, ~75 KB
```

**Build sidecar (with auto-regen tokens):**
```bash
cd D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica/sidecar/econometrica
python build_sidecar.py   # auto-runs regenerate_tokens(), then PyInstaller
```

**Rollback chain:**
```bash
git -C Dev/Aurora_Econometrica reset --hard v1.0.11-s3-audited   # to post-audit state
git -C Dev/Aurora_Econometrica reset --hard v1.0.11-m3-builder-ready   # to S3 end
git -C Dev/Aurora_Econometrica reset --hard v1.0.11-pre-templates   # to pre-S2 state
```

---

## Next session quick start (/resume)

1. Read `memory/project_client_ready_templates_2026-04-24.md` for full program context.
2. Read `Standards/SESSION_AUDIT_2026-04-24.md` for audit findings summary.
3. Session 4 first task (CRITICAL A2): define data dict schema + parametrize AuroraPPTXBuilder. Без этого builder always outputs Kagocel — ship blocker for multi-client.
4. Key files для открытия: `sidecar/econometrica/aurora_pptx/builder.py` (+`__init__.py`), `sidecar/econometrica/engines/pptx_export.py` (refactor target 703 LOC).
5. Smoke test command: `cd sidecar && python -c "from econometrica.aurora_pptx import build_pptx; build_pptx().save('test.pptx')"` — должен дать 13 slides / 75 KB.

**User context:** Антон (на "ты", тёплый тон). Value-perception rule: никаких processing time/speedup в deliverables. No em dash ever.
