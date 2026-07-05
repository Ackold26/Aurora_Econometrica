<#
.SYNOPSIS
  У5 (2026-07-04) — ночной полный прогон гейтов Econometrica с логом и алертом.

.DESCRIPTION
  Три гейта в одном проходе (gate FAILED, если упал ЛЮБОЙ):
    1. python tools/  — полный бэкенд + реальные данные (против F-AUD-6: тест-инфра
       тихо протухла, путь Desktop переехал → красный gate маскировал регрессы).
       Реальные данные подтягиваются через conftest resolution chain
       (env AURORA_TESTDATA_DIR → D:/Docs/.../TestData → Desktop). Без фикстур —
       честный SKIP, не FAIL.
    2. vitest         — фронт-контракты (аудит 2026-07-04 / F-2: buildTrainConfig
       «байт-в-байт» golden упал от use_seasonality, а svelte-check контракты
       НЕ ловит — vitest обязателен при любой фронт-правке).
    3. svelte-check   — типы/шаблоны SvelteKit (0 errors).
  Опционально (-IncludeCargo): cargo test (медленно — компиляция Rust).

  Пишет общий лог с датой; при любом падении — строка в ALERTS.log + красный вывод.

.PARAMETER RepoDir
  Корень репозитория Aurora_Econometrica.

.PARAMETER TestDataDir
  Опционально: явный путь к папке с реальными xlsx (перекрывает conftest default).

.PARAMETER IncludeCargo
  Прогнать ещё и `cargo test` (Rust). По умолчанию off (долгая компиляция).

.NOTES
  Регистрация (паттерн «Aurora Memory Reindex»):
    schtasks /Create /TN "Aurora Econometrica Nightly Gate" /TR ^
      "powershell -NonInteractive -File D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica\tools\nightly_full_gate.ps1" ^
      /SC DAILY /ST 03:00
  ИЛИ регламент: запускать вручную перед каждым релизом.
  Telegram-алерт по инфра-каналу Маши Небесной — TODO (сейчас fallback = ALERTS.log).
#>
param(
  [string]$RepoDir = 'D:\Docs\Aurora_Ai\Dev\Aurora_Econometrica',
  [string]$TestDataDir = '',
  [switch]$IncludeCargo
)

$ErrorActionPreference = 'Continue'
if ($TestDataDir) { $env:AURORA_TESTDATA_DIR = $TestDataDir }

$stamp = Get-Date -Format 'yyyy-MM-dd_HHmm'
$logDir = Join-Path $RepoDir 'tmp\nightly_gate'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
$log = Join-Path $logDir "gate_$stamp.log"

Set-Location $RepoDir
Write-Host "[nightly gate] $stamp — python + vitest + svelte-check (лог: $log)"

# Каждому гейту — своя строка сводки в общий лог + агрегированный overall-код.
$overall = 0
$summaries = @()

# Урок A-8 (аудит 2026-07-05): exit-код сам по себе не вердикт — bash-пайп в
# tail замаскировал 9 failed нулём. Здесь $LASTEXITCODE честный (Tee-Object —
# cmdlet, код остаётся от exe), но добавлена трип-проволока на обратный класс:
# exit=0 БЕЗ строки-сводки прогона = аномалия (упавший сбор / проглоченный
# запуск) → gate FAILED, не молчаливый OK.

# ── 1. Python (pytest.ini задаёт -n 4 --dist worksteal автоматически) ──────
"=== [1/3] python tools/ ($stamp) ===" | Tee-Object -FilePath $log
python -m pytest tools/ -q 2>&1 | Tee-Object -FilePath $log -Append
$pyCode = $LASTEXITCODE
if ($null -eq $pyCode -or $pyCode -ne 0) { $overall = 1 }
$pySum = (Select-String -Path $log -Pattern '\d+ (passed|failed|error)' | Select-Object -Last 1)
if ($null -eq $pySum -and $pyCode -eq 0) {
  $overall = 1
  $summaries += "python: exit=$pyCode НО сводка pytest не найдена (аномалия — сбор упал?)"
} else {
  $summaries += "python: exit=$pyCode $(if ($pySum) { $pySum.Line.Trim() } else { '(no summary)' })"
}

# ── 2. Vitest (фронт-контракты; F-2 — svelte-check их не ловит) ────────────
"=== [2/3] vitest ($stamp) ===" | Tee-Object -FilePath $log -Append
$env:CI = '1'
npx vitest run 2>&1 | Tee-Object -FilePath $log -Append
$viCode = $LASTEXITCODE
if ($null -eq $viCode -or $viCode -ne 0) { $overall = 1 }
$viSum = (Select-String -Path $log -Pattern 'Tests\s+\d+ (passed|failed)' | Select-Object -Last 1)
if ($null -eq $viSum -and $viCode -eq 0) {
  $overall = 1
  $summaries += "vitest: exit=$viCode НО сводка Tests не найдена (аномалия)"
} else {
  $summaries += "vitest: exit=$viCode $(if ($viSum) { $viSum.Line.Trim() } else { '(no summary)' })"
}

# ── 3. svelte-check (0 errors) ─────────────────────────────────────────────
"=== [3/3] svelte-check ($stamp) ===" | Tee-Object -FilePath $log -Append
npm run check 2>&1 | Tee-Object -FilePath $log -Append
$svCode = $LASTEXITCODE
if ($null -eq $svCode -or $svCode -ne 0) { $overall = 1 }
$svSum = (Select-String -Path $log -Pattern '\d+ errors?' | Select-Object -Last 1)
if ($null -eq $svSum -and $svCode -eq 0) {
  $overall = 1
  $summaries += "svelte-check: exit=$svCode НО сводка errors не найдена (аномалия)"
} else {
  $summaries += "svelte-check: exit=$svCode $(if ($svSum) { $svSum.Line.Trim() } else { '(no summary)' })"
}

# ── 4. Cargo (опционально) ─────────────────────────────────────────────────
if ($IncludeCargo) {
  "=== [4] cargo test ($stamp) ===" | Tee-Object -FilePath $log -Append
  $env:CARGO_TARGET_DIR = 'D:/cargo-targets/ai-agency'
  Push-Location (Join-Path $RepoDir 'src-tauri')
  cargo test 2>&1 | Tee-Object -FilePath $log -Append
  $cgCode = $LASTEXITCODE
  Pop-Location
  if ($cgCode -ne 0) { $overall = 1 }
  $summaries += "cargo: exit=$cgCode"
}

$summaryLine = $summaries -join ' | '
if ($overall -ne 0) {
  $alert = "[ALERT] $stamp Nightly gate FAILED: $summaryLine | лог: $log"
  Add-Content -Path (Join-Path $logDir 'ALERTS.log') -Value $alert
  Write-Host $alert -ForegroundColor Red
} else {
  Write-Host "[OK] $stamp Nightly gate passed: $summaryLine" -ForegroundColor Green
}

exit $overall

