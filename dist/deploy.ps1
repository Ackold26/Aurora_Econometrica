####################################################################
#  Aurora AI Agency v0.2.0 — Скрипт развёртывания
#  Запускать от имени администратора!
#
#  Что делает (одна команда — всё готово):
#    1. Тихо устанавливает приложение для всех пользователей ПК
#    2. Копирует лицензию в общую папку (ProgramData)
#    3. Копирует vault-файлы в общую папку (если указаны)
#    4. Устанавливает Claude Code CLI (если не установлен)
#    5. Кладёт скрипт first-login.cmd на общий рабочий стол
#
#  Примеры:
#    .\deploy.ps1 -Variant Creative -LicensePath .\license.json
#    .\deploy.ps1 -Variant Legal -LicensePath .\license.json -VaultDir .\vaults
#    .\deploy.ps1 -Variant Media -LicensePath C:\licenses\rosst-media.json
#
#  Удаление:
#    .\deploy.ps1 -Variant Creative -LicensePath dummy -Uninstall
####################################################################

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("Creative", "Legal", "Media")]
    [string]$Variant,

    [Parameter(Mandatory=$true)]
    [string]$LicensePath,

    [string]$VaultDir,

    [string]$InstallDir,

    [switch]$SkipCliInstall,

    [switch]$SkipDesktopShortcut,

    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- Конфигурация ---
$appNames = @{
    Creative = "AURORA AI AGENCY - ROSST Creative"
    Legal    = "AURORA AI AGENCY - ROSST Legal"
    Media    = "AURORA AI AGENCY - ROSST Media"
}
$appName = $appNames[$Variant]
$setupExe = Join-Path $scriptDir "ROSST_$Variant\${appName}_0.2.0_x64-setup.exe"
$programData = "C:\ProgramData\AIAgency"
$publicDesktop = [System.Environment]::GetFolderPath("CommonDesktopDirectory")

# --- Вспомогательные функции ---
function Assert-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Host "ОШИБКА: Запустите скрипт от имени администратора!" -ForegroundColor Red
        exit 1
    }
}

function Write-Step($num, $text) {
    Write-Host "`n[$num] $text" -ForegroundColor Cyan
}

# --- Удаление ---
if ($Uninstall) {
    Assert-Admin
    Write-Step 1 "Удаление $appName..."
    $uninstaller = "C:\Program Files\$appName\Uninstall $appName.exe"
    if (Test-Path $uninstaller) {
        Start-Process -FilePath $uninstaller -ArgumentList "/S" -Wait
        Write-Host "  Приложение удалено." -ForegroundColor Green
    } else {
        Write-Host "  Деинсталлятор не найден: $uninstaller" -ForegroundColor Yellow
    }
    # Убрать first-login с рабочего стола
    $loginShortcut = Join-Path $publicDesktop "Aurora AI — Первый вход.cmd"
    if (Test-Path $loginShortcut) { Remove-Item $loginShortcut -Force }

    Write-Host "`nДанные в ProgramData и профилях пользователей НЕ удалены." -ForegroundColor Gray
    Write-Host "Для полной очистки удалите вручную:" -ForegroundColor Gray
    Write-Host "  - $programData" -ForegroundColor Gray
    Write-Host "  - %LOCALAPPDATA%\AIAgency\  (в профиле каждого пользователя)" -ForegroundColor Gray
    Write-Host "  - %APPDATA%\AIAgency\  (в профиле каждого пользователя)" -ForegroundColor Gray
    exit 0
}

# --- Основной процесс ---
Assert-Admin

Write-Host ""
Write-Host "  ======================================" -ForegroundColor White
Write-Host "   Aurora AI Agency — Развёртывание" -ForegroundColor White
Write-Host "   Вариант: $Variant" -ForegroundColor White
Write-Host "  ======================================" -ForegroundColor White

# 1. Установка приложения
Write-Step 1 "Установка приложения..."
if (-not (Test-Path $setupExe)) {
    Write-Host "  ОШИБКА: Установщик не найден: $setupExe" -ForegroundColor Red
    exit 1
}

$installArgs = "/S"
if ($InstallDir) { $installArgs += " /D=$InstallDir" }

Write-Host "  Запуск: $setupExe $installArgs"
Start-Process -FilePath $setupExe -ArgumentList $installArgs -Wait
Write-Host "  Установлено для всех пользователей." -ForegroundColor Green

# 2. Лицензия
Write-Step 2 "Размещение лицензии (общая для всех пользователей)..."
if (-not (Test-Path $LicensePath)) {
    Write-Host "  ОШИБКА: Файл лицензии не найден: $LicensePath" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Path $programData -Force | Out-Null
Copy-Item $LicensePath "$programData\license.json" -Force
Write-Host "  Лицензия: $programData\license.json" -ForegroundColor Green

# 3. Vault-файлы
if ($VaultDir) {
    Write-Step 3 "Копирование vault-файлов..."
    if (-not (Test-Path $VaultDir)) {
        Write-Host "  ОШИБКА: Директория vault не найдена: $VaultDir" -ForegroundColor Red
        exit 1
    }
    $vaultDest = "$programData\vaults"
    New-Item -ItemType Directory -Path $vaultDest -Force | Out-Null
    $count = 0
    Get-ChildItem "$VaultDir\*.vault" | ForEach-Object {
        Copy-Item $_.FullName "$vaultDest\$($_.Name)" -Force
        $count++
    }
    Write-Host "  Скопировано vault-файлов: $count" -ForegroundColor Green
} else {
    Write-Step 3 "Vault-файлы: параметр -VaultDir не указан, пропуск."
}

# 4. Claude Code CLI
if (-not $SkipCliInstall) {
    Write-Step 4 "Проверка Claude Code CLI..."
    $claudePath = Get-Command claude -ErrorAction SilentlyContinue
    if ($claudePath) {
        $ver = & claude --version 2>&1
        Write-Host "  Уже установлен: $ver" -ForegroundColor Green
    } else {
        Write-Host "  Не найден. Установка..."
        $npmPath = Get-Command npm -ErrorAction SilentlyContinue
        if ($npmPath) {
            npm install -g @anthropic-ai/claude-code 2>&1 | Out-Null
            Write-Host "  Claude Code CLI установлен." -ForegroundColor Green
        } else {
            Write-Host "  ПРЕДУПРЕЖДЕНИЕ: npm не найден." -ForegroundColor Yellow
            Write-Host "  Установите Claude Code CLI вручную:" -ForegroundColor Yellow
            Write-Host "    npm install -g @anthropic-ai/claude-code" -ForegroundColor Yellow
        }
    }
} else {
    Write-Step 4 "Установка CLI пропущена (-SkipCliInstall)."
}

# 5. Скрипт первого входа на общий рабочий стол
if (-not $SkipDesktopShortcut) {
    Write-Step 5 "Размещение скрипта первого входа на рабочем столе..."
    $firstLoginSrc = Join-Path $scriptDir "first-login.cmd"
    $firstLoginDst = Join-Path $publicDesktop "Aurora AI — Первый вход.cmd"
    if (Test-Path $firstLoginSrc) {
        Copy-Item $firstLoginSrc $firstLoginDst -Force
        Write-Host "  Скрипт: $firstLoginDst" -ForegroundColor Green
        Write-Host "  Пользователи увидят его на рабочем столе при первом входе." -ForegroundColor Gray
    } else {
        Write-Host "  first-login.cmd не найден в $scriptDir, пропуск." -ForegroundColor Yellow
    }
} else {
    Write-Step 5 "Ярлык на рабочем столе пропущен (-SkipDesktopShortcut)."
}

# --- Итог ---
Write-Host ""
Write-Host "  ======================================" -ForegroundColor White
Write-Host "   Развёртывание завершено!" -ForegroundColor Green
Write-Host "  ======================================" -ForegroundColor White
Write-Host ""
Write-Host "  Приложение:  C:\Program Files\$appName\" -ForegroundColor Gray
Write-Host "  Лицензия:    $programData\license.json" -ForegroundColor Gray
if ($VaultDir) {
Write-Host "  Vault-файлы: $programData\vaults\" -ForegroundColor Gray
}
Write-Host ""
Write-Host "  СЛЕДУЮЩИЙ ШАГ (для каждого пользователя):" -ForegroundColor Yellow
Write-Host "  Запустить 'Aurora AI - Первый вход' на рабочем столе" -ForegroundColor Yellow
Write-Host "  или выполнить: claude auth login" -ForegroundColor Yellow
Write-Host ""
