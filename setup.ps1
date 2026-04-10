#Requires -Version 5.1
<#
.SYNOPSIS
    ROSST AI Agency — автоустановка окружения и сборка приложений

.DESCRIPTION
    Проверяет и устанавливает все зависимости, затем собирает 4 приложения.
    Запуск: .\setup.ps1
    Только зависимости (без сборки): .\setup.ps1 -SkipBuild
    Только сборка (зависимости уже есть): .\setup.ps1 -BuildOnly

.PARAMETER SkipBuild
    Установить зависимости, но не собирать приложения

.PARAMETER BuildOnly
    Пропустить установку зависимостей, только собрать приложения

.PARAMETER App
    Собра��ь только одно при��ожение: legal, creative, media, agency

.PARAMETER RootDir
    Корневая папка для проектов (по умолчанию: Desktop)
#>
param(
    [switch]$SkipBuild,
    [switch]$BuildOnly,
    [ValidateSet("legal","creative","media","agency","")]
    [string]$App = "",
    [string]$RootDir = "$env:USERPROFILE\Desktop"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ─── Цвета и утилиты ────────────────────────────────────────────────────────

function Write-Step  { param($msg) Write-Host "`n▶ $msg" -ForegroundColor Cyan }
function Write-OK    { param($msg) Write-Host "  ✓ $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "  ⚠ $msg" -ForegroundColor Yellow }
function Write-Fail  { param($msg) Write-Host "  ✗ $msg" -ForegroundColor Red }
function Write-Info  { param($msg) Write-Host "    $msg" -ForegroundColor Gray }

function Pause-ForUser {
    param([string]$Prompt = "Нажмите любую клавишу для продолжения...")
    Write-Host "`n$Prompt" -ForegroundColor DarkYellow
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}

# ─── Авто-повышение прав ────────────────────────────────────────────────────

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]"Administrator")

if (-not $isAdmin) {
    Write-Warn "Перезапуск с правами администратора..."
    $args_str = $PSBoundParameters.GetEnumerator() | ForEach-Object { "-$($_.Key)" + (if ($_.Value -is [switch]) { "" } else { " '$($_.Value)'" }) }
    Start-Process powershell.exe "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" $($args_str -join ' ')" -Verb RunAs
    exit
}

# ─── Заголовок ──────────────────────────────────────────────────────────────

Clear-Host
Write-Host "=" * 60 -ForegroundColor DarkCyan
Write-Host "  ROSST AI Agency — Setup & Build" -ForegroundColor White
Write-Host "  $(Get-Date -Format 'dd.MM.yyyy HH:mm')" -ForegroundColor Gray
Write-Host "=" * 60 -ForegroundColor DarkCyan

# ─── Пути к приложениям ─────────────────────────────────────────────────────

$Apps = @(
    @{ Key = "agency";   Name = "AI Agency (все кабинеты)"; Path = "$RootDir\AI_APP_AGENCY"    }
    @{ Key = "legal";    Name = "ROSST AI Legal";           Path = "$RootDir\ROSST_AI_Legal"   }
    @{ Key = "creative"; Name = "ROSST AI Creative";        Path = "$RootDir\ROSST_AI_Creative" }
    @{ Key = "media";    Name = "ROSST AI Insights Hub";     Path = "$RootDir\ROSST_AI_Media"   }
)

# Фильтр по -App если указан
if ($App) {
    $Apps = $Apps | Where-Object { $_.Key -eq $App }
}

# ─── Функция обновления PATH ─────────────────────────────────────────────────

function Refresh-Path {
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path","User")
}

# ─── Функция проверки команды ────────────────────────────────────────────────

function Test-Command { param($cmd) $null -ne (Get-Command $cmd -ErrorAction SilentlyContinue) }

# ─── БЛОК 1: Зависимости ────────────────────────────────────────────────────

if (-not $BuildOnly) {

    Write-Host "`n═══ УСТАНОВКА ЗАВИСИМОСТЕЙ ═══" -ForegroundColor DarkCyan

    # 1. winget
    Write-Step "Проверка winget..."
    if (Test-Command "winget") {
        Write-OK "winget доступен ($(winget --version))"
    } else {
        Write-Fail "winget не найден. Обновите Windows 10 до версии 1809+ или установите App Installer из Microsoft Store."
        Write-Info "https://apps.microsoft.com/store/detail/app-installer/9NBLGGH4NNS1"
        Pause-ForUser "После установки winget нажмите любую клавишу..."
        Refresh-Path
    }

    # 2. Node.js 20+
    Write-Step "Проверка Node.js..."
    Refresh-Path
    if (Test-Command "node") {
        $nodeVer = (node --version) -replace "v",""
        $nodeMajor = [int]($nodeVer.Split(".")[0])
        if ($nodeMajor -ge 20) {
            Write-OK "Node.js v$nodeVer (OK)"
        } else {
            Write-Warn "Node.js v$nodeVer — нужна версия 20+. Обновляю..."
            winget install --id OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements
            Refresh-Path
        }
    } else {
        Write-Info "Node.js не найден. Устанавливаю..."
        winget install --id OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements
        Refresh-Path
        Write-OK "Node.js установлен: $(node --version)"
    }

    # 3. Rust
    Write-Step "Проверка Rust..."
    Refresh-Path
    if (Test-Command "rustc") {
        Write-OK "Rust $(rustc --version)"
    } else {
        Write-Info "Rust не найден. Устанавливаю через winget..."
        winget install --id Rustlang.Rustup --silent --accept-package-agreements --accept-source-agreements
        Refresh-Path
        # rustup устанавливает rustc — нужно дождаться
        Start-Sleep -Seconds 5
        Refresh-Path
        if (Test-Command "rustc") {
            Write-OK "Rust установлен: $(rustc --version)"
        } else {
            Write-Warn "Rust установлен, но требует перезапуска терминала."
            Write-Info "Откройте новый PowerShell и запустите: rustup install stable"
            Pause-ForUser "После установки Rust нажмите любую клавишу..."
            Refresh-Path
        }
    }

    # 4. Visual Studio Build Tools
    Write-Step "Проверка Visual Studio Build Tools..."
    $vsBuildTools = Get-ItemProperty "HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\*" -ErrorAction SilentlyContinue |
                    Where-Object { $_.DisplayName -like "*Build Tools*" -or $_.DisplayName -like "*Visual Studio*" }
    $msBuild = Get-Command "msbuild.exe" -ErrorAction SilentlyContinue
    $clExe = Get-ChildItem "C:\Program Files (x86)\Microsoft Visual Studio\*\BuildTools\VC\Tools\MSVC\*\bin\Hostx64\x64\cl.exe" -ErrorAction SilentlyContinue |
             Select-Object -First 1
    $clExe2 = Get-ChildItem "C:\Program Files\Microsoft Visual Studio\*\BuildTools\VC\Tools\MSVC\*\bin\Hostx64\x64\cl.exe" -ErrorAction SilentlyContinue |
              Select-Object -First 1

    if ($clExe -or $clExe2 -or $msBuild) {
        Write-OK "Visual Studio Build Tools найдены"
    } else {
        Write-Info "VS Build Tools не найдены. Устанавливаю (это займёт 5-15 минут)..."
        Write-Warn "Нужен компонент 'Desktop development with C++'"
        winget install --id Microsoft.VisualStudio.2022.BuildTools `
            --silent --accept-package-agreements --accept-source-agreements `
            --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
        Write-OK "VS Build Tools установлены"
    }

    # 5. WebView2
    Write-Step "Проверка WebView2..."
    $wv2 = Get-ItemProperty "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" -ErrorAction SilentlyContinue
    $wv2User = Get-ItemProperty "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" -ErrorAction SilentlyContinue
    if ($wv2 -or $wv2User) {
        Write-OK "WebView2 установлен"
    } else {
        Write-Info "WebView2 не найден. Устанавливаю..."
        winget install --id Microsoft.EdgeWebView2Runtime --silent --accept-package-agreements --accept-source-agreements
        Write-OK "WebView2 установлен"
    }

    # 6. Python 3.8+
    Write-Step "Проверка Python..."
    Refresh-Path
    $pythonCmd = @("python","python3","py") | Where-Object { Test-Command $_ } | Select-Object -First 1
    if ($pythonCmd) {
        $pyVer = & $pythonCmd --version 2>&1
        Write-OK "$pyVer (команда: $pythonCmd)"
    } else {
        Write-Info "Python не найден. Устанавливаю..."
        winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
        Refresh-Path
        Write-OK "Python установлен: $(python --version 2>&1)"
    }

    # 7. Claude CLI
    Write-Step "Проверка Claude CLI..."
    Refresh-Path
    if (Test-Command "claude") {
        Write-OK "Claude CLI найден: $(claude --version 2>&1)"
    } else {
        Write-Info "Claude CLI не найден. Устанавливаю через npm..."
        npm install -g @anthropic-ai/claude-code
        Refresh-Path
        if (Test-Command "claude") {
            Write-OK "Claude CLI установлен: $(claude --version 2>&1)"
        } else {
            Write-Warn "Claude CLI установлен, но требует авторизации."
        }
        Write-Warn "Не забудьте авторизоваться: claude auth"
        Write-Info "Откройте новый терминал и выполните: claude auth"
    }

    # Итог зависимостей
    Write-Host "`n═══ ЗАВИСИМОСТИ: ГОТОВО ═══" -ForegroundColor Green
    Write-Info "Node.js: $(node --version 2>&1)"
    Write-Info "npm:     $(npm --version 2>&1)"
    Write-Info "Rust:    $((rustc --version 2>&1) ?? 'требует перезапуск терминала')"
    Write-Info "Python:  $((python --version 2>&1) ?? (py --version 2>&1) ?? 'не найден')"
    Write-Info "Claude:  $((claude --version 2>&1) ?? 'не найден — требует: claude auth')"
}

# ─── БЛОК 2: Сборка приложений ───────────────────────────────────────────────

if (-not $SkipBuild) {

    Write-Host "`n═══ СБОРКА ПРИЛОЖЕНИЙ ═══" -ForegroundColor DarkCyan
    Write-Info "Будут собраны: $($Apps.Name -join ', ')"

    $Built   = @()
    $Failed  = @()

    foreach ($app in $Apps) {
        Write-Step "$($app.Name)"
        Write-Info "Путь: $($app.Path)"

        if (-not (Test-Path $app.Path)) {
            Write-Fail "Директория не найдена: $($app.Path)"
            $Failed += $app.Name
            continue
        }

        Push-Location $app.Path
        try {
            # npm install
            Write-Info "npm install..."
            $npmResult = npm install 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw "npm install завершился с ошибкой: $npmResult"
            }

            # tauri build
            Write-Info "npm run tauri build (это займёт 3-10 минут)..."
            $start = Get-Date
            npm run tauri build 2>&1 | ForEach-Object {
                # Показывать только важные строки
                if ($_ -match "Compiling|Finished|error\[|warning:|Bundling|✓|Built") {
                    Write-Info "  $_"
                }
            }

            if ($LASTEXITCODE -ne 0) {
                throw "tauri build завершился с ошибкой"
            }

            $elapsed = [int]((Get-Date) - $start).TotalSeconds

            # Найти артефакт
            $nsis = Get-ChildItem "$($app.Path)\src-tauri\target\release\bundle\nsis\*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
            $msi  = Get-ChildItem "$($app.Path)\src-tauri\target\release\bundle\msi\*.msi"  -ErrorAction SilentlyContinue | Select-Object -First 1

            if ($nsis) {
                Write-OK "ГОТОВО (${elapsed}с) → $($nsis.Name)"
            } elseif ($msi) {
                Write-OK "ГОТОВО (${elapsed}с) → $($msi.Name)"
            } else {
                Write-OK "ГОТОВО (${elapsed}с) — артефакт в src-tauri\target\release\bundle\"
            }
            $Built += $app.Name

        } catch {
            Write-Fail "Ошибка сборки: $_"
            $Failed += $app.Name
        } finally {
            Pop-Location
        }
    }

    # ─── Итоговый отчёт ─────────────────────────────────────────────────────

    Write-Host "`n" + "=" * 60 -ForegroundColor DarkCyan
    Write-Host "  РЕЗУЛЬТАТ СБОРКИ" -ForegroundColor White
    Write-Host "=" * 60 -ForegroundColor DarkCyan

    if ($Built.Count -gt 0) {
        Write-Host "`n  Собраны успешно ($($Built.Count)):" -ForegroundColor Green
        $Built | ForEach-Object { Write-Host "    ✓ $_" -ForegroundColor Green }
    }
    if ($Failed.Count -gt 0) {
        Write-Host "`n  Ошибки ($($Failed.Count)):" -ForegroundColor Red
        $Failed | ForEach-Object { Write-Host "    ✗ $_" -ForegroundColor Red }
        Write-Host "`n  Проверьте лог выше для деталей ошибки." -ForegroundColor DarkYellow
    }

    Write-Host "`n  Инсталляторы (.exe) находятся в:" -ForegroundColor Cyan
    $Apps | Where-Object { Test-Path $_.Path } | ForEach-Object {
        Write-Host "    $($_.Path)\src-tauri\target\release\bundle\nsis\" -ForegroundColor Gray
    }
}

Write-Host "`nГотово. Нажмите любую клавишу..." -ForegroundColor DarkCyan
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
