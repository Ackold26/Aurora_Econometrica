# Аврора + кабинет эконометриста — роутер следующей сессии

> Скопировать в начало новой сессии. cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_avrora`
> (git worktree ветки `feat/econ-avrora-assistant`). Создан 2026-07-12.
> Полное состояние → память [[INDEX_econometrica]] (шапка 2026-07-12).

## Что сделано и на origin (НЕ переделывать)

Ветка `feat/econ-avrora-assistant` от planning-mode `36857cd` — **запушена**
(`origin/feat/econ-avrora-assistant`, 16 коммитов, 7 тегов, verify 0/0). Гейты:
vitest 1142 · svelte-check 0 · cargo обе редакции ok.

- **Ассистент «Аврора» восстановлен портом** (не merge — 233 коммита расхождения):
  grounding-страж INV-50, «Что если», Rust-мост `econ_ask_insight`, тумблер «только локально».
- **RAG-клиент узла Б** `rag_client.rs::econ_rag_search` → `127.0.0.1:8801/search`
  corpus=econometrics (17 первоисточников от трека B), гейты как Claude-egress.
- **Правила промпта** 4/11/12 (переводчик, правдоподобный диапазон).
- **Аудит-фиксы** (2 Opus): validate_rag_url (http только loopback), interlock,
  askEpoch (stale-write), sanitizeMethodologyFragment.
- **Вырезка телеметрии** (stripOpt/Model/DecompTelemetry): промпт −25%, страж чист.
- **Живой headless-прогон** доказал цепочку (ноль выдуманных чисел) —
  `Projects/AVRORA_LIVE_RUN_2026-07-12.md`.
- **Петля** `rag-query.js`: тематизация RAG двуязычно по шагу + humanizeSource.
- **Кабинет эконометриста**: зрелость 2.0→4.0, эфф 3.0→4.3. Документ аудита —
  `Dev/Aurora_Econometrica/docs/audits/CABINET_ECONOMETRIST_AUDIT_2026-07-12.md`
  (коммит `fecdb84` в kpi-units). SSOT-страж `tools/check_cabinet_drift.py` +
  эвал-харнес `tools/cabinet_eval` (6 кейсов, автогрейдеры реюз insights-grounding).

## ОСТАЛОСЬ (три хвоста, перенесены Антоном на новую сессию)

### 1. Живой RAG в рантайме + прогон ассистента В ОКНЕ
- Поднять туннель до узла Б системным ssh.exe (НЕ `! ssh-add` — уходит в Git-Bash-агент;
  узел Б принимает `ackol@EVO-X1` в Windows-агенте; секрет `AURORA_CLIENT_SECRET`
  из `~/.secrets/engine.env`, заголовок `X-Aurora-Auth`). Грабли → [[reference_windows_ssh_agent_dual_gitbash_vs_openssh]].
- Прогнать тематизированный запрос живьём → убедиться, что поднимает Jin 2017/Chan-Perry
  (гипотеза доказана вчерашней пробой adstock→Jin 2017; нужна финальная строка «по Jin 2017»
  в ответе Авроры на релевантных хитах).
- Прогон В ОКНЕ: `npm run tauri:dev` (с мостом, НЕ `npm run tauri dev`), окружение
  БЕЗ `ANTHROPIC_API_KEY` (баланс исчерпан → claude.ai-подписка снятием ключа),
  клики по кнопкам InsightsPanel. AVT-протокол: спросить состояние машины (:5173/:9223),
  мост tauri после rebuild полумёртв → [[feedback_tauri_mcp_bridge_half_dead_after_rebuild]].

### 2. Мерж линии
- Ветка сцеплена с `feat/econ-kpi-units` и `feat/econ-planning-mode` (общая база `36857cd`).
  Решение о порядке мержа/релиза — Антон. Перед мержем: `--strict-pair` cabinet-drift сработает
  в основном дереве (сверить кабинет econometrist после мержа).

### 3. Петля улучшения кабинета на находках эвал-харнеса
- Живой smoke харнеса поймал (реальные дефекты поведения промпта): в why-channel модель
  посчитала запретное отношение mROI/ROI + выдумала «помесячный расход» (числа не из данных).
- Порядок петли: правка промпта → `node tools/cabinet_eval/run_eval.mjs --case <id>` →
  сравнить грейдеры → фиксация. Флагманы: 6 UI-команд + путь Авроры.
- Медиум-хвосты кабинета из аудит-документа §«Что осталось»: теги [MODELED] кабинет↔Аврора
  свести к одному источнику (убрать зависимость от sanitizeAvroraText); эвал в CI (dry-гейт).

## Метод-уроки сессии
[[strip_graphic_telemetry_from_llm_prompt]] · [[thematize_rag_query_bilingual_by_pipeline_step]] ·
[[reference_windows_ssh_agent_dual_gitbash_vs_openssh]] · оперрежим оркестратор+субагенты,
находки верифицировать лично (поймано 4 расхождения субагентских отчётов).
