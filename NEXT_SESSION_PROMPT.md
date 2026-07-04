# Aurora Econometrica MMM Optimizer — роутер следующей сессии

> Скопируй в начало новой сессии (cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica`).
> Обновлён 2026-07-04 после марафона E1→UX→UXP→E3→E2+E4→multi-client→HTML.

## 🎯 Состояние: ROADMAP v3 ВЫПОЛНЕН + ЖИВОЙ GUI-ПРОГОН (2 бага холодного старта закрыты)

Петля доверия «предсказание → факт → калибровка» доставлена во все слои
(движки → endpoints → Rust → UI-карточки → PPTX/HTML), доказана живыми
зондами на трёх датасетах (Kagocel, Венарус, MMX) И живым GUI-прогоном.

- Ветка **запушена**: `feat/econ-e1-backtest` @e274f68 (+ живой прогон: G-2, G-4) и
  `feat/econ-commercial-readiness` @83533ad. Merge/PR — решение Антона.
- **Живой GUI-прогон (2026-07-04) вскрыл и закрыл 3 UI-бага холодного старта:**
  · **G-2** (dfc82c6): открытие сохранённого проекта → шаг «Модель» не восстанавливал
    модель, карточки E1/E3 не монтировались (гейт локального stepState). Фикс `$effect`.
  · **G-4** (e274f68): PromisesCard не обновлялась после «Зафиксировать прогноз»
    (onMount-однократность + visibility-навигация). Фикс promisesVersion-триггер.
  · **G-1** (решение Антона A): stepper показывал готовый проект непройденным
    (currentStep=0 + monotonic invariant). Фикс: reconcile ведёт currentStep на
    последний complete-шаг. Живьём: открытие → на Оптимизации, весь путь зелёный.
  · G-2/G-4 — класс [[feedback_onmount_once_stale_under_visibility_nav]] (юнит не ловит).
  · G-3 (use_holidays) и E2 CalibrationPanel разобраны — НЕ баги.
  · PPTX/HTML проверены артефактом (13 слайдов, витрина №6, 0 wireframe; HTML trust+TOC).
  · Реестр прогона: `TEST_FINDINGS_GUI_2026_07_04.md`.
- Гейты зелёные: python 58+ · vitest 797 · svelte-check 0 · verify 43/43 · cargo.
- Отчёты: `docs/audits/{COMMERCIAL_READINESS,E1_BACKTEST,UX_AUDIT,E3_LIFECYCLE,E2_E4}_2026_07.md`.
- Мат-истина дополнена: `docs/MATH_REFERENCE.md` §«Trust loop E1–E4».

## Точки входа (по типу сессии)

| Сессия | Промт/файл |
|---|---|
| **Живой GUI-прогон марафона** (нужно живое окно + мост) | `NEXT_SESSION_gui_clickpath.md` — самодостаточный клик-лист + уроки среды |
| Merge/PR веток | решение Антона; после merge — прогнать полный gate на базе |
| Полная «Валидация одним экраном» (П1 полный) | план в `docs/audits/UX_AUDIT_2026_07.md` §П1; ПОСЛЕ GUI-прогона |
| Следующий этап продукта | ROADMAP v3 закрыт; новый этап — по слову Антона (кандидаты вне анти-фокуса: sigma-samples в pickle для точного predictive; nightly bayesian-coverage; релиз v2.2.0 по aurora-release-update) |
| **Автосезонность А→Б — ПРИНЯТО (Антон, 2026-07-04)** | Делать оба, порядок А→Б. А: Фурье-гармоники годового периода как авто-компонента при detect_seasonality+≥2 лет (Robyn/Meridian-канон; праздники РФ УЖЕ авто — дыра только в гладкой волне, отсюда worse_than_naive Кагоцела) — средний батч. Б: автодетект колонки «продажи категории» + подсказка на Валидации (экзогенный контрол, фарма имеет DSM/IQVIA; «категория минус бренд» для доминаторов; автозагрузки НЕТ — 0 egress) — малый батч. Доказательство = бэктест до/после на Кагоцеле (worse_than_naive → validated). Отдельный этап ПОСЛЕ GUI-прогона |

## Инварианты (соблюдать всегда)

- INV-50: числа клиентов не «улучшать» — править честность. Детерминизм и
  pickle-совместимость (additive) не ломать. Pin Кагоцела — осознанно.
- JS+JSDoc (НЕ TS). Тесты `-n 4`. PowerShell-коммиты here-string `@'...'@`
  БЕЗ прямых двойных кавычек внутри. Узкий pathspec; чужие untracked не трогать
  (в дереве живут чужие: tokens.generated.css modified, model_backend.rs, CC-Sessions/).
- Мост tauri после kill/rebuild полумёртв — читать
  [[feedback_tauri_mcp_bridge_half_dead_after_rebuild]] до любых webview_*.
- Метод: зонд → личная верификация (агенты ~40% FP) → батч+тест → коммит →
  живой gate; реестр = ФАКТ (статусы только после числа-подтверждения);
  multi-client (≥2 датасета) перед ship narrative-изменений.

## Память

Ядро → [[INDEX_econometrica]] (состояние 2026-07-04 сверху). Реестры марафона:
`AUTONOMOUS_WORK_STATE_{E1_BACKTEST,E3_LIFECYCLE,E2_E4}.md` (метод, дизайн-решения
D-*, находки F-*, журналы батчей).
