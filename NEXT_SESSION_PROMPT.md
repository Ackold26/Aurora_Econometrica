# Aurora Econometrica MMM Optimizer — роутер следующей сессии

> Скопируй в начало новой сессии (cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica`).
> Обновлён 2026-07-04 после марафона E1→UX→UXP→E3→E2+E4→multi-client→HTML.

## 🎯 Состояние: ROADMAP v3 ВЫПОЛНЕН ЦЕЛИКОМ

Петля доверия «предсказание → факт → калибровка» доставлена во все слои
(движки → endpoints → Rust → UI-карточки → PPTX/HTML) и доказана живыми
зондами на трёх клиентских датасетах (Kagocel, Венарус, MMX).

- Ветки **запушены**: `feat/econ-e1-backtest` @9b72f22 (39 коммитов) и
  `feat/econ-commercial-readiness` @83533ad. Merge/PR — решение Антона.
- Гейты зелёные: python 58+ · vitest 791/791 · svelte-check 0 · verify 43/43 · cargo.
- Отчёты: `docs/audits/{COMMERCIAL_READINESS,E1_BACKTEST,UX_AUDIT,E3_LIFECYCLE,E2_E4}_2026_07.md`.
- Мат-истина дополнена: `docs/MATH_REFERENCE.md` §«Trust loop E1–E4».

## Точки входа (по типу сессии)

| Сессия | Промт/файл |
|---|---|
| **Живой GUI-прогон марафона** (нужно живое окно + мост) | `NEXT_SESSION_gui_clickpath.md` — самодостаточный клик-лист + уроки среды |
| Merge/PR веток | решение Антона; после merge — прогнать полный gate на базе |
| Полная «Валидация одним экраном» (П1 полный) | план в `docs/audits/UX_AUDIT_2026_07.md` §П1; ПОСЛЕ GUI-прогона |
| Следующий этап продукта | ROADMAP v3 закрыт; новый этап — по слову Антона (кандидаты вне анти-фокуса: sigma-samples в pickle для точного predictive; nightly bayesian-coverage; релиз v2.2.0 по aurora-release-update) |

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
