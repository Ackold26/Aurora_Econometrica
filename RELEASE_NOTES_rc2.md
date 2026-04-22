## 🟡 Release Candidate 2 — follow-up к rc1 по результатам live-теста CLOUDEAI

Этот билд **не публикуется** в auto-updater. Только прямая установка для тестирования (тот же сценарий что rc1 — клиент РОССТ, машина CLOUDEAI).

> **Что было в rc1:** port isolation для multi-user RDP. Паша подтвердил работу 2026-04-21 (31/34 PASS).
> **Что меняет rc2:** 7 технических фиксов стабильности и производительности из live-теста, плюс многоядерное обучение модели.

### Stability

- **FastAPI global exception handler** → JSON 500 (было: plain text `Internal Server Error` под RemoteApp, GUI валился на парсинге). HTTPException pass-through сохраняет 400/404.
- **Validator error-safe** — запись `validation.json` обёрнута в try/except + `default=str`. Под roaming profile запись падала с PermissionError → result всё равно возвращается в GUI.
- **arviz 0.23.4 split packages** — добавлены `arviz_base`, `arviz_stats`, `arviz_plots` в PyInstaller bundle. Без них FileNotFoundError при импорте.
- **Build script Unicode-safe** — `PYTHONIOENCODING=utf-8` + `stdout.reconfigure`. Фикс UnicodeEncodeError на cp1251 (инцидент Паши при локальной пересборке).
- **Post-build freshness check** — exe обязан быть свежее всех `.py` после sync, иначе exit 1. Защита от stale sidecar в Tauri bundle.

### Performance — multi-core MCMC

В rc1 обучение 4×2000×2000 висело 75 минут при CPU=25% (1 ядро из 4). Причина: `chain_method='vectorized'` свёртывал все цепи в одну JAX-операцию на единственном host device.

- **`XLA_FLAGS=--xla_force_host_platform_device_count=N`** — устанавливается в startup `server.py` до любого `import jax`. N = `min(cpu_count, 8)`.
- **`chain_method` динамический** — `parallel` если `jax.devices()>1`, `vectorized` fallback на 1 device (безопасно).
- **Ожидаемое ускорение**: 3-8× на 4-8-ядерных серверах.

### Diagnostics

- **`/health` показывает версии** `numpyro`, `jax`, `arviz`, `pytensor` (в rc1 эти поля отсутствовали — единственный FAIL A.4 в чеклисте Паши).
- **Startup log**: `JAX devices: N × cpu (expected=M)` + `AURORA_MCMC_CORES=N`.
- **Surgical asyncio filter** — убирает Windows-специфичный спам `_ProactorBasePipeTransport._call_connection_lost` из `sidecar.log`. Реальные asyncio errors сохранены.

### Env flags (новые)

- `AURORA_MCMC_CORES=N` — переопределить число виртуальных JAX host devices (дефолт `min(cpu, 8)`).
- `AURORA_MCMC_CHAIN_METHOD=parallel|vectorized|sequential` — форсировать chain distribution (обход автодетекта).
- (существующий) `AURORA_NUTS_BACKEND=auto|numpyro|pymc` — выбор backend.

### SHA256

```
6AE6524D8A235D087CA641000FA4957D3D6BA102598D4114C538EB62C34CF42D
```

### Установка

1. Скачать `Aurora AI Econometrica_1.0.9_x64-setup.exe` (177.86 MB)
2. Проверить SHA256 (PowerShell): `Get-FileHash "Aurora AI Econometrica_1.0.9_x64-setup.exe" -Algorithm SHA256`
3. Запустить installer (перезапишет rc1 если стоит)
4. Прогнать `RDP_TEST_CHECKLIST.md` из rc1 — теперь **A.4 должен быть PASS** (numpyro/jax не null в `/health`)

### Для IT Паши — delta к rc1

- Три server-side патча, которые ты делал руками на CLOUDEAI (global handler, validator safe-write, arviz split packages), **включены в rc2** — можно смело обновляться, ручные правки в `C:\Program Files\Aurora AI Econometrica\_up_\sidecar\` больше не нужны.
- Плюс performance fix для MCMC — прогон 4 chains × 2000 draws × 2000 tune должен быть в **4-8 раз быстрее**.
- Посмотри на CPU utilization во время training — ожидаемо ≥ 50% (в rc1 было 25%).

### Проверить в логах после запуска

```powershell
type "$env:LOCALAPPDATA\aurora-econometrica-gui\logs\sidecar.log" | Select-String "JAX devices"
# Ожидаемо: JAX devices: 8 × cpu (expected=8)   # число зависит от сервера

type "$env:LOCALAPPDATA\aurora-econometrica-gui\logs\sidecar.log" | Select-String "ProactorBasePipe"
# Ожидаемо: пусто (surgical filter убирает спам)

type "$env:LOCALAPPDATA\com.aurora.econometrica\sidecar.json"
# Ожидаемо: port в диапазоне 7430-7529, version=1.0.9, product=com.aurora.econometrica
```

---

**Rollback:** если rc2 хуже rc1 — `AURORA_MCMC_CHAIN_METHOD=vectorized` (env var) откатывает multi-core без переустановки. Либо установить `v1.0.9-rc1` поверх.
