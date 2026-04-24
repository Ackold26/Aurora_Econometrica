---
tags: [session, preflight, live-test, html-tier1, test-datasets]
type: session
updated: 2026-04-24
---

# HTML Tier-1 live-test preflight

Preflight для live-test HTML tier-1 program (v1.0.12). Restart сессии после `9b778de`.

## Regression check

HEAD `9b778de`. Все 5 verify tools: **137/137 PASS** (43 PPTX narrative + 14 PPTX brand + 30 HTML brand + 35 HTML narrative + 15 HTML WCAG AA).

## Smoke HTML (3 темы)

Сгенерированы в `exports/smoke_qa/` через `engines.html_export.build_html()` на synthetic Acme-Corp данных (5 каналов: TV/Digital/Search/Social/OOH).

- `aurora_smoke_light.html` (1024 KB) - default email-friendly
- `aurora_smoke_dark.html` (1024 KB)
- `aurora_smoke_fun.html` (1024 KB)

Safe для визуальной QA без запуска `tauri dev`. НЕ содержат реальных client данных (Acme-Corp, не Kagocel).

## Test datasets централизованы

Ранее разбросаны по `C:/Users/ackol/Desktop/Эконометрика - тестовые файлы/`. 2026-04-24 скопированы в:

**`D:/Docs/Aurora_Ai/TestData/Econometrica/`**

Файлы:
- `Kagocel_RF_MMM_dataset.xlsx` (66 KB) - PRIMARY для dev regression
- `Venarus_MMM_dataset.xlsx` (63 KB)
- `MMX_2021-2025_source.xlsx` (95 KB)
- `Planning_dataset.xlsx` (17 KB)
- `Kagocel_reference_model.pptx` (3.4 MB) - эталон tier-1 output
- `Venarus_reference_model.pptx` (3.4 MB)
- `README.md` - manifest + dev-only disclaimer

## ⚠️ Dev-only rule (критично)

Kagocel / Венарус / MMX - **чужие бренды**, получены Антоном как примеры для разработки Aurora AI Econometrica. Строго:

- ❌ НЕ показывать реальным клиентам (output / demo / presentations)
- ❌ НЕ использовать в маркетинговых материалах
- ❌ НЕ коммитить в git (любой, включая приватный)
- ✅ Только regression / live-test / dogfood силами команды

S7 cleanup (commit `be3d689`) + post-audit (`85d21f6`) удалили все Kagocel hardcoded strings из builder.py. Adapter threshold `len(channels) >= 2` активирует data-driven path для real-client; Kagocel defaults только в explicit fallback (wireframe preview). Verify Case 7 (43/43) гарантирует zero leak.

Новые memory entries 2026-04-24:
- `reference_test_datasets.md` - где что лежит
- `feedback_dev_only_client_names.md` - правило неиспользования чужих брендов

## Готовность к live-test

Next: `npm run tauri dev` → Import `Kagocel_RF_MMM_dataset.xlsx` → full pipeline → Report HTML → Chrome visual QA по 10-step checklist из `2026-04-24-2330-html-tier1-program.md`.

Acceptance: output HTML НЕ должен содержать "Kagocel" / "Кагоцел" - adapter sanitizes имена каналов, но не client name (если user задаёт project_id='Kagocel' в Import - будет в Report ID и DocProperties; для клиент-ready runs Антон должен задавать анонимный project_id).
