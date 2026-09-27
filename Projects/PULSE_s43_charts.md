# PULSE s43 — правка графиков этапа «Модель»

Задача (своими словами): в развороте на весь экран панели сходимости (ConvergenceDashboard)
графики (PPCScatter, PPCResidualsChart, Факт vs Прогноз, R-hat) не растягиваются по высоте —
остаются на фиксированных 240/260px, три четверти экрана пустуют. Плюс на PPCScatter налезают
друг на друга заголовок/подзаголовок и легенда серий. Плюс оси PPCScatter (и возможно соседних
графиков) идут от нуля вместо диапазона данных — облако точек сжато в угол, диагональ идеальной
подгонки не проходит по 45°.

План:
1. Прочитать ExpandableCard.svelte, PPCScatter.svelte, PPCResidualsChart.svelte, ConvergenceDashboard.svelte.
2. Дефект 1 (высота): придумать механизм передачи "expanded" от ExpandableCard к 4 графикам панели.
3. Дефект 2 (оси от нуля): scale:true + единый min/max по обеим осям для факт-vs-прогноз графиков.
4. Дефект 3 (наложение подписей): убрать внутренний title/legend конфликт в PPCScatter.
5. Прогнать vitest + svelte-check, зафиксировать числа до/после.
6. Отчитаться main.

Старт: 2026-09-12.

Факт: все три дефекта исправлены (ExpandableCard.svelte, PPCScatter.svelte,
PPCResidualsChart.svelte, ConvergenceDashboard.svelte). vitest 1493/1493 (106 файлов),
npm run check 0 ошибок / 177 предупреждений — оба совпадают с эталоном до правок.
Отчёт отправлен main. Завершено.
