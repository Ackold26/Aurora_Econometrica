# Aurora AI Econometrica v1.0.9 — чеклист single-user теста

> **Версия билда:** v1.0.9-rdp-hardening
> **Цель:** убедиться что port discovery + handshake + license cleanup + MMM fallback работают на чистой установке. Multi-user тест — отдельно после этого.

---

## Предусловия

- [ ] Build завершился без ошибок: `CARGO_TARGET_DIR="D:/cargo-targets/econometrica" npm run tauri build`
- [ ] Installer создан: `D:/cargo-targets/econometrica/release/bundle/nsis/Aurora.AI.Econometrica_1.0.9_x64-setup.exe`
- [ ] Перед install: **деинсталлировать v1.0.8** (Control Panel → Programs → Aurora AI Econometrica → Uninstall). Это важно — проверяем чистую инсталляцию.

## Terminal, открытый для команд

Открой **PowerShell от Администратора** (нужен для `netsh` и `taskkill`).

---

## Этап A — Install + first launch

### A.1. Установить v1.0.9

- [ ] Запусти installer с правами admin. Дойди до финиша. **Не запускай приложение** из NSIS финального чекбокса — сначала проверим правила firewall.

### A.2. Проверить firewall rule

```powershell
netsh advfirewall firewall show rule name="Aurora AI Econometrica (loopback)"
netsh advfirewall firewall show rule name="Aurora AI Econometrica Sidecar (loopback)"
```

**Ожидается:** обе команды показывают `Enabled: Yes`, `Direction: In`, `Action: Allow`, `LocalIP: 127.0.0.1`.

- [ ] GUI rule present
- [ ] Sidecar rule present

Если правил нет — NSIS hook не отработал. Смотри `D:/cargo-targets/econometrica/release/bundle/nsis/` на лог установки.

### A.3. Запустить приложение + проверить sidecar.json

Запусти Aurora AI Econometrica из Start Menu. **Дождись что открылся main window** (~20-40 секунд на первый запуск).

```powershell
Get-Content "$env:LOCALAPPDATA\com.aurora.econometrica\sidecar.json" | ConvertFrom-Json
```

**Ожидается:** JSON-объект с полями `port`, `pid`, `session_id`, `product="com.aurora.econometrica"`, `version="1.0.9"`, `user=<твой_username>`, `started_at=<ISO timestamp>`.

- [ ] Файл создан в `%LOCALAPPDATA%` (**НЕ** в `%APPDATA%/Roaming`)
- [ ] `product` = `com.aurora.econometrica`
- [ ] `version` = `1.0.9`
- [ ] `port` — в диапазоне `7430`..`7529` (deterministic user-scoped) **или** ≥`49152` (ephemeral fallback)
- [ ] `pid` — реальный PID процесса `econometrica-sidecar.exe`

### A.4. Verify порт живой + handshake

```powershell
$port = (Get-Content "$env:LOCALAPPDATA\com.aurora.econometrica\sidecar.json" | ConvertFrom-Json).port
curl "http://127.0.0.1:$port/health" | ConvertFrom-Json
```

**Ожидается:** JSON с `status="ok"`, `product="com.aurora.econometrica"`, `version="1.0.9"`, `session_id` (совпадает с sidecar.json), `pid`, `started_at`, `packages` (pymc/numpy/scipy заполнены).

- [ ] `status` = `ok`
- [ ] `session_id` в /health **совпадает** с `session_id` в sidecar.json
- [ ] Поля `packages.numpyro` и `packages.jax` не `null` (CPU-only JAX bundle работает)

### A.5. Netstat — процесс владелец

```powershell
netstat -ano -p tcp | findstr ":$port"
```

**Ожидается:** строка `TCP 127.0.0.1:<port> ... LISTENING <pid>` с `<pid>` из sidecar.json.

```powershell
Get-Process -Id $pid | Select-Object Id, ProcessName, StartTime
```

**Ожидается:** ProcessName = `econometrica-sidecar`.

- [ ] Processname правильный
- [ ] Порт слушает именно наш процесс

---

## Этап B — Handshake + recovery

### B.1. Force-kill sidecar, проверить auto-respawn

```powershell
$pid = (Get-Content "$env:LOCALAPPDATA\com.aurora.econometrica\sidecar.json" | ConvertFrom-Json).pid
Stop-Process -Id $pid -Force
Start-Sleep -Seconds 60   # watchdog проверяет каждые 15s, threshold 3 = ~45s на re-spawn
Get-Content "$env:LOCALAPPDATA\com.aurora.econometrica\sidecar.json" | ConvertFrom-Json
```

**Ожидается:** PID в файле сменился, `session_id` новый. Приложение продолжает работать. В UI сидебара никаких ошибок.

- [ ] New PID
- [ ] New session_id
- [ ] Приложение отвечает в UI

### B.2. Подменить sidecar.json на «чужую» версию → handshake respawn

```powershell
$sf = "$env:LOCALAPPDATA\com.aurora.econometrica\sidecar.json"
$orig = Get-Content $sf -Raw
$orig -replace '"session_id":\s*"[^"]+"', '"session_id": "fake000000000000000000000000deadbeef"' | Set-Content $sf
```

Теперь **закрой и снова открой приложение** (не просто reload — полный перезапуск).

```powershell
Get-Content $sf | ConvertFrom-Json
```

**Ожидается:** `session_id` **не** `fake...` — Rust отверг chужой session при cold start, убил старый процесс, запустил свой. Получился новый session.

- [ ] session_id ≠ fake000…
- [ ] В логах GUI (`%LOCALAPPDATA%\com.aurora.econometrica\logs\`) запись: `"Sidecar state file stale..."` или `"Cleaning up and respawning"`

### B.3. Kill-switch env var

Закрой приложение. Запусти из PowerShell с переменной:

```powershell
$env:AURORA_SIDECAR_LEGACY_PORT = "1"
Start-Process "C:\Program Files\Aurora AI Econometrica\aurora-econometrica-gui.exe"
Start-Sleep -Seconds 30
(Get-Content "$env:LOCALAPPDATA\com.aurora.econometrica\sidecar.json" | ConvertFrom-Json).port
```

**Ожидается:** port = `7430` (legacy hardcoded), **не** deterministic user-scoped.

- [ ] Port = 7430

Не забудь потом `Remove-Item Env:AURORA_SIDECAR_LEGACY_PORT`.

---

## Этап C — License cleanup

### C.1. Legacy contamination test

Закрой приложение. Создай fake legacy file:

```powershell
$legacy = "$env:APPDATA\AIAgency\license.json"
New-Item -Path (Split-Path $legacy) -ItemType Directory -Force | Out-Null
'{"license_id":"fake","issued_to":"Юрист","expires_at":"2099-01-01","machine_fingerprint_hash":"fake","cabinets":[],"salt":"","signature":""}' | Set-Content $legacy
```

Запусти приложение. Дождись полной загрузки.

```powershell
Test-Path $legacy             # должен быть False (renamed)
Test-Path "$env:APPDATA\AIAgency\license.legacy.bak"   # должен быть True
```

**Ожидается:** `license.json` переименован в `license.legacy.bak`. В Econometrica В настройках статус лицензии — не "Юрист", а либо online auth result, либо `LI001 (license not found)`.

- [ ] Legacy file → `.bak`
- [ ] В Econometrica НЕТ "Issued To: Юрист"

Если валидный per-app license отсутствует — диагностика должна говорить `LI001`, а не подтягивать мусор.

---

## Этап D — Full MMM pipeline (single-user)

### D.1. Open Pipeline

В UI: Cabinet / Pipeline → Import → drag-drop твой тестовый XLSX (или на `D:\Венарус_данные...` если есть).

- [ ] Import step success, preview показывает колонки
- [ ] Validate step — traffic-light panel работает
- [ ] Adstock step — `/compute/adstock_select` возвращает 200 (не 404!) — это был главный симптом у Паши

### D.2. Train

Выбери 2-3 канала, KPI, запусти train.

- [ ] В логах sidecar (`%LOCALAPPDATA%\com.aurora.econometrica\logs\sidecar.log`) строка `MCMC backend: NumPyro NUTS (JAX) — numpyro=X.Y.Z, jax=X.Y.Z`
- [ ] Модель обучается без ошибок `functools.partial`
- [ ] **Если** всё же всплывает — в логе `Tier-1 NumPyro NUTS: functools.partial bug ... falling back to Tier-2 PyTensor NUTS`. Это ожидаемое поведение — дальше должен быть `Tier-2 PyTensor NUTS: SUCCESS`.

### D.3. Force Strategy A через env

Закрой приложение. Запусти с:

```powershell
$env:AURORA_NUTS_BACKEND = "pymc"    # форсим PyTensor, медленный но стабильный
Start-Process "C:\Program Files\Aurora AI Econometrica\aurora-econometrica-gui.exe"
```

Повтори train. Должен работать, но медленнее (~10 мин вместо 3). В логах: `MCMC backend: ... PyTensor` (NumPyro пропущен).

- [ ] Модель обучается через PyTensor
- [ ] Нет regression — pipeline идёт до Report

Убери env переменную.

### D.4. Полный pipeline до Report

- [ ] Decompose → Optimize → Report — всё проходит без `Session mismatch` ошибок и без 409
- [ ] Логи не содержат retry-loops (`409` redirects)

---

## Этап E — Graceful shutdown

### E.1. Close GUI — state file cleanup

Закрой приложение (X в window header).

```powershell
Test-Path "$env:LOCALAPPDATA\com.aurora.econometrica\sidecar.json"
```

**Ожидается:** `False` — state file удалён в `stop_sidecar()`.

```powershell
Get-Process -Name "econometrica-sidecar" -ErrorAction SilentlyContinue
```

**Ожидается:** пусто — процесс завершился gracefully.

- [ ] state file deleted
- [ ] sidecar process exited

### E.2. Повторный запуск — clean cold start

Запусти приложение снова. Проверь что новый sidecar.json создан с новым session_id, всё работает.

- [ ] Clean cold start works

---

## Этап F — Full pipeline baseline (ещё раз)

Пройди pipeline заново от импорта до отчёта — убедиться что на чистом старте ничего не сломали.

- [ ] All steps green

---

## Что делать, если что-то сломалось

| Симптом | Fallback |
|---------|----------|
| sidecar не запускается | `$env:AURORA_SIDECAR_LEGACY_PORT = "1"` → hardcoded 7430 как до v1.0.9 |
| 409 loop в логах | `$env:AURORA_SKIP_HANDSHAKE = "1"` → отключает product/session check |
| MMM падает на `functools.partial` в обоих tiers | Смотри `error_code: MMM_SAMPLER_EXHAUSTED` в ответе — фото сюда |
| Firewall prompt всплывает | NSIS hook не отработал — проверь `netsh advfirewall firewall show rule` |
| License contamination не починилась | `%APPDATA%\AIAgency\license.json` принадлежит другому user? Посмотри ACL `Get-Acl` |

## После успешного теста

- [ ] Сохранить `%LOCALAPPDATA%\com.aurora.econometrica\logs\sidecar.log` последней сессии — как reference
- [ ] Git commit всех изменений Phase 1
- [ ] Либо Паше RC → либо сразу Phase 2 (rag/parser sidecars)
