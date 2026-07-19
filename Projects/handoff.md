# Handoff — INV-50 sweep + стандарт справки+PDF Econometrica (сессия 2026-07-19)

База аудита: `e8d50f1..324d2ba` (5 коммитов: `44ca49d`/`708363c`/`fe909ea`/`42025e7`/`324d2ba`, все на origin/feat/econ-v2.3.0). diff — `Projects/audit_session.diff` (PDF-бинарник исключён).

## 1. Цель блока
Две связанные цели. (1) **INV-50 sweep** — привести весь клиентский текст Econometrica (HTML-справка + рантайм-код приложения) к канону «правдоподобный диапазон» вместо «доверительный интервал»/«CI» (частотный термин провоцирует ложную уверенность). (2) **Стандарт справки+PDF** — довести справку до принятого кросс-продуктового стандарта (эталон Oracle/CC/SA): актуализация контента под 2.4.0 + генерируемый PDF (117 стр) с обложками/нумерацией + доставка (кнопка/Rust/settings) + линтер.

## 2. Ключевые инварианты
- **INV-50**: клиентский текст = «правдоподобный диапазон». НЕ трогать: IPC-ключи `*_ci_low/high`/`roi_ci_*` (byte-identical контракт verify.auroraai.pro + Rust↔Python), подстроку «90% HDI» (застрахована `test_report_fidelity_live.py`), CSS-классы `.ci-*`, переменные `ci`, эталон-инструкцию `tier2-context.js:280`, легитимные предиктивные/conformal интервалы.
- **Копирайт**: HTML-футеры = «© 2026 ООО «Платформа Аврора» · auroraai.pro»; NSIS publisher/copyright = «Aurora Platform LLC». `sipovich`=0. U+2014 «—»=0 в справке.
- **Счётчик пайплайна** = 7 шагов во ВСЕЙ справке (было 6; Планирование стало отдельным шагом).
- **glossary.html/js — ГЕНЕРИРУЕМЫЕ** из `docs/GLOSSARY_v2_1_0.md` через `build_glossary.py`. Правки INV-50/tire/копирайт внесены в выходы ВРУЧНУЮ (источник md отстал — перегенерация откатит; см. компромисс).
- **PDF**: собирается на сборке `build_help_pdf.py`, зашит в bundle resources (`help-econometrica/*`). Обложки — standalone-документы (Edge shrink-to-fit ломает общий). Нумерация — post-process PyMuPDF (Chromium не умеет @page counters). Линтер `check_help_pdf_consistency.py` — ОТДЕЛЬНЫЙ файл от существующего `check_help_consistency.py` (content-pack labels).

## 3. Осознанные компромиссы (решение → причина)
- **glossary INV-50/tire правлены в выходах, не в источнике** → перегенерация из `GLOSSARY_v2_1_0.md` откатила бы OVB-термин + обновлённый текст 9 терминов (правлены мимо источника прошлыми коммитами `101c999`/`f1ed7c5`/`2996dd6`) = тихий регресс. Полная SSOT-реконсиляция вынесена в долг #6. Санкционировано Антоном (Вариант А).
- **Частотные интервалы (OLS/bootstrap/causal) унифицированы под «правдоподобный диапазон»** → хотя формально частотный ДИ ≠ байесовский credible interval, продукт уже унифицировал клиентский язык; единый термин проще и дух INV-50 (не провоцировать ложную уверенность). Решение Антона.
- **CommandPalette.svelte**: «доверительный интервал» оставлен НЕвидимым keyword-синонимом (видимый текст → канон) → чтобы поиск по старому термину не сломался.
- **Обложка PDF «Optimizer MMM»** (не «Econometrica») → единое имя с productName/установщиком. Решение Антона.
- **install.html путь установки `C:\Program Files\Optimizer MMM\`** взят из кода (`tauri.conf` productName), не из реестрового PDF (PDF 2.3.1 называет иной путь — ошибочен).
- **5×WARN версий** в новом линтере (v1.0.16/v1.1.0 исторические пометки) — WARN, не FAIL → жёсткий FAIL был бы перманентно-красным (контент менять вне скоупа).

## 4. Зоны неуверенности
1. **`tools/build_help_pdf.py`** (новый, ~48KB): headless Edge print-to-pdf + pypdf-склейка + PyMuPDF-нумерация. Хрупкие места: `split_install_body()` (режет install.html по строке `<h2>Удаление программы</h2>` — сломается, если заголовок переформулируют), `sanitize_error_codes_literals()` (regex-вырезание CSS-утечек — привязан к конкретным селекторам error-codes.html), `strip_dark_theme_leaks()`. Грабли Edge (кэш temp-профиля, поллинг стабильного размера файла) — по эталону Oracle, но не прогонялось на разных машинах.
2. **`src-tauri/src/lib.rs` `save_help_pdf`** (Rust): `resource_dir()/help-econometrica/econometrica-help.pdf` → `download_dir()`. Имя файла фиксировано (не user-input) → path-traversal маловероятен, но dev-fallback путь и обработка отсутствия download_dir не прогонялись живьём (только cargo check).
3. **`check_help_pdf_consistency.py`** (новый линтер): свежесть PDF по sha-манифесту источников — проверялось «внести-поймать-откатить» на U+2014, но не на всех классах дрейфа (напр. правка build-скрипта без пересборки PDF).
4. **INV-50 замены в рантайме** (40 файлов, ~108 строк): верифицированы грепами (ключи/«90% HDI» целы, cargo/svelte 0, затронутые тесты зелёные), но каждая из 108 текст-замен на грамматическую гладкость в контексте лично прочитана НЕ вся (делали 6 субагентов + мой финальный греп-гейт).

## 5. Затронутые файлы (роль)
**INV-50 справка (`708363c`):** 8 рукописных HTML + `glossary.html`/`glossary.js` (генерируемые, ручная правка) — термин интервала → канон.
**INV-50 рантайм (`fe909ea`, 40 файлов):** `sidecar/econometrica/engines/*` + `utils/*` + `aurora_html`/`aurora_pptx`/`charts` (генераторы отчётов) + `report.rs` (Rust MD/XLSX) + `src/lib/components/**/*.svelte` (тултипы/вердикты/отчёты) + `src/lib/*.js` (инсайты/тултипы/CSV) — клиентский текст → канон. `RUNTIME_INV50_RECON.md` — карта разведки.
**ps1 (`44ca49d`):** `uninstall-cleanup.ps1` — замена ROSST-скрипта на корректный для Econometrica.
**Справка-контент (`42025e7`, 18 файлов):** 14 HTML + `install.html` (новый) — версии 2.4.0, шаг Планирование, коды ошибок+поддержка, копирайт CPD-09, U+2014 свип; `program-help.js` (путь логов); `build_glossary.py` (footer).
**PDF-слой (`324d2ba`, 8 файлов):** `tools/build_help_pdf.py` (генератор, новый), `tools/check_help_pdf_consistency.py` (линтер, новый), `tools/help_pdf_manifest.json`, `econometrica-help.pdf` (117 стр), `econ-nav.js` (кнопка PDF), `lib.rs` (`save_help_pdf`), `settings/+page.svelte` (кнопка), `tauri.conf.json` (publisher).
