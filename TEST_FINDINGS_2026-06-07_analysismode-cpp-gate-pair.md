---
tags: [load-1, analysis-mode, cpp-gate, rehydration, train-artifact, durable]
type: implementation-map
date: 2026-06-07
scope: связанная пара — persist analysisMode + cpp-гейт в ConfigPanel.trainModel (хвост LOAD-1)
gates: { svelte: "0E/171W", vitest: 677, cargo_project: 149 }
---
# LOAD-1 пара: analysisMode persist + cpp-гейт обучения

**Контекст.** Хвост класса LOAD-1 (`TEST_FINDINGS_2026-06-05_load1-config-rehydration.md`).
`ConfigPanel.trainModel` НЕ имел cpp-гейта — chokepoint только на `completeStep(1)` (шаг Валидация).
После RELOAD статус Модели уже 'complete'/'ready' (персистится в pipelineMeta) → `completeStep(1)`
НЕ перезапускается → re-train минует гейт → **ROI-артефакт** (physical-канал в roi-режиме без
unit_cost, класс TRPs 12186×). Гейт нельзя добавить в изоляции: `analysisMode` не персистился →
reset в 'roi' на reload → effectiveness-проект ложно блокировался бы. Отсюда **связанная пара**.

## Метод (мета-рекомендация прошлой сессии: truth-table ДО кода)
1. Заземление в реальном коде (`cppSatisfied` :1115, `analysisMode` :620, count-KPI subscribe :730,
   `trainModel` :251, `ProjectInfo`/`project_update`).
2. **VERIFIED truth-table** — предикат `cppSatisfied` уже залочен зелёным `nav2-footer-gate.test.js`
   (119-180 + chokepoint 215-265, включая reload-домен пустого perChannelInput). Блок ⇔
   `detectedType==='physical' && mode==='roi' && unit_cost отсутствует/≤0`. kpiKind НЕ участвует.
3. **Адверсариальный агент на ДИЗАЙН** (нумерованные оси > открытое «найди баги») → 5 дыр.
4. Test-first реализация → **адверсариальный агент на РЕАЛИЗАЦИЮ** (свой свежий код = главный
   подозреваемый) → SOUND + 2 опц. правки (сделаны).

## Truth-table пары (reload→trainModel путь; perChannelInput на reload = {} → detect(name))
| persisted mode | detect(name) | unit_cost | гейт | SHOULD | вердикт |
|---|---|---|---|---|---|
| roi | physical | нет | **BLOCK** | block (ROI-артефакт) | ✔ |
| roi | physical | есть | allow | allow | ✔ |
| roi | monetary | * | allow | allow | ✔ |
| effectiveness | physical | нет | allow | allow (физ.метрики валидны) | ✔ |
| effectiveness/mixed | * | * | allow | allow | ✔ |
| **legacy (analysis_mode=null)** | physical | нет | **allow (fail-open)** | allow (pre-fix поведение) | ✔ D-2 |
| roi, pci был 'monetary' (override потерян) | physical | нет | BLOCK | allow | ✖ **D-1 over-block** (известный) |

## 5 дыр адверс. дизайн-аудита (severity скорректирована чтением кода)
| ID | Severity | Решение |
|---|---|---|
| **D-2** legacy без analysis_mode → гейт ложно блокирует effectiveness-проект (регрессия от гейта) | HIGH | **ЗАКРЫТО:** флаг `analysisModeIsPersisted()` — гейт enforce ТОЛЬКО при persisted режиме; legacy fail-open к pre-fix. Self-healing: первый train post-fix персистит → next reload gated. cargo `read_project_legacy_json_without_analysis_mode_defaults_none` + vitest fail-open. |
| **D-5** persisted 'mixed' ре-гидрируется в non-expert UI → INV-30 рассинхрон (нет mixed-карточки) | MED | **ЗАКРЫТО:** `mixed → expertMode.set(true)` при ре-гидрации. vitest D-5. |
| **D-3** A→B→A clobber несохранённого выбора режима | MED (агент: HIGH) | **ОТЛОЖЕНО (known-limit):** гейт читает ТОТ ЖЕ стор, что показывает UI (`get(analysisMode)`) → нет surprise-блока относительно видимого; pre-existing global-store leak, не регрессия гейта. Зеркалит принятый count-KPI лимит. Закрытие — persist-on-change (AnalysisModeSelector презентационный, нет activeProjectId → инвазивно). |
| **D-1** perChannelInput reset на reload → physical-имя+юзер-override='monetary'+no-cost → ложный блок | MED | **ОТЛОЖЕНО (known-limit, safe-direction):** over-block (не порча), recoverable (re-mark на Валидации / add unit_cost). Промт явно депри��ритизировал perChannelInput persist. Сужено: гейт по `enabledChannels` (отключённый канал не блокирует). Закрытие — persist perChannelInput (follow-up). |
| **D-6** TDZ (subscribe должен быть после analysisMode :620) | LOW (fatal если нарушить) | Соблюдено — subscribe на :763, рядом с count-KPI. |

NB: агент ошибся — «план называет пару analysisMode+perChannelInput». Промт: пара =
**analysisMode persist + cpp-гейт**. perChannelInput промт отдельно депри��ритизировал.

## Реализация (3 коммит-файла)
- **Rust `project.rs`:** `ProjectInfo += analysis_mode: Option<String>` (serde default) + `project_update`
  handler + 2 инициализатора + 2 cargo-теста (roundtrip + legacy→None). cargo project **149**.
- **`project-state.js` :763:** новый `activeProject.subscribe` (id-guard `_lastAnalysisModeProjectId` +
  флаг `_activeProjectHasPersistedMode`); set режима + `mixed→expertMode`; legacy → НЕ клоббить стор;
  `!p` → reset 'roi' + флаг false. Export `analysisModeIsPersisted()`.
- **`ConfigPanel.trainModel`:** cpp-гейт (`analysisModeIsPersisted() && !cppSatisfied({channels:enabledChannels,...})`)
  после dataFile-проверки, ПЕРЕД `isComputing.set(true)`; `project_update += analysis_mode`.
- **+ братский фикс (из верификации):** `trainInFlight=false` в 4 pre-existing early-return ветках
  trainModel (latch-stuck до reload; мой гейт уже сбрасывал, старые ветки — нет — тот же класс).

## Тесты (`analysis-mode-rehydration.test.js`, +13 vitest)
Драйвит РЕАЛЬНЫЙ activeProject store (не симуляция). Лочит: persisted→set+флаг · D-2 legacy
fail-open (стор не клоббится + флаг false + гейт не блокирует) · D-5 mixed→expert · id-guard
mid-session · смена id · persisted→legacy→persisted транзиция · deselect reset · truth-table гейта
(legacy/roi-block/roi-cost/effectiveness/monetary/enabled-scope).

## Адверс. верификация реализации: SOUND
Дыр в свежем коде НЕ найдено. Подтверждено чтением: гейт-плейсмент (isComputing не залипает,
enabledChannels в scope) · enabledChannels≡buildTrainConfig mediaColumns (нет рассинхрона) ·
id-guard/флаг (флаг после early-return) · expertMode реентри нет · mixed-предикат залочен ·
!p-reset старое не ломает (migrateV13ToV20 мёртв в проде). 2 опц. правки сделаны (trainInFlight latch
+ транзиция-тест).

## Остаток LOAD-1 (после этой пары)
- 🟠 **`modelChannelEnabled` persist** (п.2) — re-train иной media set: на reload ConfigPanel re-init
  из media (zeros>80% default) → ручной disabled low-zeros канал ре-включается. persist toggle-состояния
  (НЕ media_columns роль) + правка re-init.
- D-1 (perChannelInput persist) + D-3 (analysisMode persist-on-change) — known-limits, follow-up.
