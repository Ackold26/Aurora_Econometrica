---
tags: [session, compressed, econometrica, v1.0.9-rc2, stability, multicore-mcmc, port-isolation]
type: session
updated: 2026-04-22
---
# Quick Reference
**Topic:** Econometrica v1.0.9-rc2 — follow-up к rc1 по результатам live-теста IT Паши на CLOUDEAI RDP (2026-04-21). 7 технических фиксов стабильности + multi-core MCMC (3-8× speedup), опубликован GitHub pre-release, ждём Пашу на повторный прогон чеклиста.

**Key files:**
- Code: `sidecar/econometrica/server.py`, `engines/validator.py`, `engines/modeler.py`, `build_sidecar.py`, `requirements.txt`
- Docs: `CHANGELOG.md`, `RELEASE_NOTES_rc2.md`, `.gitignore`
- Memory: `MEMORY.md`, `project_econometrica_v109_progress.md`, `project_port_isolation_phase2_scope.md` (new), `feedback_sidecar_rebuild_required.md`, `feedback_live_test_loop_pattern.md` (new)
- Skill: `C:/Users/ackol/.claude/skills/aurora-fix/SKILL.md` (+V34-V39 rules, updated V29, +7 incidents)
- Plan: `C:/Users/ackol/.claude/plans/shimmying-toasting-orbit.md`

**Status:**
- ✅ rc2 published: commit `a99b126`, tag `v1.0.9-rc2`, GitHub pre-release https://github.com/Ackold26/aurora-releases/releases/tag/v1.0.9-rc2
- ✅ NSIS 177.86 MB, SHA256 `6AE6524D8A235D087CA641000FA4957D3D6BA102598D4114C538EB62C34CF42D`
- ✅ Smoke-test локально прошёл: `/health` 10/10 пакетов, JAX 8 devices, asyncio spam=0, arviz split packages загружены
- ✅ rc1 помечен «superseded by rc2»
- ✅ Сообщение Паше подготовлено (тёплое от Маши с чеклистом из 6 пунктов)
- ⏳ Pending: фидбек Паши с CLOUDEAI, затем этап 2 (UX dialog.save + отчёт Радомира), затем Phase 2/3 port isolation на 9 продуктов

## Learnings

### rc → live-test → rc+1 паттерн работает
Client-specific окружения (multi-user RDP, cp1251 locale, roaming profile, конкретное железо) **не воспроизводятся на dev-машине**. Попытка предсказать все баги = waste. Выпуск rc + live-test клиента + 7 фиксов одним релизом за 1 день — продуктивнее чем 3 итерации dev-догадок.

### Класс «invisible на dev» багов для Windows FastAPI sidecar
- **plain-text 500** под RemoteApp — uvicorn default handler без JSON envelope → Rust parse error
- **arviz 0.23.4+ split packages** (arviz_base/stats/plots) — `--collect-all=arviz` их НЕ тянет
- **UnicodeEncodeError на cp1251** — `print('✓')` падает
- **JAX single device на CPU** — `chain_method='vectorized'` свёртывает все цепи в 1 ядро
- **Windows asyncio spam** — сотни `ProactorBasePipeTransport._call_connection_lost` при client disconnect
- **requirements.txt incomplete** — на dev всё стоит руками, на clean server — pip install не соберётся

### Критичный порядок в server.py
`XLA_FLAGS` должен быть установлен **до любого import (кроме os/sys)**, иначе JAX зафиксирует 1 device forever. Single assignment semantics. `setdefault` respects user override.

### `numpyro.set_host_device_count` избыточен при XLA_FLAGS
Обе функции делают одно и то же (устанавливают XLA_FLAGS). При наличии правильного XLA_FLAGS вторая функция — no-op.

### HTTPException pass-through в global handler
`@app.exception_handler(Exception)` по документации FastAPI игнорирует HTTPException, но поведение хрупко между версиями. **Explicit** `isinstance(StarletteHTTPException): raise exc` в начале handler'а = надёжно. Плюс `str(exc)[:500]` — избегаем длинных путей в JSON body.

### Surgical vs broad silence
`logging.getLogger('asyncio').setLevel(CRITICAL)` убил бы legit asyncio errors. Правильно — `logging.Filter` с substring check на `_ProactorBasePipeTransport._call_connection_lost`, остальное проходит.

### `chain_method` должен быть динамическим
Жёсткий `'parallel'` ломается на 1-device машинах. Правильно: `parallel if jax.devices()>1 else vectorized`. Плюс env override `AURORA_MCMC_CHAIN_METHOD` для rollback без rebuild.

### Env flags = rollback без переустановки
На RC-этапе обязательны. `AURORA_MCMC_CHAIN_METHOD=vectorized`, `AURORA_NUTS_BACKEND=pymc`, `AURORA_MCMC_CORES=1` — клиент откатывается мгновенно при регрессии.

### IT клиента может патчить код на сервере
Паша пропатчил `C:\Program Files\...\sidecar\` руками. Без переноса в master — auto-update затирает работу. **Всегда** сверять changelog клиентского патча с master и вкладывать в следующий rc.

### Post-build freshness check автоматически
`npm run tauri build` НЕ пересобирает sidecar. Ручное сравнение timestamp'ов — error-prone. Автоматизировать в `build_sidecar.py`: exit 1 если любой .py новее .exe после sync.

## Decisions

1. **Version остаётся 1.0.9, tag = rc2.** numeric version не меняется между rc1/rc2/stable — это semantic, tag отличается.
2. **rc1 оставить на GitHub**, пометить superseded в description (не удалять — чтоб не сломать тех кто уже скачал).
3. **НЕ публиковать в Supabase app_versions, НЕ обновлять latest.json** — auto-updater не должен подхватить RC.
4. **Multi-core MCMC default ON** с automatic fallback на vectorized если 1 device. Rollback через env.
5. **UX-фиксы (PPTX dialog.save, упрощение отчёта)** — отдельный этап 2, после подтверждения rc2 Пашей.
6. **Phase 2/3 port isolation (9 продуктов)** — после rc2 stable. Playbook расширить 7 must-have fixes из rc2.
7. **Критический аудит плана ДО имплементации** — нашёл 11 проблем, которые иначе поехали бы в код (HTTPException pass-through, XLA_FLAGS position, chain_method hardcode, requirements.txt missing и т.д.).

## Pending

- ⏳ **Паша — RDP test чеклист на CLOUDEAI** (6 фокус-пунктов):
  1. `/health` полный (numpyro/jax/arviz/pytensor non-null)
  2. `JAX devices: N × cpu` в sidecar.log
  3. Asyncio spam = 0 (surgical filter)
  4. CPU во время training ≥ 50% (multi-core), время сократилось с 75 мин до ~10-15
  5. Force-ошибка validator → JSON (не plain text)
  6. Multi-user RDP повторить

- **Этап 2 (после OK от Паши):**
  - PPTX/DOCX/XLSX экспорт через `dialog.save()` вместо `%APPDATA%` (клиенты теряются в скрытой папке)
  - Упрощение отчёта по фидбеку Радомира («куча данных, надо долго вкуривать») — executive summary + схлопнуть диагностику
  
- **Phase 2 port isolation (после rc2 stable):**
  - Brand Hub RAG server (`:7420`) — базовый sidecar для 6 продуктов
  - Parser sidecar (`:7421`) — базовый для 2 продуктов
  - Остальные 9 Aurora-вариантов через расширенный sync_variants.py
  - Применить все 7 rc2 fixes к каждому (см. `project_port_isolation_phase2_scope.md`)

- **Долгосрочно:** OLS fallback для <20 точек, Cabinet redesign в 3 раздела, brand vs perf split (Trust Level 3), MMM-тренировка через WebWorker для async UX.

## Full Session Notes

### Phase 1: Context из памяти
Сессия началась с чтения памяти по v1.0.9-rc1:
- `project_per_user_port_isolation.md` — system-wide задача, rc1 опубликован 2026-04-21
- `project_econometrica_v109_progress.md` — чекпойнт имплементации, ждали Пашу
- `feedback_sidecar_rebuild_required.md` — критичная ловушка Tauri build

### Phase 2: Паша сдал rc1 тест
Присланы 5 артефактов в `D:/Downloads/Browser/`:
- `changelog_2026-04-21_econometrica.md` — Паша описал 3 серверных патча, которые он сделал ВРУЧНУЮ в `C:\Program Files\Aurora AI Econometrica\_up_\sidecar\`:
  - `server.py` + global exception handler (JSON 500)
  - `engines/validator.py` try/except вокруг записи + `default=str`
  - `build_sidecar.py` + `--collect-all=arviz_base/arviz_stats/arviz_plots`
- `checklist_results_2026-04-21.md` — 31/34 PASS, 1 FAIL (A.4 /health numpyro/jax null), 2 SKIP
- `sidecar_reference_2026-04-21.log` — лог Sidecar, видно что NumPyro успешно отработал (`Tier-1 NumPyro NUTS: SUCCESS` за 7 сек для 2x500x500), НО много `ProactorBasePipeTransport` traceback'ов
- `sidecar.json` — port=7437 (НЕ 7430!), user=AiUser12 — port isolation работает
- `Aurora_Diagnostics_2026-04-21_121424.txt` — /health non-JSON 500 несколько раз до его пересборки, watchdog unhealthy 3/3 в 07:39

Плюс Telegram-жалобы Паши:
- «25% CPU, 1 ядро, 42 мин = 56%» → MCMC висит, нагрузка на 1 ядре
- Просьба по UX: PPTX export через «Сохранить как» вместо AppData
- Радомир: отчёт слишком перегружен данными

### Phase 3: Анализ + план v1 + критический аудит
Первичный план (6 блоков, 1.5 ч) прошёл **критический аудит** — нашла 11 проблем:

**Серьёзные (поменяли подход):**
1. `@app.exception_handler(Exception)` ловит HTTPException → ломает 400/404. Добавила `isinstance(StarletteHTTPException): raise exc`
2. XLA_FLAGS в modeler.py — слишком поздно. Перенесла в top-level server.py
3. `chain_method='parallel'` хардкод. Сделала dynamic: `parallel if jax.devices()>1 else vectorized`
4. `numpyro.set_host_device_count` избыточен. Убрала
5. `✓` → `[OK]` точечный фикс. Заменила на PYTHONIOENCODING=utf-8 + stdout.reconfigure
6. `asyncio` logger CRITICAL слишком грубо. Surgical logging.Filter

**Скрытые проблемы:**
7. `requirements.txt` без numpyro/jax/arviz/pytensor (Паша ставил руками)
8. `/health` ловит только ImportError, не AttributeError
9. Нет startup diagnostic для JAX devices
10. `build_sidecar.py` без post-build freshness check
11. rc1 на GitHub — что делать при rc2 publish

Обновлённый план сохранён в `C:/Users/ackol/.claude/plans/shimmying-toasting-orbit.md`.

### Phase 4: Implementation (Блоки A-D)

**Блок A — FastAPI stability (`server.py` + `validator.py`):**
- XLA_FLAGS в начале server.py: `os.environ.setdefault('XLA_FLAGS', f'--xla_force_host_platform_device_count={min(cpu_count, 8)}')`
- Global exception handler с HTTPException pass-through
- Surgical asyncio filter на `_ProactorBasePipeTransport._call_connection_lost`
- JAX devices diagnostic в startup
- `/health` packages: +numpyro, +jax, +arviz, +pytensor, `except Exception`
- `validator.py`: try/except + `default=str` + `logger.warning`

**Блок B — build_sidecar.py:**
- PYTHONIOENCODING=utf-8 + stdout.reconfigure (cp1251 fix)
- `--collect-all=arviz_base/arviz_stats/arviz_plots`
- Post-build freshness check: exit 1 если .py новее .exe

**Блок C — modeler.py:**
- Dynamic `chain_method`: `'parallel' if len(jax.devices())>1 else 'vectorized'`
- Env override `AURORA_MCMC_CHAIN_METHOD=parallel|vectorized|sequential`
- Логирование method + devices

**Блок D — requirements.txt + CHANGELOG.md:**
- Pinned: `numpyro==0.20.1`, `jax[cpu]==0.7.2`, `jaxlib==0.7.2`, `arviz==0.23.4` + split packages, `pymc==5.28.4`, `pymc-marketing==0.19.2`, `pytensor>=2.24.0`
- CHANGELOG секция `v1.0.9-rc2 (2026-04-22)`

### Phase 5: Блок E — Release
Проверка deps на dev-машине: не хватало `arviz-base` и `arviz-plots` — доставил через `pip install`.

**Sidecar build:**
```bash
cd sidecar/econometrica && python build_sidecar.py
```
- 635 MB, Unicode `✓` прошёл, freshness check PASS
- 2 items synced в ROOT

**Tauri build:**
```bash
CARGO_TARGET_DIR="D:/cargo-targets/econometrica" npm run tauri build
```
- 2m 35s, NSIS 177.86 MB (+2MB к rc1 за счёт arviz split)
- SHA256: `6AE6524D8A235D087CA641000FA4957D3D6BA102598D4114C538EB62C34CF42D`

**Smoke test локально (без установки NSIS, прямо из bundle):**
```bash
./econometrica-sidecar.exe 7999 &
sleep 8
curl http://127.0.0.1:7999/health | jq '.packages'
```
Результат: все 10 пакетов non-null (numpyro=0.20.1, jax=0.7.2, arviz=0.23.4, pytensor=2.38.2)
```
2026-04-22 10:22:50 AURORA_MCMC_CORES=8 (XLA_FLAGS=--xla_force_host_platform_device_count=8)
2026-04-22 10:22:54 JAX devices: 8 × cpu (expected=8)
```
asyncio spam в сегодняшнем запуске = 0 (74 записей в логе — из старых rc1 сессий).

**Git + Release:**
- Commit `9553588`: rc2 stability fixes (6 файлов, +224/-16)
- Commit `9c6c5de`: RELEASE_NOTES_rc2.md
- Commit `a99b126`: .gitignore build logs
- Tag `v1.0.9-rc2` + `v1.0.8-pre-rdp-hardening` запушены
- GitHub pre-release в `Ackold26/aurora-releases` с NSIS + RDP_TEST_CHECKLIST.md
- rc1 description обновлён: «⚠️ Superseded by v1.0.9-rc2»

### Phase 6: Блок F — Память + aurora-fix
- `MEMORY.md` — 3 строки индекса обновлены (priority section + feedback section)
- `project_econometrica_v109_progress.md` — rc1→rc2 delta полностью описана
- `project_port_isolation_phase2_scope.md` (новый) — 7 must-have fixes для Phase 2/3
- `feedback_sidecar_rebuild_required.md` — freshness check теперь автоматический
- `feedback_live_test_loop_pattern.md` (новый) — рабочий паттерн rc → live-test → rc+1
- aurora-fix `SKILL.md`: обновлён V29 (arviz split packages note), добавлены V34-V39 новые правила, +7 строк в reminder-таблицу с S12-rc2 инцидентами

### Phase 7: Сообщение Паше
Написано в Telegram-ready виде от Маши — тёплое, с похвалой за детальный тест rc1, с описанием delta rc2, с чеклистом из 6 фокус-пунктов (только delta к rc1, не весь чеклист заново), с env flags для rollback.

Антон одобрил тональность.

### Phase 8: Financial wrap-up
- `.gitignore` обновлён для build logs (`sidecar_build_*.log`, `tauri_build_*.log`)
- Commit + push в master
- Session compressed → этот файл

## Key commands reference

```bash
# Sidecar rebuild (всегда перед Tauri build если Python менялся)
cd D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica/sidecar/econometrica
python build_sidecar.py  # теперь с авто-freshness check

# Tauri build
cd D:/Docs/Aurora_Ai/Dev/Aurora_Econometrica
CARGO_TARGET_DIR="D:/cargo-targets/econometrica" npm run tauri build

# Smoke test sidecar без установки
./sidecar/econometrica/econometrica-sidecar.exe 7999 &
curl http://127.0.0.1:7999/health | jq '.packages'

# Env rollback MCMC
setx AURORA_MCMC_CHAIN_METHOD vectorized  # откатить multi-core
setx AURORA_MCMC_CORES 1                   # disable JAX multi-device
setx AURORA_NUTS_BACKEND pymc              # fallback Tier-2 PyTensor
```

## SHA256 registry (для support)

- v1.0.9-rc1: `3fc31e02649ed04d643f683c525626cc4dc8b7fb90d96f6d0a6ffe43b4367ff4` (175.9 MB) — superseded
- **v1.0.9-rc2: `6AE6524D8A235D087CA641000FA4957D3D6BA102598D4114C538EB62C34CF42D` (177.86 MB) — current**

## Tags на Aurora_Econometrica

- `v1.0.8-pre-rdp-hardening` (551fbe8) — rollback point
- `v1.0.9-rc1` (7a71e4c) — port isolation, 31/34 PASS
- `v1.0.9-rc2` (9553588) — stability + multi-core MCMC
