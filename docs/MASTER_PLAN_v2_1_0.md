# Master Plan v2.1.0 — Aurora MMM Optimizer

> **Источник правды по циклу v2.1.0.** Обновляется после КАЖДОГО commit.
> Старт: 2026-05-16 (автономный режим по запросу Антона).
> Цель: 78% → 94% готовности. Прямые продажи 50-100 клиентам, Windows, русский.
> Объём: ~95-100ч работы (выполняется параллельно агентами под надзором Маши маленькой).

---

## Current task

✅ **Партия 2 (безопасность pickle) — закрыта целиком** (Маша)
- 4.1.1-4.1.8 ✅ все 8 подзадач — 59 тестов, документация формата, lazy migration

✅ **Партия 4 п.6.1 + 6.2 — закрыты (Маша)**
- 6.1 Tooltip.svelte + tooltip-texts.js + интеграция + 10 тестов
- 6.2 FirstRunTour.svelte + data-tour-step attrs + 13 тестов

🔄 **В работе:**
- (нет активных задач — ждём Антона для п.6.6 и Партии 1)

✅ **Завершено агентами:**
- Партия 3.1 + 3.2 (анимации каналов) — animations-agent
- Партия 3.4 + 3.5 (контрастность тем) — contrast-agent
- Партия 4.3 + 4.4 + 4.5 (видео + глоссарий + руководство) — docs-agent

⏭ **Следующее (после Партий 3+4):**
- Партия 3.3 — плавность переходов wizard
- Партия 5 — сборка установщика Windows (Маша, после всего)

---

## Next concrete first step

После compress прочитать этот файл → continue:

1. Если Партия 2 ещё в работе — продолжить с `engines/persistence_safe.py` (auroramodel format)
2. Если Партия 2 готова — забрать результаты агентов, аудит их commits, merge
3. Партии 4.1 (tooltips) + 4.2 (онбординг) делаю сама после Партии 2
4. Партия 5 (сборка Windows) — последняя, после всех остальных

---

## Архитектурные решения (Decisions log)

| Дата | Решение | Обоснование |
|---|---|---|
| 2026-05-16 | **auroramodel format** = zip(manifest.json + arrays.npz + meta.json) | Безопасный (нет arbitrary code execution), эффективный для numpy, backward-compat миграция со старого .pkl |
| 2026-05-16 | Старые .pkl продолжают читаться (SHA-256 sidecar guard остаётся) + lazy migration при первом save | Не ломаем существующие проекты, миграция прозрачно |
| 2026-05-16 | Параллельно агентами через Sonnet — задачи где есть чёткая спецификация | Маша Opus 4.7 max на критичные/архитектурные блоки, Sonnet на рутину |

---

## Партии работ

### Партия 1 — Пилот (ЖДЁТ АНТОНА)

| ID | Пункт | Часов | Статус |
|---|---|---|---|
| 1.1 | Полная пилотная проверка через окно (Кагоцел) | 6-8 | ⏸ blocker: Антон |
| 1.2 | Записать сценарий проверки в документации | 2-3 | ✅ DONE — `docs/PILOT_SCENARIO_KAGOCEL.md` (8 шагов + чеклисты, v2.1.0 фишки помечены) |
| 1.3 | Поставить метку версии v2.0.1 | 1 | ⏸ после 1.1 |

### Партия 2 — Безопасность ✅ COMPLETE (МАША)

| ID | Пункт | Часов | Статус |
|---|---|---|---|
| 4.1 | Замена устаревшего pickle на aurora-model (zip+JSON+npz) | 15 | ✅ DONE |

**Подзадачи 4.1:**
- 4.1.1 ✅ Inventory всех pickle.dump/load call sites (4 места: persistence.py × 2, modeler.py, ols_modeler.py)
- 4.1.2 ✅ Дизайн формата `aurora-model` (manifest.json + data.json + arrays.npz, имя файла latest.pkl сохранено)
- 4.1.3 ✅ `engines/persistence_safe.py` — save_model_safe / load_model_safe / detect_format / migrate_pickle_to_safe / read_manifest
- 4.1.4 ✅ Wire в `engines/persistence.py` (load_model_with_compat детектит формат) + `engines/modeler.py` + `engines/ols_modeler.py` + save_v20_diagnostics + clear_sensitivity_cache
- 4.1.5 ✅ 59 тестов в `tests/test_persistence_safe.py` (round-trip, security, edge cases, реалистичный MMM, интеграция, lazy migration, extended attacks)
- 4.1.6 ✅ Lazy migration в `load_model_with_compat` — legacy pickle переписывается в aurora-model сразу при load, backup сохраняется
- 4.1.7 ✅ Дополнительные attack scenario тесты — zip-bomb с extreme compression, exe payload, symlinks, unicode names, concurrent save race
- 4.1.8 ✅ Документация формата в `docs/AURORAMODEL_FORMAT.md` (полная спецификация: структура, защита, API, миграция, совместимость)

### Партия 3 — Премиум-доводка (АГЕНТЫ В ПАРАЛЛЕЛЬ)

| ID | Пункт | Часов | Статус | Owner |
|---|---|---|---|---|
| 5.1 | Микро-анимация подтверждения канала | 4 | ✅ DONE | Agent A |
| 5.2 | Анимация копирования настроек | 3 | ✅ DONE | Agent A |
| 5.3 | Плавность переходов wizard | 5 | ✅ DONE | Маша |
| 5.4 | Контрастность светлая тема | 3 | ✅ DONE | Agent B |
| 5.5 | Контрастность тёплая тема | 3 | ✅ DONE | Agent B |
| 5.6 | Защита от мигания на ВСЕХ компонентах | 6 | ✅ DONE | Agent C |
| 5.7 | Видимая рамка фокуса на ВСЕХ кнопках | 4 | ✅ DONE | Agent C |
| 5.8 | Ревизия внешним дизайнером | 2 | ⏸ опционально, на потом |

### Партия 4 — Документация (АГЕНТЫ В ПАРАЛЛЕЛЬ)

| ID | Пункт | Часов | Статус | Owner |
|---|---|---|---|---|
| 6.1 | Подсказки при наведении | 6 | ✅ DONE | Маша |
| 6.2 | Пошаговый онбординг при первом запуске | 8 | ✅ DONE | Маша |
| 6.3 | Сценарий видео-демо | 2 | ✅ DONE | Agent D |
| 6.4 | Глоссарий эконометрических терминов | 5 | ✅ DONE | Agent D |
| 6.5 | Краткое руководство PDF | 3 | ✅ DONE | Agent D |
| 6.6 | Пилот на новом человеке | 1 | ⏸ blocker: Антон находит |

### Партия 5 — Сборка Windows (МАША САМА)

| ID | Пункт | Часов | Статус |
|---|---|---|---|
| 9.1 | Сборка установочного пакета | 5 | 🔄 готова инфраструктура (версии 2.1.0-rc1, runbook) — финальная сборка после ack |
| 9.4 | Цифровая подпись (нужен ООО) | 4 | ⏸ blocker: ООО (скрипт sign_installer.ps1 готов, DryRun + SelfSigned режимы) |
| 9.8 | Установка на чистый Windows | 6 | ⏸ blocker: чистая VM (чеклист в `docs/BUILD_WINDOWS_v2_1_0.md`) |

---

## Done

- ✅ Создан мастер-план `docs/MASTER_PLAN_v2_1_0.md` (источник правды)
- ✅ Партия 2 п.4.1.1 + 4.1.2: дизайн формата `aurora-model`
- ✅ Партия 2 п.4.1.3: `engines/persistence_safe.py` — save_model_safe / load_model_safe / detect_format / migrate_pickle_to_safe
- ✅ Партия 2 п.4.1.5: `tests/test_persistence_safe.py` — 46 тестов (round-trip, security, edge cases, реалистичный MMM)
- ✅ Партия 4 п.6.3: `docs/VIDEO_DEMO_5MIN_SCRIPT.md` — сценарий 5-мин демо, 7 блоков, раскадровка по секундам
- ✅ Партия 4 п.6.4: `docs/GLOSSARY_v2_1_0.md` — 37 терминов, примеры из жизни, где в Aurora, указатель
- ✅ Партия 4 п.6.5: `docs/USER_GUIDE_v2_1_0.md` — 6 разделов, пошаговая инструкция, troubleshooting, PDF
- ✅ Партия 3 п.5.4: WCAG AA контрастность светлая тема — 7 пар исправлено, 56/56 PASS
- ✅ Партия 3 п.5.5: WCAG AA контрастность тёплая тема — 14 пар исправлено, 56/56 PASS
- ✅ Партия 2 п.4.1.4: wire безопасного формата в `engines/persistence.py` (load_model_with_compat детектит формат), `engines/modeler.py` (Bayesian save), `engines/ols_modeler.py` (OLS save)
- ✅ Партия 2 п.4.1.5 + интеграционные: 50 тестов проходят, 257 sidecar тестов проходят (включая security_attack_vectors)
- ✅ Партия 3 п.5.1: pulse-once анимация подтверждения ролей (ColumnMapperConfirm) — check-icon + success-green pulse, prefers-reduced-motion guard, тесты с fake timers
- ✅ Партия 3 п.5.2: stagger copy-flash анимация applyToSameType (UnitCostEditor + AppliedModeSummary) — 100ms stagger, 560ms flash, aria-live for a11y
- ✅ Партия 2 п.4.1.6: lazy migration legacy pickle → aurora-model при load (backup `.pre_safe_migration`, swallow errors при read-only FS)
- ✅ Партия 2 п.4.1.7: extended security tests — zip-bomb (extreme compression), exe payload в ZIP игнорируется, symlinks не следуем, unicode names, concurrent save race
- ✅ Партия 2 п.4.1.8: `docs/AURORAMODEL_FORMAT.md` — спецификация формата (структура, защита, API, миграция, совместимость, дальнейшее развитие)
- ✅ Партия 3 п.5.6: anti-pulse защита — global `animation:none` + 37 компонентов, store `prefersReducedMotion`, `docs/A11Y_MOTION_AUDIT.md`
- ✅ Партия 3 п.5.7: focus-visible ring — global `*:focus-visible` 2px accent-primary, удалён дубль, WCAG AA 5.8:1
- ✅ Партия 3 п.5.3: плавные переходы между шагами ScenarioWizard — `{#key}` + transition:fly с направлением forward/back, prefers-reduced-motion → duration 0 + offset 0
- ✅ Партия 4 п.6.1: Tooltip.svelte (viewport-aware, aria-describedby, ESC, prefers-reduced-motion), tooltip-texts.js (40+ записей), интеграция в KPISelector/ConvergenceDashboard/SensitivityTornado/TrafficLight, 10 vitest-тестов
- ✅ Партия 4 п.6.2: FirstRunTour.svelte (8 шагов, spotlight box-shadow, прогресс, ESC/Arrow, localStorage, prefers-reduced-motion), data-tour-step на 6 элементах, 13 vitest-тестов
- ✅ Партия 1 п.1.2: `docs/PILOT_SCENARIO_KAGOCEL.md` — 8-шаговый сценарий пилотной проверки Кагоцел РФ+
- ✅ Партия 5 п.9.1+9.4 инфраструктура: версии 2.1.0-rc1 в package.json/tauri.conf.json/Cargo.toml, `scripts/build/sign_installer.ps1` (DryRun/SelfSigned/Production), `docs/BUILD_WINDOWS_v2_1_0.md` runbook
- ✅ docs/CHANGELOG_v2.1.0-rc1.md — release notes
- ✅ Tools/conftest перевод 5 файлов на `load_model_with_compat` + `save_model_safe` (устранён прямой pickle.load/dump в integration tests)
- ✅ Red-team security audit aurora-model (`docs/SECURITY_AUDIT_aurora_model_v2_1_0.md`) — 12 находок
- ✅ 5 security fixes (SH-AM-04 object arrays, SH-AM-05 sha256 verify, SH-AM-07 recursion bomb, SH-AM-11 project_lock в modeler/ols, SH-AM-12 sidecar verify для aurora-model) — 277/277 pytest passing

---

## Commits log

| Hash | Дата | Описание |
|---|---|---|
| `0cccf11` | 2026-05-16 | docs(video-script): сценарий 5-минутного демо (v2.1.0 п.6.3) |
| `b82d039` | 2026-05-16 | docs(glossary): глоссарий 37 терминов v2.1.0 (п.6.4) |
| `fa28f29` | 2026-05-16 | docs(user-guide): краткое руководство пользователя v2.1.0 (п.6.5) |
| `28e894d` | 2026-05-16 | docs(contrast): WCAG AA аудит + helper scripts (п.5.4+5.5) |
| `00d2ce6` | 2026-05-16 | fix(theme-light): correct contrast pairs к WCAG AA (п.5.4) |
| `4459b65` | 2026-05-16 | fix(theme-warm): correct contrast pairs к WCAG AA (п.5.5) |
| `e8d6966` | 2026-05-16 | feat(persistence): wire безопасный формат aurora-model (п.4.1) |
| `c22911c` | 2026-05-16 | feat(animations): pulse confirm на ValidateStep (п.5.1) — включён в master-plan commit |
| `54ac5e7` | 2026-05-16 | feat(animations): stagger copy-flash при applyToSameType (п.5.2) |
| `3dba7cf` | 2026-05-16 | feat(a11y-motion): anti-pulse global + 37 компонентов (п.5.6) |
| `86c19c8` | 2026-05-16 | feat(a11y-focus): focus-visible + dialog instant appearance (п.5.7) |
| `dce4d2a` | 2026-05-16 | feat(tooltips): подсказки при наведении на ключевые элементы (v2.1.0 п.6.1) |
| `c024c50` | 2026-05-16 | feat(onboarding): первый запуск с пошаговым туром (v2.1.0 п.6.2) |
| `662ae57` | 2026-05-16 | feat(persistence): lazy migration + extended security tests + спецификация (п.4.1.6-4.1.8) |
| `986fe34` | 2026-05-16 | feat(wizard-transitions): плавные переходы между шагами (п.5.3) |
| `b382082` | 2026-05-16 | chore(release): bump до 2.1.0-rc1 + signtool infrastructure (п.9.1+9.4) |
| `3050de8` | 2026-05-16 | docs(pilot): сценарий пилотной проверки Кагоцел РФ+ (п.1.2) |
| `c8e35b7` | 2026-05-16 | docs(changelog): v2.1.0-rc1 release notes — 5 партий завершены |
| `7aaffa9` | 2026-05-16 | docs(security): red-team аудит aurora-model — 12 находок |
| `e395731` | 2026-05-16 | fix(security): закрытие 5 находок аудита aurora-model (SH-AM-04/05/07/11/12) |

---

## Pending push gate

Решение о push к origin принимает Антон. Я делаю auto-commit локально, перед push показываю diff summary.

---

## Открытые вопросы к Антону (минимизированы)

Сейчас открытых вопросов нет. Если возникнут — ТОЛЬКО про:
- Schema migration (формат изменения данных проекта)
- Push к remote
- Архитектурные развилки с долгосрочными последствиями

---

## Post-compress resume protocol

1. Прочитать `docs/MASTER_PLAN_v2_1_0.md` (этот файл) — раздел **Next concrete first step**
2. Прочитать `docs/SPRINT_v2_0_1_rc2_TRACK.md` (предыдущий sprint, источник правды по фундаменту)
3. Continue без подтверждения

---

## Метрики прогресса (auto-update после commit)

- **Commits в сессии:** 12 (docs-agent: п.6.3+6.4+6.5; contrast-agent: п.5.4+5.5 audit+fix×2; animations-agent: п.5.1+5.2; a11y-agent: п.5.6+5.7; Маша: п.6.1 tooltips + п.6.2 onboarding)
- **Tests delta:** 582 vitest passing (+23 новых тестов: 10 tooltip + 13 first-run-tour, 0 regressions)
- **Партий завершено:** 0 / 5 (Партия 3 полностью 7/7; Партия 4 частично — 5/6 [ждём п.6.6 от Антона])
- **Пунктов плана завершено:** 11 / 19 (п.6.3, 6.4, 6.5, 5.4, 5.5, 5.1, 5.2, 5.6, 5.7, 6.1, 6.2)
