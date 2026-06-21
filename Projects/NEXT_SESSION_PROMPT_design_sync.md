# Следующая сессия — дизайн-синхронизация Эконометрики с каноном (элементами)

> cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica`. Ветка `feat/ai-insights-tier2`.
> Параллельный трек к отчётности (та закрыта Волнами 1–3, см. `NEXT_SESSION_PROMPT_reports_wave1.md` + trackfile `AI_INSIGHTS_ASSISTANT_PLAN.md`).
> Обмен с **Машей design-sync** идёт ЧЕРЕЗ Антона (она спрашивает/отвечает, он приносит).

## Контекст и направление (Антон + Маша design-sync, 2026-06-20)
Применять новую дизайн-систему **НЕ всю целиком**, а **по элементам, JIT** (только то, что просит конкретный экран). Метод — трассирующая пуля ВНУТРИ Эконометрики: заземлись в реальном репо → один экран насквозь до отрисованного, проверенного ГЛАЗАМИ результата → потом веер. `drift=0`/`check=0` детектора — необходимо, но НЕ достаточно: доказательство в РЕНДЕРЕ.

## Источник истины (НЕ перепутать)
- **Канон = Svelte:** `D:\Docs\Aurora_Ai\aurora-platform-core\aurora_design\` (W3C DTCG `tokens.json` → tokens.css; готовые Svelte-компоненты `Button/Card/Badge/Modal`; namespace `--ui-*`/`--brand-*`; шрифт InterVariable.woff2; wordmark). Компоненты/порты писать на `--ui-*` (Маша: цель — сходимость на `--ui-*`; порт-на-локальные-токены = last-resort, фрагментирует SSOT).
- **НЕ источник:** `D:\Docs\Aurora_Ai\06_Aurora_Design_system\aurora-ds-react\` — React-ЗЕРКАЛО только для claude.ai/design (превью у них сейчас не рендерит — баг на их стороне, к продукту не относится). Читать React-`.tsx` только как РЕФЕРЕНС контракта.

## ЗАЗЕМЛЕНИЕ (проверено grep'ом 2026-06-20 — не предполагать заново)
- Эконометрика держит свой ЖИВОЙ Aether Mesh в `src/app.css` на ЛОКАЛЬНЫХ `--bg-*`/`--accent-*`/`--text-*` — **3066 использований** в компонентах. Канон `--ui-*` = **0**.
- `src/tokens.generated.css` существует, namespace `--color-ui-*` (генератор `01_Tokens/build.py`), **НЕ импортирован нигде → мёртвый артефакт**. (Дрейф ДВУХ генераторов — канон aurora_design даёт `--ui-*`, build.py даёт `--color-ui-*`.)
- Значения локальных токенов ИДЕНТИЧНЫ канон-Aether Mesh (#0C0C12 / #2E5BFF / #CCFF00 / Inter / glass), только имена другие. Одно реальное расхождение значения: `--text-muted #9090A8` (Эконометрика подняла ради WCAG) vs канон `#7A7A90` (канон ниже AA на карточках — Маша посчитала: 4.2 на #181824).

## СДЕЛАНО в этой сессии (наработка, НЕ потерять)
- **alias-слой создан** (НЕзакоммичен, в аудите): `src/aurora-ui-alias.css` — мост `--ui-* / --brand-* → var(--локальные)` (на ЖИВЫЕ `--bg-*`, НЕ на мёртвый tokens.generated; radius маплен по ЗНАЧЕНИЮ: канон `--ui-radius-lg`=14 → локальный `--radius`=14, не `--radius-lg`=16). Импорт в `src/routes/+layout.svelte:3` ПОСЛЕ app.css. Реализует курс Маши на сходимость к `--ui-*`.

## КЛЮЧЕВАЯ НАХОДКА заземления: портировать почти нечего — паттерны УЖЕ есть
Оба «два в точку» DS-паттерна уже реализованы в Эконометрике, причём БОГАЧЕ DS-версий:
- **Stepper** = `src/lib/components/pipeline/PipelineStepper.svelte` — complete(✓ зелёный)/active/ready/**locked** + connector-заливка + иконки шагов. DS-Stepper проще (3 состояния). → НЕ портировать.
- **InsightCard** = панель «Аврора» `src/lib/components/pipeline/InsightsPanel.svelte` — severity left-accent 3px + tinted-bg + иконка + secondary-текст + **tip/action кнопки** (которых в DS-контракте `{severity,title,body}` нет). → НЕ портировать (DS обеднил бы).
⇒ «доработки дизайна элементами» = **выравнивание существующего под DS-канон**, НЕ порт новых компонентов.

## ЕДИНСТВЕННАЯ найденная реальная дельта (кандидат на первую правку)
**InsightCard severity-tint в DARK-теме.** `src/app.css:173-177` `--bg-insight-*` = нейтральный `color-mix(text-primary 3%)` — ОДИНАКОВЫЙ серый для всех severity (цветная только полоска слева). DS-паттерн И собственная light/fun-тема Эконометрики (`app.css:405-408` lavender/sage/peach/coral) хотят **severity-ЦВЕТНОЙ tint** (DS: 8%). Dark отстал и от DS, и от своей светлой темы. Правка ~4 токена, severity станет читаться фоном.

## ЗАДАЧИ next-session (решить с Антоном/Машей)
1. **alias-слой: оставить или откатить?** Сейчас 0 потребителей `--ui-*` → формально «впрок». Маша стратегически за (сходимость на `--ui-*`). Решить пакетом.
2. **InsightCard dark-tint правка** (4 токена `--bg-insight-*` → severity-цветной 8%) — на родных `--success/--warning/...` или на `--ui-functional-*` через alias. Live-рендер обязателен.
3. **Широкий проход** компонентов Эконометрики (Button/Card/Modal/Badge) vs канон aurora_design — найти дельты, ДОКАЗАТЬ «выравнивать, не портировать» (а не предположить).
4. **text-muted канон-bump** — Маша поднимает `#7A7A90→#9090A8` в `aurora_design/tokens.json` (её сторона, a11y). Проверить, долетело ли (если будем тянуть канон-токены).
5. Если решим InsightCard/Stepper В канон (cross-product) — Маша портирует Svelte сама, сказать ей.

## Инфраструктура
- **dev-окно** запущено: `aurora-econometrica-gui.exe` (debug), мост `:9223` живой — вести его (Маша подтвердила: можно). `npm run tauri:dev` для моста (withGlobalTauri).
- **Лайм sacred** `#CCFF00` — ТОЛЬКО focus/active/Badge-lime; никогда primary-fill/body-текст/error/deliverable.
- **Логотип шапки** = Horizon `06_Aurora_Design_system\05_Logo\Horizon\logo-horizon.png` (уже в `static/`). НЕ брать `*-ui-wb-flat.svg` (вшита тёмная плашка #0A1628 + debug-метка «WB flat_UX»).
- Идиома канона: `aurora-ds-react\.design-sync\conventions.md` + `06_Aurora_Design_system\03_Hybrid_Design_System\README.md` + Print-PDF (10 стр).
