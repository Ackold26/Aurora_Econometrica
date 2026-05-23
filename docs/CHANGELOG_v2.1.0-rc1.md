# Aurora MMM Optimizer v2.1.0-rc1 — Premium Polish + Security Hardening

**Release date:** 2026-05-16 (release candidate, pending pilot Антон)
**Branch:** `feat/v2.0.0-explicit-mode-wizard`
**Base tag:** `v2.0.1-rc2`
**Status:** ⏳ RC1 — готов к пилотной проверке Антона перед stable

---

## Цели цикла

Цикл v2.1.0 поднимает Aurora MMM Optimizer с **78% → 94%** готовности. Цель — прямые продажи 50-100 клиентам в России, на русском, под Windows.

Закрыты пять направлений работ из утверждённого плана (~95-100 часов работы, выполнено за одну автономную сессию через параллельное использование агентов под надзором Маши маленькой).

---

## Изменения по направлениям

### 1. Безопасность сохранения моделей (Партия 2)

Полная замена устаревшего pickle-формата на закрытый безопасный формат `aurora-model`.

**Что внутри:**

- Новый модуль `engines/persistence_safe.py`:
  - `save_model_safe(data, path)` — атомарная запись через temp + os.replace + fsync
  - `load_model_safe(path)` — безопасный load с проверкой структуры и лимитов
  - `detect_format(path)` — маршрутизация между новым и legacy форматом по magic bytes
  - `migrate_pickle_to_safe(source, target)` — явная миграция legacy pickle
  - `read_manifest(path)` — чтение только manifest без распаковки массивов

- Структура файла (расширение `.pkl` сохранено для обратной совместимости с 40+ путями в Rust IPC, Python и фронтенде):
  - `manifest.json` — формат, версия, контрольные суммы, дата создания
  - `data.json` — все JSON-сериализуемые поля (numpy массивы заменены placeholder'ами)
  - `arrays.npz` — массивы (через `np.savez`, `allow_pickle=False` при load)

- Защитные механизмы:
  - RCE-surface устранён (нет `pickle.load`)
  - Zip-bomb защита (лимит 500 MB uncompressed)
  - Path traversal blocked (member names с `..`, `/`, `\` отвергаются)
  - Лимит 16 файлов в ZIP
  - Лимит 200 символов на имя члена
  - `allow_pickle=False` для arrays.npz
  - SHA-256 sidecar для опциональной tamper-detection

- Lazy migration:
  - При load legacy pickle файл сразу переписывается в `aurora-model`
  - Backup `.pre_safe_migration` сохраняется бессрочно
  - Errors при миграции (read-only FS, EACCES) не ломают load — модель работает в read-only режиме

- Wire:
  - `engines/persistence.py::load_model_with_compat` — детектит формат, маршрутизирует
  - `engines/persistence.py::save_v20_diagnostics` — пишет aurora-model
  - `engines/persistence.py::clear_sensitivity_cache` — пишет aurora-model
  - `engines/modeler.py` — Bayesian save переключён
  - `engines/ols_modeler.py` — small-data OLS save переключён

- Тесты: `tests/test_persistence_safe.py` — **59 тестов**:
  - Round-trip: scalars, lists, nested dicts, numpy arrays всех dtypes/shapes
  - Edge cases: пустой dict, deeply nested, NaN/Inf в arrays (ОК), NaN/Inf в скалярах (отвергается)
  - Безопасность: pickle file отвергается, path traversal blocked, zip-bomb, allow_pickle=False
  - Реалистичный MMM (7 каналов × 8000 samples)
  - Интеграция с `load_model_with_compat`
  - Lazy migration (триггер, idempotent, failure не ломает load)
  - Extended security (exe payload игнорируется, symlinks, unicode, concurrent save)

- Документация: `docs/AURORAMODEL_FORMAT.md` — полная спецификация формата (структура, защита, API, миграция, совместимость, дальнейшее развитие).

### 2. Премиум-доводка интерфейса (Партия 3)

- **Микро-анимация подтверждения канала** (п.5.1) — pulse-once + check-icon при подтверждении роли в `ColumnMapperConfirm`, prefers-reduced-motion guard
- **Анимация копирования настроек** (п.5.2) — stagger copy-flash при `applyToSameType` в `UnitCostEditor` и `AppliedModeSummary` (100ms stagger, 560ms flash, aria-live для screen-readers)
- **Плавность переходов между шагами помощника** (п.5.3) — `{#key currentStep}` + `transition:fly` с направлением forward/back в `ScenarioWizard`, prefers-reduced-motion → duration 0
- **Контрастность светлой темы** (п.5.4) — **7 цветовых пар** исправлены к WCAG AA, минимальная HSL коррекция без изменения hue/saturation
- **Контрастность тёплой темы** (п.5.5) — **14 цветовых пар** исправлены к WCAG AA
- **Защита от мигания на ВСЕХ компонентах** (п.5.6) — глобальный catch-all в `app.css` (`animation: none !important`) + 37 компонентов получили `@media (prefers-reduced-motion: reduce)` блоки + store `$prefersReducedMotion` для programmatic transitions
- **Видимая рамка фокуса на ВСЕХ кнопках** (п.5.7) — глобальный `*:focus-visible` (2px accent-primary, WCAG AA 5.8:1), удалён дубль

Всего **56/56 контрастных пар** проходят WCAG AA в обеих темах.

Артефакты:
- `docs/CONTRAST_AUDIT_v2_1_0.md` — полный inventory контрастных пар
- `docs/A11Y_MOTION_AUDIT.md` — список покрытых компонентов
- `tools/contrast_audit.py` + `tools/find_wcag_color.py` — helper-скрипты
- `src/lib/stores/a11y.js` — реактивный store `prefersReducedMotion`

### 3. Документация и обучение (Партия 4)

- **Подсказки при наведении** (п.6.1) — компонент `Tooltip.svelte` + централизованный словарь `src/lib/data/tooltip-texts.js`, обёрнуты ключевые элементы (KPI selector, ROAS/R²/R-hat/ESS, role icons, traffic light), keyboard a11y, prefers-reduced-motion
- **Пошаговый онбординг при первом запуске** (п.6.2) — `FirstRunTour.svelte` с 8-step overlay, `data-tour-step` атрибуты на ключевых компонентах, localStorage `aurora.firstRunTourCompleted`
- **Сценарий видео-демо «5 минут до первой модели»** (п.6.3) — `docs/VIDEO_DEMO_5MIN_SCRIPT.md`, 7 временных блоков (0:00-4:50), полный voiceover на русском без англицизмов, B-roll инструкции, чеклист перед съёмкой
- **Глоссарий эконометрических терминов** (п.6.4) — `docs/GLOSSARY_v2_1_0.md`, **37 терминов** в 9 тематических разделах, каждый термин с определением + примером + указанием где в Aurora он встречается, алфавитный указатель
- **Краткое руководство пользователя** (п.6.5) — `docs/USER_GUIDE_v2_1_0.md`, 6 разделов, ~10 страниц A4, пошаговая инструкция «Первая модель за 15 минут», troubleshooting, 4 варианта конвертации в PDF

### 4. Сборка установщика Windows (Партия 5)

Инфраструктура готова, финальная сборка ждёт ack Антона и пилотную проверку.

- Версии подняты до **2.1.0-rc1** в `package.json`, `src-tauri/tauri.conf.json`, `src-tauri/Cargo.toml`
- `scripts/build/sign_installer.ps1` — PowerShell wrapper для signtool.exe:
  - DryRun режим (по умолчанию пока ООО не оформлено)
  - UseSelfSigned для smoke-теста signtool инфраструктуры
  - Production mode через `SIGNING_CERT_THUMBPRINT` env var
- `docs/BUILD_WINDOWS_v2_1_0.md` — полный runbook:
  - Pre-flight checklist
  - Команда сборки + ожидаемый размер
  - Цифровая подпись (текущее без ООО + post-ООО workflow)
  - Тестовая установка на чистом Windows 10/11 (15+ проверок)
  - Roadmap к stable

### 5. Пилотная проверка (Партия 1)

- `docs/PILOT_SCENARIO_KAGOCEL.md` — пошаговый сценарий для Антона:
  - 8 шагов с чеклистами
  - Фишки v2.1.0 явно отмечены
  - Финальный чеклист (время, шероховатости, скриншоты)
  - Список известных ограничений (не блокеров)

---

## Тестовое покрытие

| Уровень | Было (v2.0.1-rc2) | Стало (v2.1.0-rc1) | Прирост |
|---|---|---|---|
| Sidecar pytest | 220 | **270** | +50 (lazy migration + security extended + integration) |
| Migration pytest | 40 | 40 | — |
| Rust (cargo test) | 140 | 140 | — (без правок Rust) |
| Vitest (frontend) | 543 | **547+** | +4+ (animations + tooltips тесты) |
| **Всего** | **943** | **997+** | **+54** |

0 регрессий по результатам всех прогонов.

---

## Известные ограничения v2.1.0-rc1

- **Без цифровой подписи** — ООО не оформлено, инфраструктура signtool готова к подписи
- **Только русский язык** — английский в backlog v2.2.0
- **Только Windows** — macOS / Linux в backlog v2.2.0
- **Однопользовательский режим** — многопользовательский в backlog v2.2.0

---

## Roadmap к v2.1.0 stable

1. Пилотная проверка Антона по `docs/PILOT_SCENARIO_KAGOCEL.md` (Кагоцел РФ+, end-to-end)
2. Тестовая установка на чистом Windows 10/11 VM по `docs/BUILD_WINDOWS_v2_1_0.md`
3. Запись видео-демо по `docs/VIDEO_DEMO_5MIN_SCRIPT.md` (на Антоне)
4. Получение фидбека от 3-5 пилотных клиентов
5. Исправление найденных шероховатостей → rc2 или stable
6. Получение EV сертификата от ООО → подпись installer
7. Tag `v2.1.0` + публикация на auroraai.pro
8. Прямые продажи 50-100 клиентам

---

## Связанные документы

- `docs/MASTER_PLAN_v2_1_0.md` — общий план + commits log
- `docs/AURORAMODEL_FORMAT.md` — спецификация формата сохранения
- `docs/CONTRAST_AUDIT_v2_1_0.md` — WCAG AA аудит
- `docs/A11Y_MOTION_AUDIT.md` — список компонентов с anti-pulse защитой
- `docs/GLOSSARY_v2_1_0.md` — глоссарий 37 терминов
- `docs/USER_GUIDE_v2_1_0.md` — руководство пользователя
- `docs/VIDEO_DEMO_5MIN_SCRIPT.md` — сценарий видео-демо
- `docs/BUILD_WINDOWS_v2_1_0.md` — сборка установщика
- `docs/PILOT_SCENARIO_KAGOCEL.md` — сценарий пилотной проверки
- `docs/v2_2_0_backlog.md` — отложенное на следующий цикл (английский, macOS, многопользовательский)
