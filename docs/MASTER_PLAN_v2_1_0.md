# Master Plan v2.1.0 — Aurora MMM Optimizer

> **Источник правды по циклу v2.1.0.** Обновляется после КАЖДОГО commit.
> Старт: 2026-05-16 (автономный режим по запросу Антона).
> Цель: 78% → 94% готовности. Прямые продажи 50-100 клиентам, Windows, русский.
> Объём: ~95-100ч работы (выполняется параллельно агентами под надзором Маши маленькой).

---

## Current task

🔄 **IN PROGRESS:** Партия 2 (безопасность pickle) — Маша
- 4.1.1-4.1.2 ✅ дизайн формата `aurora-model` (zip + manifest.json + data.json + arrays.npz)
- 4.1.3 ✅ `engines/persistence_safe.py` готов
- 4.1.4 🔄 wire в `persistence.py` / `modeler.py` / `ols_modeler.py`
- 4.1.5 ✅ 46 round-trip + security тестов passing
- 4.1.6 ⏸ lazy migration в `load_model_with_compat`
- 4.1.7 ⏸ дополнительные attack scenario тесты
- 4.1.8 ⏸ документация формата

🟢 **Делегировано агентам параллельно:**
- Партия 3.1 + 3.2 (анимации каналов) — Sonnet, animations-agent
- Партия 3.4 + 3.5 (контрастность) — Sonnet, contrast-agent
- Партия 4.3 + 4.4 + 4.5 (контент) — Sonnet, docs-agent
- Партия 3.6 + 3.7 (анти-мигание + focus-ring) — Sonnet, a11y-agent

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
| 1.2 | Записать сценарий проверки в документации | 2-3 | 🟢 готовлю автономно |
| 1.3 | Поставить метку версии v2.0.1 | 1 | ⏸ после 1.1 |

### Партия 2 — Безопасность (МАША САМА, IN PROGRESS)

| ID | Пункт | Часов | Статус |
|---|---|---|---|
| 4.1 | Замена устаревшего pickle на auroramodel (zip+JSON+npz) | 15 | 🔄 IN PROGRESS |

**Подзадачи 4.1:**
- 4.1.1 Inventory всех pickle.dump/load call sites — pending
- 4.1.2 Дизайн формата auroramodel (manifest.json + arrays.npz) — DONE (в decisions log)
- 4.1.3 Реализация `engines/persistence_safe.py` (save_model_safe, load_model_safe) — pending
- 4.1.4 Миграция `engines/persistence.py` — wrapper detects format + delegates — pending
- 4.1.5 Round-trip тесты (numpy arrays, scalars, nested dicts, special floats) — pending
- 4.1.6 Lazy migration при первом save старого .pkl — pending
- 4.1.7 Безопасность тесты (malicious pickle blocked) — pending
- 4.1.8 Документация формата в `docs/AURORAMODEL_FORMAT.md` — pending

### Партия 3 — Премиум-доводка (АГЕНТЫ В ПАРАЛЛЕЛЬ)

| ID | Пункт | Часов | Статус | Owner |
|---|---|---|---|---|
| 5.1 | Микро-анимация подтверждения канала | 4 | 🟢 in progress | Agent A |
| 5.2 | Анимация копирования настроек | 3 | 🟢 in progress | Agent A |
| 5.3 | Плавность переходов wizard | 5 | pending | Agent A (после 5.1+5.2) |
| 5.4 | Контрастность светлая тема | 3 | 🟢 in progress | Agent B |
| 5.5 | Контрастность тёплая тема | 3 | 🟢 in progress | Agent B |
| 5.6 | Защита от мигания на ВСЕХ компонентах | 6 | 🟢 in progress | Agent C |
| 5.7 | Видимая рамка фокуса на ВСЕХ кнопках | 4 | 🟢 in progress | Agent C |
| 5.8 | Ревизия внешним дизайнером | 2 | ⏸ опционально, на потом |

### Партия 4 — Документация (АГЕНТЫ В ПАРАЛЛЕЛЬ)

| ID | Пункт | Часов | Статус | Owner |
|---|---|---|---|---|
| 6.1 | Подсказки при наведении | 6 | pending | Маша (после Партии 2) |
| 6.2 | Пошаговый онбординг при первом запуске | 8 | pending | Маша (после Партии 2) |
| 6.3 | Сценарий видео-демо | 2 | ✅ DONE | Agent D |
| 6.4 | Глоссарий эконометрических терминов | 5 | ✅ DONE | Agent D |
| 6.5 | Краткое руководство PDF | 3 | ✅ DONE | Agent D |
| 6.6 | Пилот на новом человеке | 1 | ⏸ blocker: Антон находит |

### Партия 5 — Сборка Windows (МАША САМА)

| ID | Пункт | Часов | Статус |
|---|---|---|---|
| 9.1 | Сборка установочного пакета | 5 | pending (после Партии 2-4) |
| 9.4 | Цифровая подпись (нужен ООО) | 4 | ⏸ blocker: ООО (готовим инфраструктуру) |
| 9.8 | Установка на чистый Windows | 6 | pending (после 9.1) |

---

## Done

- ✅ Создан мастер-план `docs/MASTER_PLAN_v2_1_0.md` (источник правды)
- ✅ Партия 2 п.4.1.1 + 4.1.2: дизайн формата `aurora-model`
- ✅ Партия 2 п.4.1.3: `engines/persistence_safe.py` — save_model_safe / load_model_safe / detect_format / migrate_pickle_to_safe
- ✅ Партия 2 п.4.1.5: `tests/test_persistence_safe.py` — 46 тестов (round-trip, security, edge cases, реалистичный MMM)
- ✅ Партия 4 п.6.3: `docs/VIDEO_DEMO_5MIN_SCRIPT.md` — сценарий 5-мин демо, 7 блоков, раскадровка по секундам
- ✅ Партия 4 п.6.4: `docs/GLOSSARY_v2_1_0.md` — 37 терминов, примеры из жизни, где в Aurora, указатель
- ✅ Партия 4 п.6.5: `docs/USER_GUIDE_v2_1_0.md` — 6 разделов, пошаговая инструкция, troubleshooting, PDF

---

## Commits log

| Hash | Дата | Описание |
|---|---|---|
| `0cccf11` | 2026-05-16 | docs(video-script): сценарий 5-минутного демо (v2.1.0 п.6.3) |
| `b82d039` | 2026-05-16 | docs(glossary): глоссарий 37 терминов v2.1.0 (п.6.4) |
| `fa28f29` | 2026-05-16 | docs(user-guide): краткое руководство пользователя v2.1.0 (п.6.5) |

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

- **Commits в сессии:** 3 (docs-agent: п.6.3 + 6.4 + 6.5)
- **Tests delta:** baseline 947 (pytest + vitest + Rust + migration) — docs-only commits, нет изменений тестов
- **Партий завершено:** 0 / 5 (Партия 4 частично — 3/6 пунктов готовы)
- **Пунктов плана завершено:** 3 / 19 (п.6.3, 6.4, 6.5)
