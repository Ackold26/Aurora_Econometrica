# Audit findings — полировка Econometrica v2.3.1 (чистый внешний аудит)

Формат: severity | файл:строка | суть | сценарий | вердикт(CONFIRMED/PLAUSIBLE)

## ИТОГ: реальных дефектов НЕ найдено (0 CRIT, 0 HIGH, 0 MED, 0 LOW)

Дифф проверен целиком, все зоны неуверенности handoff §4 отработаны прицельно с воспроизведением вживую. Ни одна не дала воспроизводимого дефекта.

## Отработанные гипотезы и почему сняты

- **§4.1 B call-site выбор (lib.rs:92/113/311/458).** Тип `online.vault_versions: Option<HashMap<String,u32>>` совпадает с `Option<&HashMap>` через `.as_ref()`. 92 (missing) и 458 (open_cabinet) → `online.vault_versions.as_ref()`; 113 (stale) → `Some(server_versions)`; 311 (update_content, «мёртвая» команда) → `None`. resolve_vault_version при отсутствии записи кабинета в карте делает fallback на content_version. Rust компилируется, 19 тестов content_updater зелёные. Регрессии нет. СНЯТО.

- **§4.2 resolve_vault_version парсинг версии.** `"cabc".trim_start_matches('c')`→`"abc"`→parse Err→unwrap_or(0)→0, при 0 запись версии пропускается (ver_num>0). `"c5c6"`→`"5c6"`→Err→0. Безопасная деградация, юнит-тест это фиксирует (assert на "cabc"→0). СНЯТО.

- **§2 Нулевая регрессия при старом сервере.** vault_versions==None → resolve_vault_version fallback на content_version — идентично прежнему `version.trim_start_matches('c').parse().unwrap_or(0)`. Подтверждено тестом resolve_vault_version(...,None,"c6")==6. СНЯТО.

- **§4.3 NFKC-побочки в grounding.** NFKC применяется ТОЛЬКО в sanitizePromptFragment (вопрос/методология/tier1-инсайты). context.facts (tier2-context.js:398) сериализуется JSON.stringify БЕЗ санитизации; grounding (insights-grounding.js) сверяет числа из jsonFacts, graders numbersGrounded использует только {jsonFacts: ctx.facts}. NFKC меняет x²→x2, ½→1⁄2, ①②③→123, ５→5 — но эти символы попадают лишь в свободный текст, не в факты движка (обычные JSON-числа). Путь grounding-чисел NFKC не задет. Заявление handoff верно. СНЯТО.

- **§4.4 orphan-парсинг legacy.** regex /(mmm-[\w\-]+) ловит ровно 9 legacy-стемов из LEGACY_COMMANDS.md. Линтер вживую: EXIT 0 на текущем состоянии; при внесённом orphan-файле (zzz-orphan-probe.md) EXIT 1 с точным сообщением — детектор НЕ мёртвый обвес. Хрупкость (упоминание /mmm-* в changelog ослабит детектор) признана в handoff §4.4 как осознанный компромисс, ложного FAIL не даёт. СНЯТО.

- **§4.5 маркер «оцен».** Расширение «оценк»→«оцен» ловит оценочно/оценить/оценка. Это эвал-грейдер (не прод), компромисс полнота-vs-точность заявлен. numbersGrounded PASS/FAIL прогнан на 3 кейсах — различает грунт/негрунт/помеченное. СНЯТО.

- **report.rs filter_map→map (§2 инвариант).** Замыкание (report.rs:281-295) не содержит `?`/early-return, всегда возвращает json!({...}); старый filter_map возвращал Some(json!({...})) безусловно. Семантически эквивалентно. СНЯТО.

- **fingerprint.rs map_or(false,f)→is_some_and(f).** Семантически тождественно по определению is_some_and. clippy --lib = 0 warnings. СНЯТО.

- **online_auth.rs docstring `>24h`→«дольше 24 ч».** Правка внутри `///`-комментария, поведение не задето. СНЯТО.

- **A CI_TERM_RE scoped (?i:…).** Вживую: ловит «доверительный интервал»/«ДОВЕРИТЕЛЬНЫЙ ИНТЕРВАЛ»/смешанный регистр; «CI» строго заглавными (не ловит «ci» в society/specific); «доверительная беседа» без «интервал» не ловится. Линтер промптов EXIT 0, 19/19. СНЯТО.

- **D тесты econ-project-context / graders-eval.** vitest: 32/32 на затронутых файлах, полный прогон 1279/1279. summarizeValidation реально читает r.high_correlations/r.warnings (не тавтология). «расхождение» noEnvPaths C:\ в раннем прогоне оказалось артефактом bash/heredoc эскейпинга обратных слэшей — настоящий vitest на реальном файле зелёный. СНЯТО.

## Верификация окружения (прогнано вживую)
- `npx vitest run`: 79 файлов, 1279 тестов — все PASS.
- `cargo test --lib content_updater`: 19 PASS (вкл. новый resolve_vault_version).
- `cargo clippy --lib`: 0 warnings/errors.
- CI clippy = `cargo clippy --manifest-path src-tauri/Cargo.toml -- -D warnings` (без --all-targets) → test-only warnings не блокируют, как заявлено §3.
- `python tools/lint_prompt_commands.py`: OK 19/19, EXIT 0.
- `python tools/check_help_consistency.py`: OK, EXIT 0; на orphan-пробе EXIT 1 (детектор жив).
