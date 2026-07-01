# Карта разрыва дизайна — Econometrica vs эталон DocMaster (2026-07-01)

**Эталон (выбор Антона):** Docs Lab / DocMaster (`Dev/ROSST_AI_DocMaster`).
**Отстающий:** Econometrica (`Dev/Aurora_Econometrica`).
**Метод:** сравнение дизайн-систем по коду (токены, шрифт, темы, компоненты). Обе на ветке `feat/rag-core-adopt`.
**Вывод:** разрыв не косметический — **разные поколения дизайн-системы**. DocMaster мигрирован на **Aurora Hybrid Design System** (генерируемый SSOT), Econometrica застряла на pre-Hybrid ручной «AETHER MESH».

## Разрыв по пунктам (приоритет = влияние на облик × стоимость)

### 1. 🔴 Источник токенов — архитектурный разрыв (корень всего)
- **Эталон:** `app.css` импортит `tokens.generated.css` + `themes.generated.css`, которые генерируются из `Standards/tokens/tokens.json` через `build.py` (W3C DTCG SSOT). Автоперегенерация на `predev`/`prebuild` (`build:tokens`). Last build — 2026-07-01.
- **Econometrica:** `tokens.generated.css` физически ЕСТЬ, но **`--color-ui-*` использований: 0** — файл мёртв, в `app.css` даже не импортируется. Всё на хардкод-цветах в `:root` (`--bg-primary:#0C0C12`…), `--bg-*` использований — сотни. Нет `build:tokens` pipeline.
- **Следствие:** любые правки канона в SSOT (`Standards/tokens/`) до Econometrica не доезжают.

### 2. 🟠 Палитра/бренд — беднее канона
- **Эталон:** премиум-палитра `--color-brand-deep-*` (глубокий синий #0A1628→#1E3A5F), золото #C5A46D, sig-lime #CCFF00, + `--color-semantic-*` светофор go/caution/stop (#269924/#F1C44D/#ED2124).
- **Econometrica:** базовые `--accent-primary #2E5BFF` (electric-blue) + secondary lime, без брендовой глубины/золота, без семантического светофора из канона.

### 3. 🟠 Темы light/fun — ручные, не из канона
- **Эталон:** полные light + fun темы в SSOT (`--color-ui-themes-light-*`, `--color-ui-themes-fun-*` — продуманные беж/золото/земля).
- **Econometrica:** темы `[data-theme=light/fun]` собраны вручную в app.css, не из generated SSOT → расходятся с каноном.

### 4. 🟠 Типографика — не гарантирована
- **Эталон:** self-hosts Inter Variable — `src: url('/fonts/InterVariable.woff2')` (реально встроенный вариативный шрифт, премиум-рендер на любой машине).
- **Econometrica:** Inter только через `local('Inter')` — **нет self-hosted woff2**. На машине без Inter → падение на system-ui (Segoe UI). Премиум-типографика не гарантирована у клиента.

### 5. 🟠 Облик шапки/главной (визуальная сверка выполнена — скрин DocMaster v0.10.0)
Живой скрин эталона (`Desktop/scr/screenshot.png`) vs главная Econometrica (снята через мост):
- **A. Чип продукта:** DocMaster — «DOCS LAB» в electric-blue **pill-капсуле с рамкой** (brand chip). Econometrica (эта ветка) — «ECONOMETRICA / OPTIMIZER MMM» просто текстом в 2 строки, без капсулы. → BrandChip уже сделан на ветке `feat/ai-insights-tier2`, здесь его нет.
- **B. Таймер:** DocMaster — **счёт вверх** `00:27:42` (session elapsed) + иконка. Econometrica (эта ветка) — стенные часы `22:46 МСК` (DigitalClock). → SessionTimer уже сделан на `feat/ai-insights-tier2`.
- **C. 🟠 Карточки главной (самый заметный разрыв):** DocMaster — ДВЕ богатые карточки-задачи, каждая с 3-колоночной структурой «Когда использовать / Что получите / Типичные задачи» + крупная цветная CTA (синяя/оранжевая). Econometrica — ОДНА простая карточка «Визуальный пайплайн» + одинокая кнопка «Новый проект» + ссылка. Эталон плотнее, профессиональнее, «workspace-first».
- **D. Hero-логотип с glow** по центру — есть у ОБОИХ (Econometrica догнала, `539e11f`).
- Компоненты у обоих доменные/scoped (нет общих Button/Card/Modal/Badge). У Econometrica свои MQSBadge/ExpandableCard.

**Важно для стратегии ветки:** пункты A (чип) и B (таймер) УЖЕ закрыты на `feat/ai-insights-tier2` → слияние/перенос tier2 в актуальную ветку закрывает половину визуального разрыва облика. Останутся C (карточки главной) + фундамент (пункты 1–4).

## Рекомендованный путь актуализации (для плана, НЕ выполнять сейчас)
Порядок от корня к листьям (руби по стволу):
1. **Подключить Aurora Hybrid DS:** `@import tokens.generated.css + themes.generated.css` в app.css, регенерировать из `Standards/tokens/`, добавить `build:tokens` в package.json (predev/prebuild). — снимает пункт 1, автоматически подтягивает 2 и 3.
2. **Alias-мост:** старые `--bg-*/--accent-*` → на `--color-ui-*` (alias-слой уже начинали, коммит `da330d1`) — чтобы сотни использований не переписывать разом.
3. **Self-host Inter Variable** woff2 (пункт 4) — дёшево, заметный эффект.
4. **Облик** шапки/карточек под эталон — после визуальной сверки скринов.

## ⚠️ АДВЕРС-АУДИТ ПЛАНА (пересмотр 2026-07-02) — разворот по app-themes
При разведке реализации вскрылось (проверка перед генерацией):
- **Econometrica `content-packs/themes.json` (v5) УЖЕ = канон по light/fun значениям И богаче** appThemes SSOT на ~20 токенов: `--card-accent-*` (fun разноцветные карточки), `--radius-btn/chip:999px` (fun pill-кнопки), `--bg-insight-*` (severity-tint), `--hover-transform`. Результат прошлого дизайн-трека.
- **appThemes SSOT намеренно бедный** (41 переменная = только цвет+объём; per-card/radius/поведение по канону пути B живут в app.css). DocMaster themes.json тоже беден (0 по card-accent/radius/insight).
- **`gen_themes_json` перезаписывает** → наивная генерация из SSOT **регрессировала бы fun-тему** Econometrica (потеря цветных карточек/pill/insight-tint).
- **Визуального выигрыша от переезда НЕТ**: dark app.css уже = канон, light/fun уже = канон+.

**Вывод:** пункты 2–3 карты (палитра/темы) переоценены — по ЗНАЧЕНИЯМ Econometrica вровень/впереди. Реальное отставание = **облик** (карточки главной / чип / таймер — пункт 5/C) + **архитектура** (генерация vs руками) + **шрифт**.

**Скорректированный фундамент (безопасный, low-risk):**
- ✅ Self-host Inter Variable woff2 (чистый выигрыш, 0 риска).
- ✅ Подключить обновлённый `tokens.generated.css` (@import) — открывает brand-токены (deep/gold) для облика этапа 2. Аддитивно.
- ✅ `build:tokens` pipeline ТОЛЬКО для `tokens.generated.css` (не themes.json).
- ⏸️ **app-themes переезд (themes.generated/themes.json из SSOT) — ОТЛОЖИТЬ**: требует аккуратного разбора богатого themes.json на canon-часть (→генерация) + статику (→app.css per-theme `[data-theme]`), высокий риск регрессии fun, нулевой визуальный выигрыш. Отдельным этапом, если нужна архитектурная чистота.
- ➡️ **Реальный визуальный подъём — этап 2 (облик):** карточки главной под эталон + чип/таймер из tier2.

## Открытый вопрос перед планом
Нужна ли живая визуальная сверка (поднять DocMaster для скрина облика рядом с Econometrica), или карты по коду достаточно, чтобы утверждать план актуализации.
