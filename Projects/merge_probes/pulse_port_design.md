# Пульс: перенос дизайн-элементов (hero-glow + settings chip)

Задача: вернуть два оформительских элемента, утверждённых владельцем в живой подгонке и потерянных при развитии продукта:
1. Свечение за логотипом на главной (`.hero-zone::before`, radial-gradient) — в `src/routes/+page.svelte`.
2. Чип-оформление подзаголовка в настройках (`.settings-logo-subtitle`) — в `src/routes/settings/+page.svelte`.

Образец: `git show origin/feat/ai-insights-tier2:<путь>`. Работаю ТОЛЬКО в этих двух файлах, не коммичу.

Старт: 2026-08-04.

Готово: оба элемента внесены. npm run check — 0 ERRORS, 177 WARNINGS (без изменений от базы). Отчёт отправлен team-lead.
