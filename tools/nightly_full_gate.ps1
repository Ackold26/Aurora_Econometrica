<#
.SYNOPSIS
  У5 (2026-07-04) — ночной полный прогон тестов Econometrica с логом и алертом.

.DESCRIPTION
  Против F-AUD-6: тест-инфра тихо протухла (путь Desktop переехал → 18 тестов
  красные, полный gate был всегда красный и маскировал настоящие регрессы).
  Скрипт-обёртка прогоняет ВЕСЬ tools/ (реальные данные подтягиваются через
  conftest resolution chain: env AURORA_TESTDATA_DIR → D:/Docs/.../TestData →
  Desktop), пишет лог с датой и при exit≠0 добавляет строку в ALERTS.log.

  Real-data тесты без доступных фикстур честно SKIP (не FAIL) — алерт только на
  настоящие падения.

.PARAMETER RepoDir
  Корень репозитория Aurora_Econometrica.

.PARAMETER TestDataDir
  Опционально: явный путь к папке с реальными xlsx (перекрывает conftest default).

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
  [string]$TestDataDir = ''
)

$ErrorActionPreference = 'Continue'
if ($TestDataDir) { $env:AURORA_TESTDATA_DIR = $TestDataDir }

$stamp = Get-Date -Format 'yyyy-MM-dd_HHmm'
$logDir = Join-Path $RepoDir 'tmp\nightly_gate'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
$log = Join-Path $logDir "gate_$stamp.log"

Set-Location $RepoDir
Write-Host "[nightly gate] $stamp — прогон tools/ (лог: $log)"

# pytest.ini уже задаёт -n 4 --dist worksteal; addopts подхватятся автоматически.
python -m pytest tools/ -q 2>&1 | Tee-Object -FilePath $log
$code = $LASTEXITCODE

$summaryMatch = Select-String -Path $log -Pattern '\d+ (passed|failed|error)' | Select-Object -Last 1
$summary = if ($summaryMatch) { $summaryMatch.Line.Trim() } else { 'нет сводки в логе' }

if ($code -ne 0) {
  $alert = "[ALERT] $stamp Nightly gate FAILED (exit=$code): $summary | лог: $log"
  Add-Content -Path (Join-Path $logDir 'ALERTS.log') -Value $alert
  Write-Host $alert -ForegroundColor Red
} else {
  Write-Host "[OK] $stamp Nightly gate passed: $summary" -ForegroundColor Green
}

exit $code

