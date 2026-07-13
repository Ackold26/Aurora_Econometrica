# Econometrica — роутер следующей сессии (после полировки + CI-hardening 2.3.1)

> Скопируй в начало новой сессии. cwd = `D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica_v230`
> (worktree релизной ветки `feat/econ-v2.3.0`). Обновлён 2026-07-13 (конец сессии полировки).

## Контекст — что сделано (НЕ переделывать)

**Полировка v2.3.1 + внешний аудит + CI-hardening ЗАВЕРШЕНЫ.** 16 коммитов на `feat/econ-v2.3.0`,
**ЗАПУШЕНО** на origin (`e63176b`), открыт **PR #3 → master** для CI.

**Блоки:**
1. **Полировка (7)** `ea78812`..`629029c`: 2a clippy-гейт · дыры 3 линтеров-стражей · NFKC-гомоглифы
   sanitize · next-quarter секция-6 · per-cabinet версия доставки (латентная до 2c) · юнит-тесты 6 грейдеров.
2. **Внешний diff-аудит полировки** `e270353` — opus, чистый контекст, **0 находок**, готов к merge.
3. **installer** `3a7b9a2` — влиты актуальные NSIS-хуки из kpi-units (фикс кодировки кракозябр + окно успеха).
4. **CI-hardening** (PR #3 вскрыл невидимое локально — 3 класса):
   - `3a96607` UTF-8 stdout линтеров (Windows cp1252 UnicodeEncodeError);
   - `0e61e89` pymc-скип (7 MCMC-тестов importorskip) + filelock в CI-депы;
   - `11139b2` **РЕАЛЬНЫЙ БАГ** y_actual порча (notna-маска убивала детект серединных NaN) + устаревший
     тест brand_perf (локализация);
   - `e63176b` **РЕАЛЬНЫЙ БАГ** resolver кросс-платформа (Path.name на Linux не бьёт Windows-путь → fallback
     C3-N3 не работал на облачном Linux-sidecar).
5. **RELEASE_PLAN_2.3.1.md** `80aa5c8` — решения Антона по выкату зафиксированы.

**Гейты локально зелёные:** cargo 191 · clippy 0 · svelte 0 · vitest 1279 · 3 линтера · cabinet_eval --dry 6/6.
**CI (PR #3):** Test & Lint ✅ · Help Sync ✅ · Python Tests — было 23 fail → 0 (проверить финальный run
на `e63176b`, если не зелёный — добить).

## 🔴 РЕЖИМ: выкат идём ВМЕСТЕ с Антоном (GUI/live/необратимое)

Полная точка входа выката — **`Projects/RELEASE_PLAN_2.3.1.md`** (решения + пошаговый план 2b с точками
«вместе»). Опубликовано сейчас клиентам: облачная **2.1.0** → цель **2.3.1** (широкий смоук).

## Задачи продолжения (приоритет)

### 1. 🔴 Проверить финальный CI PR #3 (первый шаг)
`gh run list --branch feat/econ-v2.3.0 --limit 1` → статусы Test&Lint + Python Tests на `e63176b`.
Оба зелёные → CI-гейт закрыт. Если Python Tests ещё красный — добить остаток (эмуляция локально
`python -c "import sys; sys.modules['pymc']=None; import pytest; pytest.main([...,'-n','0'])"`, но
помнить: эмуляция Windows ≠ CI Ubuntu для платформо-зависимого — проверять на реальном CI).
⚠️ Сеть до github только через **`dangerouslyDisableSandbox: true`** (sandbox режет DNS).

### 2. 🔴 Выкат 2.3.1 ВМЕСТЕ (по RELEASE_PLAN_2.3.1.md)
Живой прогон в окне (`npm run tauri:dev`, env БЕЗ `ANTHROPIC_API_KEY`) → bump 2.3.1 ×4 → **пересборка
VAULT** с промптами + греп свежей строки → сборка **только облачной** (`npm run tauri build`, БЕЗ local) →
смоук .exe (окно успеха + нет кракозябр) → публикация: **Supabase `app_versions` первично** (Edge —
реальный канал; `rosst-updates/latest.json` — legacy fallback), только `aurora-econometrica-gui` → тег
`v2.3.1` → мерж PR #3 в master. Без code-signing (сертификата нет → пометка, SmartScreen предупредит).

### 3. Внешний аудит новых коммитов (после аудита полировки e270353)
Коммиты `e270353..HEAD` (installer + 5 CI-фиксов) НЕ прошли внешний diff-аудит. Среди них **2 реальных
бага** логики (y_actual, resolver) — стоит адверсариальный аудит на регресс. `git diff e270353..HEAD`
чистым субагентом (см. handoff.md).

### 4. Отложенное (эскалация/после выката)
- **G9 geo-иерархия** (продуктовое решение, эскалация Антону) · **G7 SBC** (движковое) · **справка
  econometrist** (8 команд + бандл + возврат кнопки, к сборке) · **2d frontend BUNDLED_FRONTEND_VERSION**
  (build-time, к сборке) · **2c серверная vault_versions** (активирует латентный фикс B).
- Мелочи в отчёт: Батч2 channelNames sanitize, checksum vault пустой (by-design).

## Инварианты/правила
- INV-50 честность метрик (`insights-grounding.js` НЕ трогать). Кабинет-эконометрист ТОЛЬКО в Econometrica.
- JS+JSDoc не TS. Клиентский текст: короткое тире «–», без англицизмов, без slash-команд.
- Релиз по СВОЕМУ каналу; промпты в VAULT не content-pack; content-pack правка → `sign_content_pack.py --bump`.
- Shared-репо: зонд HEAD/origin ДО коммита/push; узкий pathspec. Сеть → `dangerouslyDisableSandbox`.

## 🔴 Руководство по стилю действий (прочитать ПЕРВЫМ)
1. **CI в чистом окружении ловит невидимое локально.** Эта сессия: PR/CI поймал 3 класса, не видных на
   моей машине — кодировка (Windows cp1252 UnicodeEncodeError на русском print), CI-депы (pymc/filelock
   не в lightweight), **кросс-платформа** (Linux basename ≠ Windows). Гонять PR/CI ДО публикации обязательно.
2. **Эмуляция локально ≠ CI.** `sys.modules['pymc']=None` + `-n 0` (против xdist-воркеров в своих процессах)
   — хороша для pymc-скипов, НО платформо-зависимое (Path.name Windows vs Linux) эмуляция на Windows НЕ
   ловит — только реальный CI (Ubuntu). Для path/encoding-багов доверять CI, не локальному прогону.
3. **Разбирать «устарел тест vs баг» по существу, не xfail вслепую.** Решение Антона окупилось: за
   filelock-маской 3 «фейла» оказались 2 РЕАЛЬНЫХ бага (y_actual silent corruption, resolver Linux-fallback)
   + 1 устаревший тест. xfail замаскировал бы порчу данных клиента. Читать код+тест, понять замысел.
4. **`gh run watch --exit-status` ОБМАНЫВАЕТ** на уже-завершённом run (вернул exit 0 при статусе failure).
   Проверять статус ЯВНО: `gh run view <id> --json jobs --jq '.jobs[]|"\(.name): \(.conclusion)"'`.
5. **Windows bash-эскейпинг `\` в heredoc/`python -c`** ломается (SyntaxError на `\` в строке) — не
   доверять grep/`git show > tmp` для проверки кириллицы/путей, использовать парсер/файл напрямую.
6. **Сеть до github — только `dangerouslyDisableSandbox: true`** (sandbox режет DNS, fetch «Could not
   resolve host»). Локальные git-операции (commit/status/log) sandbox не требуют.
