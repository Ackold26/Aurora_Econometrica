# Sprint 5: Infrastructure Hardening

**Started:** 2026-04-27
**Branch:** math-fix-v1.0.13 (continuing post-Sprint 4)
**Plan:** `C:\Users\ackol\.claude\plans\bright-jingling-pebble.md`
**Estimate:** 23-33h (4 tracks, can parallel)

---

## Current Status

**Phase:** 0 — Pre-sprint verification
**In progress:** Status file create + baseline metrics capture
**Blocking:** None
**Next concrete step:** Verify Tauri bundle path (`help-econometrica/` vs `help/`) + capture baseline metrics (svelte 31 errors, vitest 31/31, CI ~10min)

---

## Done

- [x] 2026-04-27 Plan approved with audit (18 issues found)
- [x] 2026-04-27 Status file created
- [x] 2026-04-27 Phase 0 baseline: svelte=31 errors, vitest=31/31 PASS, bundle path = `help-econometrica/`
- [x] 2026-04-27 Phase 1 SHIPPED [commit `09858b4`]:
  - Track A complete: svelte-check 31 → **0 errors**
  - NEW pytest.ini + tools/conftest.py (sys.path injection, fixtures)
  - NEW tools/run_legacy_tests.py (standalone runner для legacy scripts)
  - NEW .github/actions/setup-aurora composite action
- [x] 2026-04-27 Phase 2 — CI extension:
  - Extended .github/workflows/ci.yml: NEW python-tests job (ubuntu-latest), NEW help-sync job
  - check job: + V40 XSS + DecomposeStep regression guard (defense-in-depth)
  - release job: needs [check, python-tests, help-sync] — blocks на ANY failure
- [x] 2026-04-27 Phase 3 — Help sync + multi-client:
  - NEW tools/sync_help_lists.py — auto-inject BRAND_HINTS/PERF_HINTS/STRONG_PERF_HINTS via markers
  - methodology.html updated: Trust Level 3 «в разработке» → «v1.1.0 (shipped)» + auto-sync sections
  - lefthook.yml: NEW sync-help-lists hook (auto-rebuild + git add)
  - NEW tools/test_integration_kagocel_pathologies.py — 5 integration tests (using kagocel_pathology fixture)
- [x] 2026-04-27 Verification: vitest 31/31, pytest 53 (parallel), legacy 10/10, all PASS

---

## Decisions Log

### 2026-04-27 — Architectural (audit-revised)

- **Help docs: NO migration к Markdown** (Critical Audit issue A) — preserve existing HTMLs с inline CSS + econ-nav.js. Auto-inject sections from code via `<!-- AUTO_X_START -->` markers. Saves 6-8h.
- **Multi-client tests: synthetic pathology fixtures** (issue B) — pattern uже established (test_optimizer_kagocel_redistribution.py). NEW pathology fixtures для Венарус. Real data testing = manual alpha gate.
- **No `pyproject.toml`** (issue E) — use `pytest.ini` (legacy compat, single-purpose).
- **CI matrix:** Python tests на ubuntu-latest (faster, cheaper), Tauri build на windows-latest (issue G).
- **Lefthook auto-rebuild** (NOT --check fail) (issue F) — git add updated files automatically.
- **Pre-trained pickle fixture** (issue D) — session-scoped, reused across integration tests.
- **Composite GitHub Action** для DRY setup (issue H).
- **pytest-xdist** для parallel test execution (issue I).
- **lefthook hooks в CI defense-in-depth** (issue P).

---

## Tracks

### Track A — Svelte-check cleanup (4-6h)
- Wave 1: JSDoc bulk fixes (~15-20 errors)
- Wave 2: Property doesn't exist (~5-7)
- Wave 3: Legacy cleanup (Hill.js, insights-rules.js)
- Target: 0 errors

### Track B — Help docs auto-sync (2-4h, audit-revised)
- NEW `tools/sync_help_lists.py` — inject BRAND_HINTS / PERF_HINTS via markers
- Lefthook auto-rebuild hook
- CI drift check
- Bonus: econ-nav.js PAGES auto-sync

### Track C — Multi-client pytest infrastructure (8-12h)
- NEW `pytest.ini` + `tools/conftest.py` (sys.path injection, markers, fixtures)
- Pre-trained pickle session fixture
- NEW pathology fixtures (kagocel + venarus synthetic)
- Verify existing 15 test_*.py have `def test_X()` for pytest discovery

### Track D — CI/CD extension (4-6h)
- NEW `.github/actions/setup-aurora/action.yml` (composite)
- Extend `.github/workflows/ci.yml`:
  - Python tests job (ubuntu-latest)
  - Help sync check job (ubuntu-latest)
  - Lefthook hooks defense-in-depth в `check`
  - Release job needs all prior

---

## Next steps queue

1. Phase 0: Verify Tauri bundle path + vitest baseline
2. Phase 1: Foundation (pytest.ini, conftest.py, composite action, Track A wave 1)
3. Phase 2: Tests + CI (pytest discovery audit, pre-trained fixture, CI Python tests, Track A waves 2+3)
4. Phase 3: Help + Multi-client (sync_help_lists.py, lefthook auto-rebuild, pathology fixtures)
5. Phase 4: Verification (e2e CI run, alpha gate, docs)

---

## Commits

- `09858b4` 2026-04-27 — feat(sprint5): Phase 1 foundation — pytest harness + svelte-check 0 errors + composite CI action
- (next) 2026-04-27 — feat(sprint5): CI Python tests + help sync auto-inject + multi-client integration fixtures
