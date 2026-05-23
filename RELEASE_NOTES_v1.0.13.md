# Aurora AI Econometrica v1.0.13

**Дата:** 26 апреля 2026
**Тип релиза:** Mathematical hardening — Phase 0.1 fix-session

## Главное

Это фундаментальная коррекция математики оптимизатора и качества отчётов. v1.0.13 закрывает 19 дефектов, обнаруженных в ходе live-test и code-аудита, обеспечивая математически эталонные расчёты Marginal ROAS и физически осмысленную оптимизацию бюджета на смешанных единицах (TRPs + рубли).

## Что починилось

### Math chain rule — корректные mROAS values
- Исправлена опечатка `miroas` (с одной i) в narrative_adapter, из-за которой HTML/PPTX отчёты годами показывали **average ROI** в полях, помеченных как «mROAS». Теперь обе метрики выведены отдельными колонками с tooltip-объяснениями.
- Восстановлена полная формула цепного правила: `mROAS = β · hill'(x_norm) · adstock_factor · y_std / mean / unit_cost`. Раньше пропадали два множителя — adstock factor (зависит от θ, n_periods) и /unit_cost. На каналах с большим CPP (типа TRPs) числа были завышены в 100-200×.
- Создан единый helper `_compute_mroas_money()` — single source of truth. Все 5 ранее расходившихся мест (UI chart, optimization.json, insights, HTML отчёт, PPTX) теперь дают одинаковые числа.
- JS marginalROI() в OptimizeStep deprecated — frontend читает authoritative значения с backend.

### Optimizer — реальная оптимизация
- **Дефолты бюджетных границ:** Мин 20% / Макс 200% (было 50%/150%). Раньше при money_budget = current × 1.5 границы зажимали SLSQP до тривиального масштабирования всех каналов на +50%. Новые дефолты дают реальное пространство решений.
- **Multi-start SLSQP** (3 стартовые точки) — защита от застревания в локальном минимуме при money_target = current. Воспроизводимо через фиксированный seed=42.
- **Money mode constraint** — оптимизация в рублёвом эквиваленте (Σ x × unit_cost = const) корректно работает на смешанных единицах. Native sum constraint, который физически бессмыслен на TRP+рубли, больше не используется.
- **Pre-flight feasibility check** — перед запуском SLSQP backend проверяет, что заданный бюджет умещается в границы каналов (с tolerance 0.1%). При нарушении возвращает INFEASIBLE_BUDGET_HIGH/LOW мгновенно (раньше зависание до 90 сек с краш sidecar и watchdog respawn).
- **Diagnostic flags в JSON** — `binding_constraints`, `n_channels_at_max/min`, `min_pct_used`, `max_pct_used`. Используются нарративом для честной диагностики «оптимизатор упёрся в границы».

### Narrative & UX
- **Conditional precision в форматировании процентов** — никаких больше «26% продаж при 0% бюджета» (Performance имел 0.4% spend, округлялось в 0%). Теперь шкала: `0` → "0%", `<0.1%` → "<0.1%", `<1%` → "0.4%", `≥1%` → "26%".
- **Binding-aware narrative** — SCQAR Answer, finding f3 и Recommendation Action 01 теперь синхронизированы по threshold (realloc ≥ 0.5 млн) и учитывают флаги `binding_constraints` / `optimization_converged`. Нет больше противоречий «перебалансировать 0 млн ₽» + «нарастить X».
- **Generic советы → data-driven** — пункты «Burst-планирование» и «Targeted retargeting» (которые были маркетинговым boilerplate, не выведенные из модели) удалены. Заменены на «Контролировать saturation» (с числом каналов под breakeven) и «Замерить эффект через 90 дней».
- **Verdict для high-mROAS underspent** — канал с marginal ROAS > 1.5 и opt > current теперь автоматически получает `Scale` (раньше выдавался `Hold`).
- **Dirty-state hint** — амбер бейдж «⚙️ Настройки изменились» рядом с кнопкой Optimize. UI напоминает запустить оптимизацию заново после смены границ.
- **Sidecar hardening** — try/except SLSQP с graceful fallback, `maxiter=200`, `ftol=1e-7`. Watchdog таймаут 60 → 90 сек.

### Внутренние улучшения
- 2 новых analytical unit-теста с пеной-и-бумагой ответом (`test_compute_mroas_analytical_synthetic` дает точно 500 для специально подобранных параметров).
- Property-based test на инвариантность mROAS относительно unit_cost: `mROAS(uc=K) × K = mROAS(uc=1)`.
- Edge cases: нулевой spend / mean / beta / unit_cost — все возвращают 0.
- Adstock params loss audit: подтверждено, что параметры не sample-ятся в NUTS, training/optimizer/scenario симметрично используют library defaults. Phase 1.1 будет делать joint adstock+Hill MCMC.
- Math reference document: `docs/MATH_AUDIT_v1_3_PHASE_0_1.md` — single source of truth для chain rule.

## Что показывает live-test (Kagocel, 31 неделя, 7 каналов)

```
Optimize defaults 20/200, money budget = current:
  Lift: +6.0% (вместо 0.0% pre-fix)
  Статьи: +200% (3.87M → 11.6M, mROAS 52.92×) — verdict Scale ✅
  TRPs: -0.1% (mROAS 0.014×, deeply saturated) — verdict Cut ✅
  binding: False, converged: True
  
Tight bounds 50/130, money +50%:
  binding: True, at_max: 6 — диагностика binding triggers
  Insights panel: «Оптимизатор упёрся в границы — расширьте Мин./Макс. %»
  
Infeasible budget ×5:
  Pre-flight rejection в 0.05s с INFEASIBLE_BUDGET_HIGH (было 60+ сек hang)
```

## Совместимость

- Старые проекты (.pkl от v1.0.12) **совместимы** — pickle schema не менялась относительно v1.0.13-math-audited.
- HTML/PPTX/XLSX отчёты сохраняют структуру, но числа в колонке mROAS теперь корректные. Если вы сравнивали с предыдущими отчётами — это ожидаемое расхождение.
- Сценарии (saved scenarios) совместимы.

## Минимальные требования

- Windows 10 / 11 (x64)
- 4 ГБ свободного RAM при обучении модели
- WebView2 Runtime (устанавливается автоматически)
- Подписка на Claude AI с установленным CLI

---

**Полные коммиты:** `e567a37` · `56984ec` · `a3662a0` · `75872db`
**Math reference:** `docs/MATH_AUDIT_v1_3_PHASE_0_1.md`
**Plan:** `plans/joyful-strolling-fiddle.md`
