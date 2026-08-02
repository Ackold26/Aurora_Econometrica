# Починка preflight-проверки Econometrica — находки 5 и 6

## Пересказ задачи своими словами

Предварительная проверка данных (preflight) перед обучением модели врёт в двух местах:

1. **Находка 6:** когда пользователь явно выбирает движок OLS, объём наблюдений (n_obs) всегда
   помечается «надёжным» (`banner_tone: 'good'`) независимо от реального n — потому что
   `recommend_engine` при активном override коротко замыкается. На 12 строках баннер должен
   кричать «данных мало», а молчит.
2. **Находка 5:** причина пропуска проверки приоров (`prior_predictive`) считается по движку,
   который РЕКОМЕНДОВАН системой, а не по тому, которым реально пойдёт обучение. Если движок в
   настройках — «Байесовский», а система рекомендует OLS (мало строк), пропуск помечается
   «неприменимо к выбранному способу», хотя обучаться в итоге будет байесовская модель — для
   которой проверка приоров как раз нужна и не выполняется.

Обе правки — в честность отображаемого клиенту вердикта, без изменения самой модели.

## План

1. Прочитать релевантный код: `ols_modeler.py::recommend_engine`, `server.py` (preflight-агрегация,
   строки ~920-940), `ConfigPanel.svelte` (передача movdeOverride / modelEngine).
2. Находка 6: написать падающий тест на `n_obs_tone` независимо от override → починить →
   доказать красноту откатом правки.
3. Находка 5: написать падающий тест на причину пропуска по фактическому движку → починить
   контракт ConfigPanel↔server → доказать красноту откатом.
4. Прогнать полный тестовый набор `sidecar/econometrica/tests/`, зафиксировать итог.
5. Обновить словари `PREFLIGHT_SOURCE_RU` / `PREFLIGHT_SKIP_RU` при новых ключах.
6. Коммит своим pathspec (`git commit --only`), без пуша.
7. Заполнить итоговую таблицу сочетаний (n, движок) с изменившимся вердиктом.

## Отметки

- **[старт]** Файл создан. Подтверждено: `pwd` = `D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica_v230`,
  `git rev-parse --show-toplevel` = то же самое (это изолированный git worktree, отдельный от
  `Aurora_Econometrica` и других веток), branch = `feat/econ-v2.3.0`, HEAD = `90eda78`. Начинаю
  чтение кода.

- **[код прочитан + оба факта подтверждены живьём]** `ols_modeler.py::recommend_engine` (533-594),
  `server.py::aggregate_preflight_tier`+`preflight()` (896-1059), `ConfigPanel.svelte` (279-490).
  `modelEngine` store default = `'bayesian'` (`project-state.js:998`), авто-подстраивается по n
  в `ImportStep.svelte:154-157`, но пользователь может вручную оверрайднуть (`selectEngineOverride`,
  persist в localStorage per-project) — то есть сценарий находки 5 (25 строк, ручной bayesian при
  auto-рекомендации ols) реально достижим.

  🔴 **Дополнительный факт, шире описанного в находке 6:** зондом подтверждено, что
  `_validate_mode(None)` (server.py:796-797) возвращает **строку `'bayesian'`**, а не `None`.
  `preflight()` вызывает `recommend = recommend_engine(n_obs, override=mode_override)` уже ПОСЛЕ
  прогона через `_validate_mode` — то есть override всегда non-None (либо явный `'ols'`, либо
  подставленный `'bayesian'` по умолчанию). Значит ветки `n_obs<20`/`20≤n<30` в `recommend_engine`
  были МЁРТВЫМ КОДОМ при вызове через `/compute/preflight` — override-ветка срабатывала ВСЕГДА,
  независимо от того, послал ли фронтенд `modeOverride`. Проверено зондом:
  `recommend_engine(12, override=_validate_mode(None)[0])` → `banner_tone: 'good'`, хотя n=12<20.
  Решение координатора по находке 6 («n_obs_tone считать по n всегда, независимо от override»)
  чинит и эту более широкую версию дефекта тем же полем — отдельного контрактного разъезда не
  требуется. Записываю здесь, чтобы не потерялось: старая логика n_obs-баннера была нерабочей
  для ЛЮБОГО вызова preflight, не только при явном выборе OLS.

- **[правка 1/2 — находка 6, готова]** `ols_modeler.py::recommend_engine`: добавлено
  `_honest_n_obs_tone(n_obs)` и поле `n_obs_tone` в каждую из 4 веток возврата (честный тон по n,
  не зависит от override). `banner_tone` не тронут. `server.py::aggregate_preflight_tier`:
  `by_source['n_obs']` теперь берёт `n_obs_tone` вместо `banner_tone` + обновлён докстринг.

- 🔴 **[находка 5 — НЕ подтвердилась эмпирически, откатываю правку, докладываю фактом]**
  Сначала реализовал правку по ТЗ (поле `selected_engine` в `PreflightRequest`, `training_engine =
  req.selected_engine or recommended_mode`, проброс через `econometrica.rs` + `ConfigPanel.svelte`
  `selectedEngine: engine`). Перед коммитом прогнал сценарий из ТЗ через РЕАЛЬНЫЙ `preflight()`
  end-to-end (n=25, `mode_override=None` — именно так шлёт ConfigPanel при `engine==='bayesian'`)
  и получил: `recommended_mode == 'bayesian'`, `prior_predictive` посчитан, `skipped == {}`. То есть
  описанный сбой НЕ воспроизводится.

  **Причина (проверено зондом дважды):** `server.py:796-797` `_validate_mode(None)` возвращает
  строку `'bayesian'`, а НЕ `None`. `preflight()` вызывает `recommend_engine(n_obs,
  override=mode_override)` уже ПОСЛЕ этой валидации — то есть override, доходящий до
  `recommend_engine`, НИКОГДА не бывает `None`: это либо явный `'ols'`, либо подставленный
  `'bayesian'`. `recommend_engine`'s override-ветка (533-560) срабатывает всегда, когда override
  не `None` → `recommended` = ровно override. Единственный вызывающий фронтенд — `ConfigPanel.svelte`
  (проверено grep по всему `src/` — других мест вызова `econ_preflight` нет), и он шлёт
  `modeOverride: engine === 'ols' ? 'ols' : null`. Итог: `recommended_mode` в реальном пайплайне
  ВСЕГДА равен фактически выбранному `engine` (для обоих его значений) — не благодаря
  преднамеренному фиксу, а по совпадению двух независимых dead-code эффектов
  (`_validate_mode`'s None→'bayesian' default + override-короткое замыкание в `recommend_engine`).
  Разъезд «рекомендация ≠ факт», который описывает находка 5, структурно не может возникнуть при
  текущей связке `ConfigPanel` → `_validate_mode` → `recommend_engine`.

  **Что откатил:** `server.py` (поле `selected_engine`, переменная `training_engine`, обе точки
  использования, добавка в докстринг `aggregate_preflight_tier`), `econometrica.rs` (параметр
  `selected_engine` команды `econ_preflight`), `ConfigPanel.svelte` (`selectedEngine: engine`).
  `git diff --stat` подтверждает: `econometrica.rs` и `ConfigPanel.svelte` — 0 diff (чистый откат),
  в `server.py`/`ols_modeler.py` остались только правки находки 6.

  **Не трогаю дальше:** первопричина (`_validate_mode`'s None→'bayesian' default) — общая функция,
  используется и `/compute/train`'s `mode` (где None→bayesian корректен по смыслу как дефолт
  движка), поменять её семантику только для `mode_override` — контракт шире двух полей, которые
  мне поручены (стоп-условие ТЗ). Решение — за координатором.
