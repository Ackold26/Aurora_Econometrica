#Requires -Version 5.1
<#
    AURORA AI ECONOMETRICA
    Очистка остаточных файлов после деинсталляции

    Запускать ПОСЛЕ удаления приложения через Windows
    (Пуск → Настройки → Приложения → Установленные приложения).
    Обрабатывает обе редакции – облачную и локальную (152-ФЗ), какая найдётся на машине.
    Запуск: правой кнопкой → "Выполнить с помощью PowerShell"
#>

$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]"Administrator")
if (-not $isAdmin) {
    Start-Process powershell.exe "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs; exit
}

$AppName = "Aurora AI Econometrica"
# Обе редакции продукта используют раздельное per-app хранение (свой identifier) –
# скрипт проходит по обеим, чистит только ту, что реально найдётся на машине.
$Editions = @(
    @{ Id = "com.aurora.econometrica";       Label = "облачная редакция" },
    @{ Id = "com.aurora.econometrica.local"; Label = "локальная редакция (152-ФЗ)" }
)

Clear-Host
Write-Host ""
Write-Host "  =============================================" -ForegroundColor DarkRed
Write-Host "   $AppName" -ForegroundColor White
Write-Host "   Очистка остаточных файлов" -ForegroundColor Gray
Write-Host "  =============================================" -ForegroundColor DarkRed
Write-Host ""
Write-Host "  Будут удалены (для каждой найденной редакции):" -ForegroundColor Yellow
Write-Host "  • Лицензия и служебные файлы: license.json, vault_salt.bin," -ForegroundColor Gray
Write-Host "    session_cache.json, vault-versions.json, instance.id" -ForegroundColor Gray
Write-Host "  • Vault-файлы кабинетов и журналы приложения" -ForegroundColor Gray
Write-Host "  • Пакеты контента, кэш WebView2 и служебное состояние sidecar" -ForegroundColor Gray
Write-Host ""
Write-Host "  НЕ будут затронуты: ваши сохранённые результаты и проекты" -ForegroundColor Cyan
Write-Host "  (папка Desktop\AIAgency\ или указанная вами папка результатов)." -ForegroundColor Cyan
Write-Host ""
Write-Host "  ВНИМАНИЕ: Действие необратимо!" -ForegroundColor Red
Write-Host ""

$confirm = Read-Host "  Продолжить? (y/N)"
if ($confirm -notmatch '^[yYдД]$') {
    Write-Host "  Отменено." -ForegroundColor DarkGray
    Write-Host ""
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 0
}

Write-Host ""
$removed = 0
$skipped = 0

function Remove-Safe {
    param($Path, $Label, [switch]$Recurse)
    if (Test-Path $Path) {
        try {
            if ($Recurse) { Remove-Item $Path -Recurse -Force }
            else { Remove-Item $Path -Force }
            Write-Host "  [OK] Удалено: $Label" -ForegroundColor Green
            $script:removed++
        } catch {
            Write-Host "  [!!] Ошибка: $Label – $_" -ForegroundColor Red
        }
    } else {
        Write-Host "  [--] Не найдено (пропущено): $Label" -ForegroundColor DarkGray
        $script:skipped++
    }
}

function Remove-EmptyDir {
    param($Path)
    if ((Test-Path $Path) -and (@(Get-ChildItem $Path -Recurse -ErrorAction SilentlyContinue).Count -eq 0)) {
        Remove-Item $Path -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "  [OK] Пустая папка удалена: $Path" -ForegroundColor DarkGreen
    }
}

foreach ($edition in $Editions) {
    $id    = $edition.Id
    $label = $edition.Label

    # %APPDATA%\<identifier>\ – конфигурация, лицензия, vault-файлы кабинетов, журналы
    $appDataDir = Join-Path $env:APPDATA $id
    Remove-Safe (Join-Path $appDataDir "license.json")          "лицензия ($label)"
    Remove-Safe (Join-Path $appDataDir "vault_salt.bin")        "ключ шифрования vault ($label)"
    Remove-Safe (Join-Path $appDataDir "session_cache.json")    "кэш авторизации ($label)"
    Remove-Safe (Join-Path $appDataDir "vault-versions.json")   "версии vault-файлов ($label)"
    Remove-Safe (Join-Path $appDataDir "content_version.txt")   "версия контента, устар. формат ($label)"
    Remove-Safe (Join-Path $appDataDir "instance.id")           "идентификатор установки ($label)"
    Remove-Safe (Join-Path $appDataDir "vaults")                "vault-файлы кабинетов ($label)" -Recurse
    Remove-Safe (Join-Path $appDataDir "logs")                  "журналы приложения ($label)" -Recurse
    Remove-EmptyDir $appDataDir

    # %LOCALAPPDATA%\<identifier>\ – пакеты контента, версии фронтенда, кэш WebView2, sidecar
    $localDataDir = Join-Path $env:LOCALAPPDATA $id
    Remove-Safe (Join-Path $localDataDir "content-packs")               "пакеты контента ($label)" -Recurse
    Remove-Safe (Join-Path $localDataDir "content-packs-new")           "остаток обновления, staging ($label)" -Recurse
    Remove-Safe (Join-Path $localDataDir "content-packs-old")           "остаток обновления, резерв ($label)" -Recurse
    Remove-Safe (Join-Path $localDataDir "current_frontend_version.txt") "версия интерфейса ($label)"
    Remove-Safe (Join-Path $localDataDir "EBWebView")                   "кэш WebView2 ($label)" -Recurse
    Remove-Safe (Join-Path $localDataDir "sidecar.json")                "состояние фонового процесса ($label)"
    Remove-Safe (Join-Path $localDataDir "logs")                        "журналы приложения, альт. путь ($label)" -Recurse

    if (Test-Path $localDataDir) {
        $frontendDirs = Get-ChildItem -Path $localDataDir -Directory -Filter "frontend-*" -ErrorAction SilentlyContinue
        foreach ($fd in $frontendDirs) {
            Remove-Safe $fd.FullName "версия интерфейса $($fd.Name) ($label)" -Recurse
        }
    }
    Remove-EmptyDir $localDataDir
}

Write-Host ""
Write-Host "  =============================================" -ForegroundColor DarkGreen
Write-Host "  Готово. Удалено: $removed, пропущено: $skipped" -ForegroundColor Green
Write-Host "  =============================================" -ForegroundColor DarkGreen
Write-Host ""
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
