---
tags: [session, compressed, hybrid, ship, signature-lime, econometrica, pptx, brand-decision]
type: session
updated: 2026-04-24
---

# Quick Reference

**Topic:** Aurora Hybrid Ship — закрытие P0.1 (decision approved) и P0.5 (signature-lime `#CCFF00` 2pt line под action-titles в Econometrica PPTX). Session с двумя commit'ами, потому что первый попал в неправильный файл.

**Key files:**
- `D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica/sidecar/econometrica/engines/pptx_export.py` — **правильный** engine для Econometrica Report (PyInstaller-bundled)
- `D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica/src-tauri/sidecar/pptx_pipeline.py` — engine media-analyst (plain Python), патч там тоже применён для consistency
- `D:/Docs/Aurora_Ai/Standards/BRAND_DECISION.md` — ADR DECISION block (Hybrid Variant C approved)
- `D:/Docs/Aurora_Ai/Standards/AUDIT.md` — P0.1 + P0.5 RESOLVED, P0.5b OPEN
- `D:/Docs/Aurora_Ai/Standards/DOGFOOD_2026-04-24.md` — audit findings + post-live-test correction
- `D:/Docs/Aurora_Ai/Standards/RELEASE_v1.0.11_checklist.md` — Phase 5 workflow

**Status:**
- ✅ Phase 0 (baseline git tags)
- ✅ Phase 1 (formalize P0.1 — ADR block + TL;DR + memory)
- ✅ Phase 2 initial (signature-lime в pptx_pipeline.py — commit `3b7ca43`) **— но в неправильный файл**
- ✅ Phase 3 (pseudo-dogfood 5/5 PASS — но на неправильном pipeline)
- ✅ Pre-commit red-team audit (7 findings, 6 исправлены, DOCX = P0.5b)
- ✅ Phase 4.1 (Tauri build — 178MB, SHA256 `51a4ab37...`)
- 🔴 Phase 4.2 (live-test CLOUDEAI) показал что lime не появился — **wrong file** discovered
- ✅ Phase 4.1.5 (fix commit `36f7445`, tag `v1.0.11-rc2-hybrid-signature`) — patch в правильный `pptx_export.py`, PyInstaller sidecar rebuilt, Tauri rebuild в процессе
- ⏸️ Phase 4.2 retry — ждёт нового installer + user-attended CLOUDEAI test
- ⏸️ Phase 5 (release v1.0.11) — после Phase 4.2 OK

**Branch/commit state:**
- master: `36f7445 fix(hybrid): signature-lime in REAL Econometrica PPTX engine`
- Prev: `3b7ca43 feat(hybrid): PPTX signature-lime #CCFF00 under action-titles (P0.5)`
- Tag: `v1.0.11-rc2-hybrid-signature` (rc1 deleted — был wrong-file)
- Rollback: `v1.0.10-before-hybrid-lime`

---

## Learnings

### 🔴 Самый важный урок сессии — grep ≠ fact-check

Explorer-агент нашёл `src-tauri/sidecar/pptx_pipeline.py` grep'ом `has_text_frame` и назвал это «main PPTX generator». Я доверилась findings без проверки, **какой pipeline реально использует UI Report flow**. В итоге:
- Патч попал в media-analyst cabinet (summary slides из synthesis.md)
- Econometrica UI Report использует **отдельный** PyInstaller-bundled sidecar `sidecar/econometrica/engines/pptx_export.py`
- Live-test показал что lime не появился
- Rollback через revert patch + новый commit в правильном месте

**Правило на будущее:** когда меняешь output любого продукта — trace от UI action → Rust command → Python invocation → конкретная функция. Не верить grep-находкам сабагента как «main entry».

### Pseudo-dogfood ≠ honest dogfood

Прогон на фикстуре через `inject_summary_slides()` дал 5/5 PASS и успокоил. Но это был **media-analyst flow**, а user проверял **Econometrica Report**. Pseudo-dogfood должен либо:
- запускать реальный UI → save PPTX
- либо вызывать тот же entry-point что UI вызывает (в нашем случае `pptx_export.build_pptx()`)

### Single-entry-point rule

`_add_title_text()` в `pptx_export.py` — одна функция, 10 слайдов, lime на всех. Патч helper'а vs патч каждого места — huge win для consistency. Искать в коде `add_title`, `_add_heading` паттерны и предпочитать их точечным patches.

### python-pptx — Connectors skip в text extraction

`Connector` shape не имеет `has_text_frame=True`, поэтому `extract_text_from_shape()` их автоматически пропускает. Нет риска "empty text" injection при preprocess'е обратного парсинга. Защитный comment добавлен в код.

### Red-team audit — критичен, но не непогрешим

Audit нашёл 7 issues (1 critical — DOCX scope gap, 3 medium, 3 minor). Все адресованы до live-test. **НО** audit пропустил главное — что `pptx_pipeline.py` может быть не тем pipeline. Audit проверял корректность кода в **данном файле**, не «правильно ли мы выбрали файл».

### Standards/ не в git — разные уровни защиты

`Aurora_Econometrica` — git repo. `Standards/` — filesystem-only. Изменения в Standards идут с `.bak-YYYY-MM-DD` backup вместо git tag. Это приемлемо для low-stakes docs, но важно не забывать — rollback другой механизм.

---

## Decisions

### P0.1 — Hybrid (Variant C) approved 2026-04-24

Формально закрыт ADR-блоком в `BRAND_DECISION.md`:
- **Product UI** (Tauri apps, dashboards, marketing) — остаётся Aether Mesh dark (`#0C0C12` + `#2E5BFF` + `#CCFF00` + Inter + JetBrains Mono)
- **Client Deliverables** (PPTX/PDF/DOCX/XLSX) — Tier-1 light (Aurora Deep + Gold + Noto Serif + Inter body + 7 Morgan Stanley hues для data-viz, Wall Street coding в XLSX)
- **Bridge (3 sacred-элемента):** Inter (unified body font), `#CCFF00` signature-lime (в UI focus/secondary, в Deliverable 2pt line под action-title), breadcrumb DNA (6pt footer stripe)

### Формат-specific implementation order

Изначально DECISION была ambiguous — «2pt линия под action-title» без указания per-format. После audit'а уточнено:
- **PPTX** — `MSO_CONNECTOR.STRAIGHT` 2pt connector под textbox ✅ realized 2026-04-24
- **DOCX** — paragraph border-bottom 2pt lime = **P0.5b next volley**
- **PDF** — наследует от PPTX/DOCX при экспорте (no direct render)
- **XLSX** — не применяется (signature там = Wall Street color coding)

### Scope: только Econometrica в этой сессии

9 остальных Aurora-продуктов (Analytics Hub, ROSST Media/Legal/Creative/DocMaster, Aurora Creative Hub/PR Master/Oracle, AI_APP_AGENCY) — **не тронуты**. Rollout отложен на следующую сессию (8-12 часов по плану `ship-2-3-zany-hinton.md` § Out of Scope).

### rc2 как tag — не rc1

После wrong-file fix — git tag переименован с `v1.0.11-rc1-hybrid-signature` (commit `3b7ca43`, wrong) → `v1.0.11-rc2-hybrid-signature` (commit `36f7445`, correct). rc1 deleted. Теги теперь отражают реальное состояние.

---

## Pending

### 🔴 Phase 4.2 — CLOUDEAI retry (user-attended)

Новый installer после Tauri rebuild (в процессе). Когда готов:
1. Copy to CLOUDEAI via RDP
2. Install per-machine (admin) over v1.0.10
3. Run full Econometrica pipeline with real Kagocel XLSX
4. Open generated PPTX in PowerPoint
5. Verify `#CCFF00` 2pt line под каждым action-title на реальных слайдах (cover / executive summary / decomposition / ROI / share / waterfall / optimization / recommendations / methodology)
6. Report блокеры (если есть) в `Standards/DOGFOOD_2026-04-24.md`

### ⏸️ Phase 5 — Release v1.0.11 (after 4.2 OK)

Workflow в `Standards/RELEASE_v1.0.11_checklist.md`:
- Bump Cargo.toml + tauri.conf.json + package.json: 1.0.10 → 1.0.11
- Rebuild (installer получает `_1.0.11_` имя + новый SHA256)
- Commit + tag `v1.0.11-hybrid-signature` (rc → stable)
- Upload Supabase Storage + GitHub Release `Ackold26/aurora-releases`
- Update `Infrastructure/rosst-updates/aurora-econometrica/latest.json`
- UPDATE Supabase `app_versions` SQL
- Update `C:/Users/ackol/Desktop/PASHE_IT.MD`

### ⏳ Next session work

1. **P0.5b (DOCX signature-lime)** — paragraph border-bottom в `generate_docx()` + `generate_docx_with_synthesis()` pptx_pipeline.py через python-docx
2. **Rollout на 9 других продуктов** — diff check per-product, точечный патч vs full copy
3. **P0.2 + P0.3** — SSOT pipeline `tokens.json` → CSS/Python/PPTX (устранить 4-way hardcoding)
4. **P0.4** — `aurora-doc-lint` CLI (after SSOT, нужны machine-readable tokens)
5. **Enhancements из DOGFOOD:**
   - A.1: validation длины action-title в `parse_synthesis_sections()` (≤15 слов)
   - B.1: font fallback `Calibri` → `Arial`/`Georgia`
   - K.1: breadcrumb footer helper `_add_breadcrumb_footer()` (второй sacred-элемент)
6. **Flat-mark SVG** от дизайнера — ждём по brief `C:/Users/ackol/Desktop/Aurora_AI_Flat_Mark_Brief/`
7. **Live-dogfood с реальным Kagocel XLSX** — нужен dataset от Антона

---

## Errors & Workarounds

### Wrong-file patch (major)

**Error:** Commit `3b7ca43` добавил signature-lime в `src-tauri/sidecar/pptx_pipeline.py::inject_summary_slides()`, который используется media-analyst cabinet (не Econometrica).

**Workaround:** Revert не нужен — в первом файле патч **тоже корректен** (для media-analyst). Добавлен второй commit `36f7445` с правильным fix в `pptx_export.py::_add_title_text()`. Оба файла теперь несут signature, комментарий в pptx_pipeline указывает на sibling.

### Smoke-test emoji crash (minor)

**Error:** `UnicodeEncodeError: 'charmap' codec can't encode character '\u2705'` при print('✅ PASS') на cp1251 Windows console.

**Workaround:** Заменить emoji на ASCII `[PASS]`/`[FAIL]` в tools/verify_*.py. Python PYTHONIOENCODING=utf-8 env var может помочь, но ASCII-fallback проще.

### PyInstaller freshness check

**Potential error:** `build_sidecar.py` имеет freshness check: если .py newer exe, падает с exit 1. Правильное поведение, защищает от stale bundle.

**Workaround (если упадёт):** `python build_sidecar.py --force` (flag existence надо проверить в скрипте).

### PPTX bundle path differences

**Discovery:** `pptx_pipeline.py` bundled **as-is** (plain Python) через `tauri.conf.json` `sidecar/pptx_pipeline.py` resource. `pptx_export.py` bundled **внутри PyInstaller exe** (`sidecar/econometrica/**/*` resource) — требует `build_sidecar.py` rebuild при изменении.

**Workaround:** Две разные схемы bundle → две разные процедуры rebuild. Для rollout на 9 продуктов надо определить, какую схему каждый использует.

---

## Full Session Notes

### Timeline

1. **Session start** (~01:00 2026-04-24): User попросил закрыть «Hybrid Ship» план из plans/ship-2-3-zany-hinton.md. Plan approved с audit-based revisions (4-6 часов scope = Econometrica only, rollout следующей сессией).

2. **Phase 0** (5 min): git tag `v1.0.10-before-hybrid-lime` + backup `.bak-2026-04-24` для Standards/*.md (Standards/ не в git).

3. **Phase 1** (30 min): Formalized P0.1 в 3 местах:
   - `BRAND_DECISION.md` — ADR DECISION block (Date/Status/Deciders/Context/Decision/Consequences/Alternatives/References structure, переиспользуемый template)
   - `AUDIT.md` — TL;DR updated (5 P0 → 4 open + 1 resolved), P0.1 header → ✅ RESOLVED
   - `memory/project_standards_library.md` — description + status checklist

4. **Phase 2 initial** (60 min): signature-lime в `pptx_pipeline.py::inject_summary_slides()`. Helper `_add_signature_lime(slide, title_box)` с adaptive `title_box.height + Pt(6)` positioning. Smoke-test PASS.

5. **Phase 3 pseudo-dogfood** (60 min): 5-slide e2e через real template + synthetic Kagocel MMM synthesis. 100% lime coverage. 0 blockers. 3 enhancements + 2 minors. DOGFOOD_2026-04-24.md написан.

6. **Pre-commit red-team audit** (30 min): Independent Explore agent прогнал по коду, docs, gitignore, side-effects. Нашёл 7 issues:
   - 🔴 DOCX scope gap — отсрочен на P0.5b
   - 🟡 title_box.top null guard — defensive check добавлен
   - 🟡 Text clipping на 3+ line titles — mitigated через MBB ≤15 words rule
   - 🟡 hardcoded user path in BRAND_DECISION — принято (local context)
   - 🟡 Stale CC-Sessions file — исключён из commit
   - 🟢 .gitignore для tools/*.pptx — добавлено правило
   - 🟢 Connector extraction safety — comment добавлен

7. **Commit `3b7ca43`** (5 min): feat(hybrid): PPTX signature-lime #CCFF00 under action-titles (P0.5). Lefthook V40 PASS.

8. **Phase 4.1 — Tauri build** (~10 min: 5m27s incremental Rust + 3 min NSIS). Installer: 178MB, SHA256 `51a4ab376ad166153251323edac93a371f2f094e19929d9aa4cdf273613c2dc0`.

9. **Phase 4.2 attempt — live-test feedback** (user): «я не вижу изменений в pptx и xlsx». User показал screenshot PowerPoint slide sorter — 10 слайдов Econometrica Report, **lime не видно**.

10. **Root cause analysis** (15 min): grep нашёл второй генератор `sidecar/econometrica/engines/pptx_export.py` с функцией `_add_title_text()` — single entry point для Econometrica Report. Патч должен быть тут. Red-team audit и pseudo-dogfood это пропустили.

11. **Phase 4.1.5 — correct fix** (30 min):
    - `pptx_export.py`: `SIGNATURE_LIME` const + `_add_title_text(signature=True)` расширение
    - `tools/verify_pptx_export_lime.py` smoke-test: PASS (signature=True → lime, signature=False → skip)
    - `pptx_pipeline.py`: comment про sibling file
    - DOGFOOD.md updated с POST-LIVE-TEST CORRECTION section

12. **PyInstaller sidecar rebuild** (~2 min): `build_sidecar.py` отработал, sync в Tauri resource path, freshness check PASS. Sidecar exe: 635 MB dist / 48.7 MB main exe.

13. **Commit `36f7445`**: fix(hybrid): signature-lime in REAL Econometrica PPTX engine (post-live-test). Tag `v1.0.11-rc2-hybrid-signature` (rc1 deleted).

14. **Tauri rebuild** — запущен, aurora-econometrica-gui компилируется (incremental). Ждёт NSIS bundle.

### Code patterns used

#### `_add_title_text` patch pattern

```python
# Before (simple)
def _add_title_text(slide, text, left=0.5, top=0.3, width=9, height=0.6, size=28, color=None, bold=True):
    """Add a title textbox."""
    txBox = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    # ... set text, font, color ...
    return txBox

# After (with signature)
def _add_title_text(slide, text, ..., signature=True):
    """Add a title textbox + Aurora Hybrid signature-lime 2pt line under it."""
    txBox = slide.shapes.add_textbox(...)
    # ... set text, font, color ...

    # Aurora Hybrid signature — 2pt lime line under action-title (P0.5).
    if signature and HAS_PPTX and SIGNATURE_LIME is not None:
        try:
            from pptx.enum.shapes import MSO_CONNECTOR
            line_y = txBox.top + txBox.height + Pt(6)
            line = slide.shapes.add_connector(
                MSO_CONNECTOR.STRAIGHT,
                txBox.left, line_y,
                txBox.left + txBox.width, line_y,
            )
            line.line.color.rgb = SIGNATURE_LIME
            line.line.width = Pt(2)
        except Exception as e:
            logger.warning(f"signature-lime skipped on title '{text[:40]}...': {e}")

    return txBox
```

#### Smoke-test fixture pattern (reusable)

```python
# tools/verify_<feature>.py — standalone, no UI needed
# 1. Import the helper from source
# 2. Build minimal fixture (Presentation + 1-3 slides)
# 3. Call helper
# 4. Save PPTX for visual inspection
# 5. Programmatic assertion: count signature shapes, verify props
# 6. Print [PASS]/[FAIL] (ASCII only — cp1251 safe)
# Run: python tools/verify_<feature>.py
# Fast iteration: 30 sec vs 10 min full app run
```

### External state changes

- Supabase `app_versions`: **NOT touched** (Phase 5 pending)
- `rosst-updates/latest.json`: **NOT touched** (Phase 5 pending)
- GitHub Releases: **NOT touched** (Phase 5 pending)
- PASHE_IT.MD: **NOT touched** (Phase 5 pending)
- Infrastructure other than git: nothing

### Files modified (session total)

**Git-tracked (Aurora_Econometrica repo, 2 commits):**
- `src-tauri/sidecar/pptx_pipeline.py` (commit `3b7ca43`: signature-lime helper for media-analyst cabinet; `36f7445`: comment about sibling)
- `sidecar/econometrica/engines/pptx_export.py` (commit `36f7445`: signature-lime for Econometrica Report — REAL engine)
- `.gitignore` (commit `3b7ca43`: tools/*.pptx exclusion)
- `tools/verify_signature_lime.py` (commit `3b7ca43`: smoke-test media-analyst)
- `tools/pseudo_dogfood_kagocel.py` (commit `3b7ca43`: e2e media-analyst with Kagocel synthesis)
- `tools/verify_pptx_export_lime.py` (commit `36f7445`: smoke-test Econometrica engine)

**Filesystem-only (Standards/ not in git):**
- `Standards/BRAND_DECISION.md` — ADR DECISION block
- `Standards/AUDIT.md` — TL;DR + P0.1/P0.5 RESOLVED + P0.5b OPEN
- `Standards/DOGFOOD_2026-04-24.md` — audit findings + post-live-test correction
- `Standards/RELEASE_v1.0.11_checklist.md` — Phase 5 workflow
- `Standards/BRAND_DECISION.md.bak-2026-04-24` — pre-change backup
- `Standards/AUDIT.md.bak-2026-04-24` — pre-change backup

**Memory (auto-memory system):**
- `memory/MEMORY.md` — Hybrid Ship status in index
- `memory/project_hybrid_ship_2026-04-24.md` — detailed session record
- `memory/project_standards_library.md` — P0.1/P0.5 RESOLVED, P0.5b OPEN
- `memory/user_anton.md` — Антон Сипович profile (created earlier in session)

**Ignored (diagnostic artifacts):**
- `tools/test_signature_lime.pptx` — 1-slide output of verify_signature_lime.py
- `tools/pseudo_dogfood_output.pptx` — 5-slide output of pseudo_dogfood_kagocel.py
- `tools/test_pptx_export_lime.pptx` — 3-slide output of verify_pptx_export_lime.py

### Rollback procedure (if needed)

```bash
# Full code rollback
git -C "D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica" reset --hard v1.0.10-before-hybrid-lime
git -C "D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica" tag -d v1.0.11-rc2-hybrid-signature
rm -f "D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica/tools/"{test_signature_lime,pseudo_dogfood_output,test_pptx_export_lime}.pptx

# Standards rollback (filesystem)
mv "D:/Docs/Aurora_Ai/Standards/BRAND_DECISION.md.bak-2026-04-24" "D:/Docs/Aurora_Ai/Standards/BRAND_DECISION.md"
mv "D:/Docs/Aurora_Ai/Standards/AUDIT.md.bak-2026-04-24" "D:/Docs/Aurora_Ai/Standards/AUDIT.md"
rm "D:/Docs/Aurora_Ai/Standards/DOGFOOD_2026-04-24.md" "D:/Docs/Aurora_Ai/Standards/RELEASE_v1.0.11_checklist.md"

# Sidecar exe — restore from pre-rebuild OR rebuild from rolled-back .py
# (pre-rebuild exe SHA256 was captured in build log: check 2026-04-23 03:00 timestamp)
```

### Verification commands for next session

```bash
# Confirm PPTX signature is in right engine
grep -n "SIGNATURE_LIME\|signature=True\|_add_title_text" \
  "D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica/sidecar/econometrica/engines/pptx_export.py"
# Should find: const, function def with signature=True, usage calls

# Verify both smoke-tests still pass
cd "D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica"
python tools/verify_signature_lime.py       # media-analyst path
python tools/verify_pptx_export_lime.py     # Econometrica path

# Confirm no regression in standards docs
grep -c "P0.1 RESOLVED\|P0.5 RESOLVED\|P0.5b OPEN" \
  "D:/Docs/Aurora_Ai/Standards/AUDIT.md" "D:/Docs/Aurora_Ai/Standards/BRAND_DECISION.md"
```
